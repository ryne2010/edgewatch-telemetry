from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..db import db_session
from ..models import Device, TelemetryPoint
from ..schemas import DeviceOut, TimeseriesPointOut
from ..services.monitor import compute_status

router = APIRouter(prefix="/api/v1", tags=["devices"])


@router.get("/devices", response_model=List[DeviceOut])
def list_devices() -> List[DeviceOut]:
    now = datetime.now(timezone.utc)
    with db_session() as session:
        devices = session.query(Device).order_by(Device.device_id.asc()).all()
        out: List[DeviceOut] = []
        for d in devices:
            status, seconds = compute_status(d, now)
            out.append(
                DeviceOut(
                    device_id=d.device_id,
                    display_name=d.display_name,
                    heartbeat_interval_s=d.heartbeat_interval_s,
                    offline_after_s=d.offline_after_s,
                    last_seen_at=d.last_seen_at,
                    enabled=d.enabled,
                    status=status,
                    seconds_since_last_seen=seconds,
                )
            )
        return out


@router.get("/devices/{device_id}/telemetry")
def get_telemetry(
    device_id: str,
    metric: Optional[str] = Query(default=None, description="If set, return only points containing this metric key"),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
):
    """Return raw telemetry points. Intended for debugging and small time windows."""
    with db_session() as session:
        q = session.query(TelemetryPoint).filter(TelemetryPoint.device_id == device_id)
        if since is not None:
            q = q.filter(TelemetryPoint.ts >= since)
        if until is not None:
            q = q.filter(TelemetryPoint.ts <= until)
        q = q.order_by(desc(TelemetryPoint.ts)).limit(limit)
        rows = q.all()

        def _keep(row: TelemetryPoint) -> bool:
            if metric is None:
                return True
            return metric in (row.metrics or {})

        return [
            {
                "message_id": r.message_id,
                "device_id": r.device_id,
                "ts": r.ts,
                "metrics": r.metrics,
            }
            for r in rows
            if _keep(r)
        ]


@router.get("/devices/{device_id}/timeseries", response_model=List[TimeseriesPointOut])
def get_timeseries(
    device_id: str,
    metric: str = Query(..., description="Metric key, e.g. water_pressure_psi"),
    bucket: str = Query("minute", pattern="^(minute|hour)$", description="Bucket size: minute|hour"),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
):
    """Return bucketed time series (server-side aggregation)."""
    from sqlalchemy import func, cast, Float
    from sqlalchemy.dialects.postgresql import JSONB

    date_trunc_unit = "minute" if bucket == "minute" else "hour"

    with db_session() as session:
        q = session.query(
            func.date_trunc(date_trunc_unit, TelemetryPoint.ts).label("bucket_ts"),
            func.avg(cast(TelemetryPoint.metrics[metric].astext, Float)).label("value"),
        ).filter(TelemetryPoint.device_id == device_id)

        # Only include points that have the metric key
        q = q.filter(TelemetryPoint.metrics.has_key(metric))  # noqa: W601

        if since is not None:
            q = q.filter(TelemetryPoint.ts >= since)
        if until is not None:
            q = q.filter(TelemetryPoint.ts <= until)

        q = q.group_by("bucket_ts").order_by(desc("bucket_ts")).limit(limit)
        rows = q.all()

        # Return ascending for chart friendliness
        return [TimeseriesPointOut(bucket_ts=r.bucket_ts, value=float(r.value)) for r in reversed(rows) if r.value is not None]
