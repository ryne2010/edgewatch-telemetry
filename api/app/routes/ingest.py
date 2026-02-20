from __future__ import annotations

import uuid

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.dialects.postgresql import insert

from ..config import settings
from ..contracts import load_telemetry_contract
from ..db import db_session
from ..models import Device, TelemetryPoint, IngestionBatch
from ..schemas import IngestRequest, IngestResponse
from ..security import require_device_auth
from ..services.monitor import ensure_water_pressure_alerts

router = APIRouter(prefix="/api/v1", tags=["ingest"])


def _normalize_utc(dt: datetime) -> datetime:
    """Normalize an incoming datetime to timezone-aware UTC.

    - If dt is naive, assume UTC.
    - If dt has tzinfo, convert to UTC.

    We keep ingestion semantics based on the *device timestamp*, not delivery time.
    """

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@router.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest, device: Device = Depends(require_device_auth)) -> IngestResponse:
    """Ingest a batch of points for the authenticated device.

    Notes:
      * Inserts are idempotent per (device_id, message_id) via a unique constraint.
      * We bulk-insert for performance, then evaluate threshold alerts only for newly-inserted points.
      * last_seen_at is updated based on the newest *inserted* point timestamp.
    """

    # Load the active telemetry contract.
    try:
        contract = load_telemetry_contract(settings.telemetry_contract_version)
    except Exception:
        # Don't leak file paths or stack traces to devices.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="telemetry contract is not available",
        )

    with db_session() as session:
        rows: list[dict] = []
        batch_id = str(uuid.uuid4())

        # Contract validation + drift visibility (unknown keys).
        unknown_keys_union: set[str] = set()
        type_errors: list[str] = []

        # Keep the *first* seen point for any message_id in this request so we can evaluate
        # alerts based on what actually got inserted when duplicates are present in the same batch.
        point_by_message_id: dict[str, tuple[datetime, dict]] = {}

        client_ts_min: datetime | None = None
        client_ts_max: datetime | None = None

        for p in req.points:
            ts = _normalize_utc(p.ts)

            if client_ts_min is None or ts < client_ts_min:
                client_ts_min = ts
            if client_ts_max is None or ts > client_ts_max:
                client_ts_max = ts

            unknown_keys, errors = contract.validate_metrics(p.metrics)
            unknown_keys_union |= unknown_keys
            if settings.telemetry_contract_enforce_types:
                type_errors.extend(errors)

            if p.message_id not in point_by_message_id:
                point_by_message_id[p.message_id] = (ts, p.metrics)

            rows.append(
                {
                    "id": str(uuid.uuid4()),
                    "message_id": p.message_id,
                    "device_id": device.device_id,
                    "batch_id": batch_id,
                    "ts": ts,
                    "metrics": p.metrics,
                }
            )

        if not rows:
            return IngestResponse(device_id=device.device_id, batch_id=batch_id, accepted=0, duplicates=0)

        if type_errors:
            # Avoid flooding: show only the first handful.
            sample = type_errors[:10]
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "telemetry metrics failed contract validation",
                    "contract_version": contract.version,
                    "contract_hash": contract.sha256,
                    "errors": sample,
                    "error_count": len(type_errors),
                },
            )

        # Create an ingestion batch row first (flush to satisfy FK constraint).
        batch = IngestionBatch(
            id=batch_id,
            device_id=device.device_id,
            contract_version=contract.version,
            contract_hash=contract.sha256,
            points_submitted=len(rows),
            points_accepted=0,
            duplicates=0,
            client_ts_min=client_ts_min,
            client_ts_max=client_ts_max,
            unknown_metric_keys=sorted(unknown_keys_union),
        )
        session.add(batch)
        session.flush()

        stmt = (
            insert(TelemetryPoint)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["device_id", "message_id"])
            .returning(TelemetryPoint.message_id)
        )

        inserted_message_ids = list(session.execute(stmt).scalars().all())
        accepted = len(inserted_message_ids)
        duplicates = len(rows) - accepted

        batch.points_accepted = accepted
        batch.duplicates = duplicates

        newest_ts: datetime | None = None

        # Threshold alert evaluation on newly-inserted points only.
        for mid in inserted_message_ids:
            if mid not in point_by_message_id:
                continue
            ts, metrics = point_by_message_id[mid]

            if newest_ts is None or ts > newest_ts:
                newest_ts = ts

            wp = metrics.get("water_pressure_psi")
            if isinstance(wp, (int, float)):
                ensure_water_pressure_alerts(session, device.device_id, float(wp), ts)

        if newest_ts is not None:
            d = session.query(Device).filter(Device.device_id == device.device_id).one()
            if d.last_seen_at is None or newest_ts > d.last_seen_at:
                d.last_seen_at = newest_ts

    return IngestResponse(
        device_id=device.device_id, batch_id=batch_id, accepted=accepted, duplicates=duplicates
    )
