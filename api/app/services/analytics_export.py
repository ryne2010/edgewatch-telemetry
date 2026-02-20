from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, Sequence

from sqlalchemy.orm import Session

from ..config import settings
from ..contracts import load_telemetry_contract
from ..models import ExportBatch, TelemetryPoint


class StorageClient(Protocol):
    def upload_jsonl(self, *, bucket: str, object_name: str, rows: Sequence[dict[str, Any]]) -> str: ...


class BigQueryClient(Protocol):
    def ensure_table(self, *, dataset: str, table: str) -> None: ...

    def load_jsonl_from_gcs(self, *, dataset: str, table: str, gcs_uri: str) -> None: ...


@dataclass(frozen=True)
class ExportSlice:
    watermark_from: datetime | None
    watermark_to: datetime | None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def compute_export_slice(
    *,
    created_ats: Sequence[datetime],
    watermark_from: datetime | None,
    max_rows: int,
) -> ExportSlice:
    if max_rows <= 0:
        raise ValueError("max_rows must be positive")

    eligible = [ts for ts in created_ats if watermark_from is None or ts > watermark_from]
    if not eligible:
        return ExportSlice(watermark_from=watermark_from, watermark_to=None)

    ordered = sorted(eligible)
    head = ordered[:max_rows]
    return ExportSlice(watermark_from=watermark_from, watermark_to=head[-1])


def _default_project_id() -> str | None:
    return settings.ingest_pubsub_project_id


class GoogleStorageClient:
    def upload_jsonl(self, *, bucket: str, object_name: str, rows: Sequence[dict[str, Any]]) -> str:
        from google.cloud import storage  # type: ignore[import-not-found]

        client = storage.Client(project=_default_project_id())
        blob = client.bucket(bucket).blob(object_name)

        payload = "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows)
        if payload:
            payload = payload + "\n"

        blob.upload_from_string(payload, content_type="application/x-ndjson")
        return f"gs://{bucket}/{object_name}"


class GoogleBigQueryClient:
    def __init__(self) -> None:
        from google.cloud import bigquery  # type: ignore[import-not-found]

        self._bigquery = bigquery
        self._client = bigquery.Client(project=_default_project_id())

    def ensure_table(self, *, dataset: str, table: str) -> None:
        bq = self._bigquery
        project_id = self._client.project

        dataset_ref = bq.DatasetReference(project_id, dataset)
        table_ref = dataset_ref.table(table)

        dataset_obj = bq.Dataset(dataset_ref)
        dataset_obj.location = "US"
        self._client.create_dataset(dataset_obj, exists_ok=True)

        schema = [
            bq.SchemaField("ts", "TIMESTAMP"),
            bq.SchemaField("created_at", "TIMESTAMP"),
            bq.SchemaField("device_id", "STRING"),
            bq.SchemaField("message_id", "STRING"),
            bq.SchemaField("batch_id", "STRING"),
            bq.SchemaField("ingestion_batch_id", "STRING"),
            bq.SchemaField("contract_version", "STRING"),
            bq.SchemaField("contract_hash", "STRING"),
            bq.SchemaField("metrics", "JSON"),
        ]

        table_obj = bq.Table(table_ref, schema=schema)
        table_obj.time_partitioning = bq.TimePartitioning(
            type_=bq.TimePartitioningType.DAY,
            field="ts",
        )
        table_obj.clustering_fields = ["device_id", "message_id"]

        self._client.create_table(table_obj, exists_ok=True)

    def load_jsonl_from_gcs(self, *, dataset: str, table: str, gcs_uri: str) -> None:
        bq = self._bigquery
        project_id = self._client.project

        table_id = f"{project_id}.{dataset}.{table}"
        config = bq.LoadJobConfig(
            source_format=bq.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bq.WriteDisposition.WRITE_APPEND,
        )
        load_job = self._client.load_table_from_uri(gcs_uri, table_id, job_config=config)
        load_job.result()


def _load_last_success_watermark(session: Session) -> datetime | None:
    row = (
        session.query(ExportBatch)
        .filter(ExportBatch.status == "success", ExportBatch.watermark_to.is_not(None))
        .order_by(ExportBatch.finished_at.desc())
        .first()
    )
    if row is None:
        return None
    return row.watermark_to


def _serialize_row(
    *,
    point: TelemetryPoint,
    export_batch_id: str,
    contract_version: str,
    contract_hash: str,
) -> dict[str, Any]:
    return {
        "ts": point.ts.isoformat(),
        "created_at": point.created_at.isoformat(),
        "device_id": point.device_id,
        "message_id": point.message_id,
        "batch_id": export_batch_id,
        "ingestion_batch_id": point.batch_id,
        "contract_version": contract_version,
        "contract_hash": contract_hash,
        "metrics": point.metrics,
    }


def run_export_once(
    session: Session,
    *,
    now: datetime | None = None,
    storage_client: StorageClient | None = None,
    bigquery_client: BigQueryClient | None = None,
) -> ExportBatch:
    ts_now = now or utcnow()

    if not settings.analytics_export_enabled:
        raise RuntimeError("ANALYTICS_EXPORT_ENABLED is false")
    if not settings.analytics_export_bucket:
        raise RuntimeError("ANALYTICS_EXPORT_BUCKET is required when analytics export is enabled")

    contract = load_telemetry_contract(settings.telemetry_contract_version)
    watermark_from = _load_last_success_watermark(session)

    q = session.query(TelemetryPoint).order_by(TelemetryPoint.created_at.asc(), TelemetryPoint.id.asc())
    if watermark_from is not None:
        q = q.filter(TelemetryPoint.created_at > watermark_from)

    points = q.limit(max(1, settings.analytics_export_max_rows)).all()

    export_batch = ExportBatch(
        started_at=ts_now,
        watermark_from=watermark_from,
        watermark_to=watermark_from,
        contract_version=contract.version,
        contract_hash=contract.sha256,
        status="running",
    )
    session.add(export_batch)
    session.flush()

    if not points:
        export_batch.finished_at = ts_now
        export_batch.row_count = 0
        export_batch.status = "success"
        return export_batch

    watermark_to = points[-1].created_at
    export_batch.watermark_to = watermark_to

    rows = [
        _serialize_row(
            point=point,
            export_batch_id=export_batch.id,
            contract_version=contract.version,
            contract_hash=contract.sha256,
        )
        for point in points
    ]

    bucket = settings.analytics_export_bucket
    object_name = (
        f"{settings.analytics_export_gcs_prefix.rstrip('/')}/"
        f"{ts_now.strftime('%Y/%m/%d')}/"
        f"export_batch_{export_batch.id}.jsonl"
    )

    storage = storage_client or GoogleStorageClient()
    bigquery = bigquery_client or GoogleBigQueryClient()

    try:
        gcs_uri = storage.upload_jsonl(bucket=bucket, object_name=object_name, rows=rows)
        bigquery.ensure_table(
            dataset=settings.analytics_export_dataset, table=settings.analytics_export_table
        )
        bigquery.load_jsonl_from_gcs(
            dataset=settings.analytics_export_dataset,
            table=settings.analytics_export_table,
            gcs_uri=gcs_uri,
        )

        export_batch.gcs_uri = gcs_uri
        export_batch.row_count = len(rows)
        export_batch.finished_at = utcnow()
        export_batch.status = "success"
        export_batch.error_message = None
    except Exception as exc:
        export_batch.finished_at = utcnow()
        export_batch.status = "failed"
        export_batch.error_message = f"{type(exc).__name__}: analytics export failed"

    return export_batch
