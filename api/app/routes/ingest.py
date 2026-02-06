from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.dialects.postgresql import insert

from ..db import db_session
from ..models import TelemetryPoint, Device
from ..schemas import IngestRequest, IngestResponse
from ..security import require_device_auth
from ..services.monitor import ensure_water_pressure_alerts

router = APIRouter(prefix="/api/v1", tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest, device: Device = Depends(require_device_auth)) -> IngestResponse:
    accepted = 0
    duplicates = 0

    with db_session() as session:
        # Track last seen based on newest point timestamp
        newest_ts: datetime | None = None

        for p in req.points:
            # Normalize ts to UTC (if naive, assume UTC)
            ts = p.ts
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            stmt = (
                insert(TelemetryPoint)
                .values(
                    message_id=p.message_id,
                    device_id=device.device_id,
                    ts=ts,
                    metrics=p.metrics,
                )
                .on_conflict_do_nothing(index_elements=["message_id"])
                # Use RETURNING instead of `rowcount` to reliably detect whether the insert happened
                # (some DB drivers/dialects may not provide an accurate rowcount for INSERTs).
                .returning(TelemetryPoint.message_id)
            )
            inserted = session.execute(stmt).first()
            if inserted is not None:
                accepted += 1
                if newest_ts is None or ts > newest_ts:
                    newest_ts = ts

                # Example threshold alert: water pressure low
                wp = p.metrics.get("water_pressure_psi")
                if isinstance(wp, (int, float)):
                    ensure_water_pressure_alerts(session, device.device_id, float(wp), ts)
            else:
                duplicates += 1

        if newest_ts is not None:
            # refresh device row and update last_seen if newer
            d = session.query(Device).filter(Device.device_id == device.device_id).one()
            if d.last_seen_at is None or newest_ts > d.last_seen_at:
                d.last_seen_at = newest_ts

    return IngestResponse(device_id=device.device_id, accepted=accepted, duplicates=duplicates)
