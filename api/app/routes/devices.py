from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc

from ..db import db_session
from ..models import Device, TelemetryPoint
from ..schemas import DeviceOut, TimeseriesMultiPointOut, TimeseriesPointOut
from ..services.monitor import compute_status

router = APIRouter(prefix="/api/v1", tags=["devices"])


# Normalize optional datetime query params to UTC.
#
# FastAPI/Pydantic may parse datetimes as naive depending on the client;
# comparing naive datetimes to Postgres timestamptz columns is error-prone,
# so we normalize consistently.


def _normalize_opt_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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


@router.get("/devices/{device_id}", response_model=DeviceOut)
def get_device(device_id: str) -> DeviceOut:
    now = datetime.now(timezone.utc)
    with db_session() as session:
        d = session.query(Device).filter(Device.device_id == device_id).one_or_none()
        if d is None:
            raise HTTPException(status_code=404, detail="Device not found")

        status, seconds = compute_status(d, now)
        return DeviceOut(
            device_id=d.device_id,
            display_name=d.display_name,
            heartbeat_interval_s=d.heartbeat_interval_s,
            offline_after_s=d.offline_after_s,
            last_seen_at=d.last_seen_at,
            enabled=d.enabled,
            status=status,
            seconds_since_last_seen=seconds,
        )


@router.get("/devices/{device_id}/telemetry")
def get_telemetry(
    device_id: str,
    metric: Optional[str] = Query(
        default=None, description="If set, return only points containing this metric key"
    ),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
):
    """Return raw telemetry points. Intended for debugging and small time windows."""
    since = _normalize_opt_utc(since)
    until = _normalize_opt_utc(until)
    if since is not None and until is not None and since > until:
        raise HTTPException(status_code=400, detail="since must be <= until")
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
    from sqlalchemy import Float, case, cast, func

    date_trunc_unit = "minute" if bucket == "minute" else "hour"

    since = _normalize_opt_utc(since)
    until = _normalize_opt_utc(until)
    if since is not None and until is not None and since > until:
        raise HTTPException(status_code=400, detail="since must be <= until")

    with db_session() as session:
        value_text = TelemetryPoint.metrics[metric].astext
        # Avoid runtime errors when the JSON value isn't numeric (bad data / drift).
        numeric_value = case(
            (
                value_text.op("~")(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$"),
                cast(value_text, Float),
            ),
            else_=None,
        )

        q = session.query(
            func.date_trunc(date_trunc_unit, TelemetryPoint.ts).label("bucket_ts"),
            func.avg(numeric_value).label("value"),
        ).filter(TelemetryPoint.device_id == device_id)

        # Only include points that have the metric key
        q = q.filter(TelemetryPoint.metrics.has_key(metric))

        if since is not None:
            q = q.filter(TelemetryPoint.ts >= since)
        if until is not None:
            q = q.filter(TelemetryPoint.ts <= until)

        q = q.group_by("bucket_ts").order_by(desc("bucket_ts")).limit(limit)
        rows = q.all()

        # Return ascending for chart friendliness
        return [
            TimeseriesPointOut(bucket_ts=r.bucket_ts, value=float(r.value))
            for r in reversed(rows)
            if r.value is not None
        ]


@router.get("/devices/{device_id}/timeseries_multi", response_model=List[TimeseriesMultiPointOut])
def get_timeseries_multi(
    device_id: str,
    metrics: List[str] = Query(
        ..., description="Metric keys, e.g. metrics=water_pressure_psi&metrics=oil_pressure_psi"
    ),
    bucket: str = Query("minute", pattern="^(minute|hour)$", description="Bucket size: minute|hour"),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
):
    """Return multiple bucketed time series in a single request.

    Uses a single GROUP BY with per-metric FILTER aggregations, so the UI can switch metrics instantly.
    """
    from sqlalchemy import Float, case, cast, func

    date_trunc_unit = "minute" if bucket == "minute" else "hour"

    since = _normalize_opt_utc(since)
    until = _normalize_opt_utc(until)
    if since is not None and until is not None and since > until:
        raise HTTPException(status_code=400, detail="since must be <= until")

    # Basic input hygiene: avoid empty keys and enforce a small upper bound to prevent accidental abuse.
    unique_metrics: list[str] = []
    seen: set[str] = set()
    for m in metrics:
        mm = (m or "").strip()
        if not mm:
            continue
        if mm in seen:
            continue
        seen.add(mm)
        unique_metrics.append(mm)
    if not unique_metrics:
        raise HTTPException(status_code=400, detail="metrics must include at least one metric key")
    if len(unique_metrics) > 10:
        raise HTTPException(status_code=400, detail="metrics must include at most 10 metric keys")

    bucket_ts = func.date_trunc(date_trunc_unit, TelemetryPoint.ts).label("bucket_ts")
    cols = [bucket_ts]
    for m in unique_metrics:
        value_text = TelemetryPoint.metrics[m].astext
        numeric_value = case(
            (
                value_text.op("~")(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$"),
                cast(value_text, Float),
            ),
            else_=None,
        )

        value = func.avg(numeric_value).filter(TelemetryPoint.metrics.has_key(m)).label(m)
        cols.append(value)

    with db_session() as session:
        q = session.query(*cols).filter(TelemetryPoint.device_id == device_id)
        if since is not None:
            q = q.filter(TelemetryPoint.ts >= since)
        if until is not None:
            q = q.filter(TelemetryPoint.ts <= until)
        q = q.group_by(bucket_ts).order_by(desc(bucket_ts)).limit(limit)
        rows = q.all()

        out: list[TimeseriesMultiPointOut] = []
        for r in reversed(rows):
            values: dict[str, Optional[float]] = {}
            for m in unique_metrics:
                v = getattr(r, m)
                values[m] = float(v) if v is not None else None
            out.append(TimeseriesMultiPointOut(bucket_ts=r.bucket_ts, values=values))
        return out
