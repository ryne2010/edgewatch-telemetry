from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import desc, func

from ..config import settings
from ..db import db_session
from ..models import Device, TelemetryPoint, TelemetryRollupHourly
from ..schemas import DeviceOut, TimeseriesMultiPointOut, TimeseriesPointOut, DeviceSummaryOut
from ..services.monitor import compute_status

router = APIRouter(prefix="/api/v1", tags=["devices"])


METRIC_KEY_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
NUMERIC_TEXT_RE = r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$"


DEFAULT_SUMMARY_METRICS: list[str] = [
    # Fleet vitals shown in the UI (keep this list small + high signal).
    "water_pressure_psi",
    "oil_pressure_psi",
    "temperature_c",
    "humidity_pct",
    "oil_level_pct",
    "oil_life_pct",
    "drip_oil_level_pct",
    "battery_v",
    "signal_rssi_dbm",
    "flow_rate_gpm",
    "pump_on",
]


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


def _json_metric_text_expr(metric_key: str, dialect_name: str):
    # SQLAlchemy 2 no longer exposes .astext on JSON index expressions.
    if dialect_name == "sqlite":
        return func.json_extract(TelemetryPoint.metrics, f"$.{metric_key}")
    return TelemetryPoint.metrics.op("->>")(metric_key)


@router.get("/devices", response_model=List[DeviceOut])
def list_devices() -> List[DeviceOut]:
    now = datetime.now(timezone.utc)
    with db_session() as session:
        devices = session.query(Device).order_by(Device.device_id.asc()).all()
        out: List[DeviceOut] = []
        for d in devices:
            device_status, seconds = compute_status(d, now)
            out.append(
                DeviceOut(
                    device_id=d.device_id,
                    display_name=d.display_name,
                    heartbeat_interval_s=d.heartbeat_interval_s,
                    offline_after_s=d.offline_after_s,
                    last_seen_at=d.last_seen_at,
                    enabled=d.enabled,
                    status=device_status,
                    seconds_since_last_seen=seconds,
                )
            )
        return out


