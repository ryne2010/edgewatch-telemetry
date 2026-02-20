from __future__ import annotations

from datetime import datetime, timedelta, timezone
import types
from typing import Any, cast

from api.app.models import ExportBatch, TelemetryPoint
from api.app.services import analytics_export


class _FakeQuery:
    def __init__(self, data):
        self._data = data
        self._limit: int | None = None

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def first(self):
        if isinstance(self._data, list):
            return self._data[0] if self._data else None
        return self._data

    def limit(self, n: int):
        self._limit = n
        return self

    def all(self):
        if not isinstance(self._data, list):
            return []
        if self._limit is None:
            return list(self._data)
        return list(self._data)[: self._limit]


class _FakeSession:
    def __init__(self, *, points: list[TelemetryPoint], last_success: ExportBatch | None = None):
        self._points = points
        self._last_success = last_success
        self.added: list[object] = []

    def query(self, model):
        if model is ExportBatch:
            return _FakeQuery([self._last_success] if self._last_success else [])
        if model is TelemetryPoint:
            return _FakeQuery(self._points)
        raise AssertionError(f"unexpected query model: {model}")

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        for obj in self.added:
            if isinstance(obj, ExportBatch) and not obj.id:
                obj.id = "exp-batch-001"


class _FakeStorage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def upload_jsonl(self, *, bucket: str, object_name: str, rows):
        self.calls.append((bucket, object_name, len(rows)))
        return f"gs://{bucket}/{object_name}"


class _FakeBigQuery:
    def __init__(self) -> None:
        self.ensure_calls: list[tuple[str, str]] = []
        self.load_calls: list[tuple[str, str, str]] = []

    def ensure_table(self, *, dataset: str, table: str) -> None:
        self.ensure_calls.append((dataset, table))

    def load_jsonl_from_gcs(self, *, dataset: str, table: str, gcs_uri: str) -> None:
        self.load_calls.append((dataset, table, gcs_uri))


def _point(*, message_id: str, created_at: datetime) -> TelemetryPoint:
    return TelemetryPoint(
        id=f"tp-{message_id}",
        message_id=message_id,
        device_id="dev-1",
        batch_id="ing-batch-1",
        ts=created_at,
        metrics={"water_pressure_psi": 42.0},
        created_at=created_at,
    )


def test_compute_export_slice_respects_watermark_and_limit() -> None:
    base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    created_ats = [base + timedelta(minutes=i) for i in range(5)]

    slice_ = analytics_export.compute_export_slice(
        created_ats=created_ats,
        watermark_from=base,
        max_rows=2,
    )

    assert slice_.watermark_from == base
    assert slice_.watermark_to == base + timedelta(minutes=2)


def test_run_export_once_uses_storage_and_bigquery_clients(monkeypatch) -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    points = [
        _point(message_id="m-1", created_at=now - timedelta(minutes=2)),
        _point(message_id="m-2", created_at=now - timedelta(minutes=1)),
    ]

    fake_settings = types.SimpleNamespace(
        analytics_export_enabled=True,
        analytics_export_bucket="edgewatch-analytics",
        analytics_export_dataset="edgewatch_ds",
        analytics_export_table="telemetry_points",
        analytics_export_gcs_prefix="telemetry",
        analytics_export_max_rows=500,
        telemetry_contract_version="v1",
        ingest_pubsub_project_id="demo-project",
    )
    monkeypatch.setattr(analytics_export, "settings", fake_settings)
    monkeypatch.setattr(
        analytics_export,
        "load_telemetry_contract",
        lambda _version: types.SimpleNamespace(version="v1", sha256="hash-123"),
    )

    storage = _FakeStorage()
    bigquery = _FakeBigQuery()
    session = _FakeSession(points=points)

    batch = analytics_export.run_export_once(
        cast(Any, session),
        now=now,
        storage_client=storage,
        bigquery_client=bigquery,
    )

    assert batch.status == "success"
    assert batch.row_count == 2
    assert batch.gcs_uri is not None and batch.gcs_uri.startswith("gs://edgewatch-analytics/")
    assert storage.calls and storage.calls[0][0] == "edgewatch-analytics"
    assert bigquery.ensure_calls == [("edgewatch_ds", "telemetry_points")]
    assert bigquery.load_calls and bigquery.load_calls[0][2] == batch.gcs_uri