@router.get("/devices/summary", response_model=List[DeviceSummaryOut])
def list_device_summaries(
    metrics: Optional[List[str]] = Query(default=None),
    limit_metrics: int = Query(default=20, ge=1, le=100),
) -> List[DeviceSummaryOut]:
    """Return a fleet-friendly device list with the latest telemetry metrics.

    Why this exists
    - The UI wants to render "fleet vitals" without N+1 API calls.
    - We join devices with each device's *latest* telemetry point.

    Query params
    - metrics: optional repeated query param (metrics=a&metrics=b). If omitted, uses DEFAULT_SUMMARY_METRICS.
    - limit_metrics: safety valve for callers that pass an overly-large list.

    Notes
    - This endpoint is public (no secrets) and returns only *latest* metrics per device.
    """

    requested: List[str]
    if metrics:
        requested = [m.strip() for m in metrics if (m or "").strip()]
    else:
        requested = list(DEFAULT_SUMMARY_METRICS)

    # Defensive limits (avoid returning huge JSON blobs per device).
    if len(requested) > limit_metrics:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many metrics requested (max {limit_metrics})",
        )

    # De-dupe while preserving order.
    seen: set[str] = set()
    unique_metrics: List[str] = []
    for metric_name in requested:
        if metric_name in seen:
            continue
        if not METRIC_KEY_RE.fullmatch(metric_name):
            continue
        seen.add(metric_name)
        unique_metrics.append(metric_name)

    now = datetime.now(timezone.utc)

    with db_session() as session:
        tp = TelemetryPoint
        rn = (
            func.row_number()
            .over(partition_by=tp.device_id, order_by=(tp.ts.desc(), tp.created_at.desc()))
            .label("rn")
        )
        ranked = (
            session.query(
                tp.device_id.label("device_id"),
                tp.ts.label("ts"),
                tp.message_id.label("message_id"),
                tp.metrics.label("metrics"),
                rn,
            )
        ).subquery()

        latest = session.query(ranked).filter(ranked.c.rn == 1).subquery()

        rows = (
            session.query(Device, latest.c.ts, latest.c.message_id, latest.c.metrics)
            .outerjoin(latest, latest.c.device_id == Device.device_id)
            .order_by(Device.device_id)
            .all()
        )

        out: List[DeviceSummaryOut] = []
        for d, ts, message_id, metrics_obj in rows:
            device_status, seconds = compute_status(d, now)

            metrics_map: dict[str, object] = metrics_obj if isinstance(metrics_obj, dict) else {}
            summary_metrics = {k: metrics_map.get(k) for k in unique_metrics}

            out.append(
                DeviceSummaryOut(
                    device_id=d.device_id,
                    display_name=d.display_name,
                    heartbeat_interval_s=d.heartbeat_interval_s,
                    offline_after_s=d.offline_after_s,
                    last_seen_at=d.last_seen_at,
                    enabled=d.enabled,
                    status=device_status,
                    seconds_since_last_seen=seconds,
                    latest_telemetry_at=ts,
                    latest_message_id=message_id,
                    metrics=summary_metrics,
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

        device_status, seconds = compute_status(d, now)
        return DeviceOut(
            device_id=d.device_id,
            display_name=d.display_name,
            heartbeat_interval_s=d.heartbeat_interval_s,
            offline_after_s=d.offline_after_s,
            last_seen_at=d.last_seen_at,
            enabled=d.enabled,
            status=device_status,
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
    from sqlalchemy import Float, String, case, cast, func

    date_trunc_unit = "minute" if bucket == "minute" else "hour"
    metric = metric.strip()
    if not METRIC_KEY_RE.fullmatch(metric):
        raise HTTPException(status_code=400, detail="metric must match ^[A-Za-z0-9_]{1,64}$")

    since = _normalize_opt_utc(since)
    until = _normalize_opt_utc(until)
    if since is not None and until is not None and since > until:
        raise HTTPException(status_code=400, detail="since must be <= until")

    with db_session() as session:
        if bucket == "hour" and settings.telemetry_rollups_enabled:
            rollup_query = session.query(
                TelemetryRollupHourly.bucket_ts.label("bucket_ts"),
                TelemetryRollupHourly.avg_value.label("value"),
            ).filter(
                TelemetryRollupHourly.device_id == device_id,
                TelemetryRollupHourly.metric_key == metric,
            )
            if since is not None:
                rollup_query = rollup_query.filter(TelemetryRollupHourly.bucket_ts >= since)
            if until is not None:
                rollup_query = rollup_query.filter(TelemetryRollupHourly.bucket_ts <= until)
            rollup_rows = rollup_query.order_by(desc(TelemetryRollupHourly.bucket_ts)).limit(limit).all()
            if rollup_rows:
                return [
                    TimeseriesPointOut(bucket_ts=r.bucket_ts, value=float(r.value))
                    for r in reversed(rollup_rows)
                    if r.value is not None
                ]

        dialect_name = session.bind.dialect.name if session.bind is not None else ""
        value_text = _json_metric_text_expr(metric, dialect_name)
        if dialect_name == "postgresql":
            # Avoid runtime errors when the JSON value isn't numeric (bad data / drift).
            text_value = cast(value_text, String)
            numeric_value = case(
                (text_value.op("~")(NUMERIC_TEXT_RE), cast(text_value, Float)),
                else_=None,
            )
        else:
            # SQLite/json_extract returns NULL when absent and tolerates casts to float.
            numeric_value = cast(value_text, Float)

        q = session.query(
            func.date_trunc(date_trunc_unit, TelemetryPoint.ts).label("bucket_ts"),
            func.avg(numeric_value).label("value"),
        ).filter(TelemetryPoint.device_id == device_id)

        # Only include points that have the metric key.
        q = q.filter(value_text.is_not(None))

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
    from sqlalchemy import Float, String, case, cast, func

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
        if not METRIC_KEY_RE.fullmatch(mm):
            raise HTTPException(status_code=400, detail=f"invalid metric key: {mm}")
        if mm in seen:
            continue
        seen.add(mm)
        unique_metrics.append(mm)
    if not unique_metrics:
        raise HTTPException(status_code=400, detail="metrics must include at least one metric key")
    if len(unique_metrics) > 10:
        raise HTTPException(status_code=400, detail="metrics must include at most 10 metric keys")

    with db_session() as session:
        dialect_name = session.bind.dialect.name if session.bind is not None else ""

        bucket_ts = func.date_trunc(date_trunc_unit, TelemetryPoint.ts).label("bucket_ts")
        cols = [bucket_ts]
        for m in unique_metrics:
            value_text = _json_metric_text_expr(m, dialect_name)
            if dialect_name == "postgresql":
                text_value = cast(value_text, String)
                numeric_value = case(
                    (text_value.op("~")(NUMERIC_TEXT_RE), cast(text_value, Float)),
                    else_=None,
                )
            else:
                numeric_value = cast(value_text, Float)

            value = func.avg(numeric_value).filter(value_text.is_not(None)).label(m)
            cols.append(value)

        if bucket == "hour" and settings.telemetry_rollups_enabled:
            bucket_q = session.query(TelemetryRollupHourly.bucket_ts).filter(
                TelemetryRollupHourly.device_id == device_id,
                TelemetryRollupHourly.metric_key.in_(unique_metrics),
            )
            if since is not None:
                bucket_q = bucket_q.filter(TelemetryRollupHourly.bucket_ts >= since)
            if until is not None:
                bucket_q = bucket_q.filter(TelemetryRollupHourly.bucket_ts <= until)

            bucket_rows = (
                bucket_q.group_by(TelemetryRollupHourly.bucket_ts)
                .order_by(desc(TelemetryRollupHourly.bucket_ts))
                .limit(limit)
                .all()
            )
            if bucket_rows:
                selected_buckets = [r.bucket_ts for r in bucket_rows]
                rollup_rows = (
                    session.query(
                        TelemetryRollupHourly.bucket_ts,
                        TelemetryRollupHourly.metric_key,
                        TelemetryRollupHourly.avg_value,
                    )
                    .filter(
                        TelemetryRollupHourly.device_id == device_id,
                        TelemetryRollupHourly.metric_key.in_(unique_metrics),
                        TelemetryRollupHourly.bucket_ts.in_(selected_buckets),
                    )
                    .all()
                )

                values_by_bucket: dict[datetime, dict[str, Optional[float]]] = {
                    b: {m: None for m in unique_metrics} for b in selected_buckets
                }
                for bucket_ts, metric_key, avg_value in rollup_rows:
                    bucket_values = values_by_bucket.get(bucket_ts)
                    if bucket_values is None:
                        continue
                    bucket_values[metric_key] = float(avg_value) if avg_value is not None else None

                ordered_buckets = sorted(selected_buckets)
                return [
                    TimeseriesMultiPointOut(bucket_ts=bucket_ts, values=values_by_bucket[bucket_ts])
                    for bucket_ts in ordered_buckets
                ]

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
