from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..models import (
    Device,
    DriftEvent,
    IngestionBatch,
    QuarantinedTelemetry,
    TelemetryIngestDedupe,
    TelemetryPoint,
)
from .ingest_pipeline import CandidatePoint, QuarantinedPoint, candidate_rows
from .monitor import (
    ensure_battery_alerts,
    ensure_drip_oil_level_alerts,
    ensure_oil_level_alerts,
    ensure_oil_life_alerts,
    ensure_oil_pressure_alerts,
    ensure_signal_alerts,
    ensure_water_pressure_alerts,
)


def _dialect_insert(
    session: Session,
    model: type[TelemetryPoint] | type[TelemetryIngestDedupe],
):
    dialect = (session.bind.dialect.name if session.bind is not None else "").strip().lower()
    if dialect == "sqlite":
        return sqlite_insert(model)
    return pg_insert(model)


def persist_points_for_batch(
    session: Session,
    *,
    batch_id: str,
    device_id: str,
    points: Sequence[CandidatePoint],
) -> tuple[int, int, datetime | None]:
    if not points:
        return 0, 0, None

    rows = candidate_rows(device_id=device_id, batch_id=batch_id, points=points)

    point_by_message_id: dict[str, CandidatePoint] = {}
    for point in points:
        if point.message_id not in point_by_message_id:
            point_by_message_id[point.message_id] = point

    unique_points = list(point_by_message_id.values())
    unique_rows = candidate_rows(device_id=device_id, batch_id=batch_id, points=unique_points)
    dedupe_rows = [
        {
            "device_id": device_id,
            "message_id": row["message_id"],
            "point_ts": row["ts"],
        }
        for row in unique_rows
    ]

    dedupe_stmt = (
        _dialect_insert(session, TelemetryIngestDedupe)
        .values(dedupe_rows)
        .on_conflict_do_nothing(index_elements=["device_id", "message_id"])
        .returning(TelemetryIngestDedupe.message_id)
    )

    inserted_message_ids = list(session.execute(dedupe_stmt).scalars().all())
    accepted_message_ids = set(inserted_message_ids)

    telemetry_rows = [row for row in unique_rows if row["message_id"] in accepted_message_ids]
    if telemetry_rows:
        telemetry_stmt = _dialect_insert(session, TelemetryPoint).values(telemetry_rows)
        session.execute(telemetry_stmt)

    accepted = len(inserted_message_ids)
    duplicates = len(rows) - accepted

    newest_ts: datetime | None = None

    for message_id in inserted_message_ids:
        point = point_by_message_id.get(message_id)
        if point is None:
            continue

        if newest_ts is None or point.ts > newest_ts:
            newest_ts = point.ts

        water_pressure = point.metrics.get("water_pressure_psi")
        if isinstance(water_pressure, (int, float)) and not isinstance(water_pressure, bool):
            ensure_water_pressure_alerts(session, device_id, float(water_pressure), point.ts)

        oil_pressure = point.metrics.get("oil_pressure_psi")
        if isinstance(oil_pressure, (int, float)) and not isinstance(oil_pressure, bool):
            ensure_oil_pressure_alerts(session, device_id, float(oil_pressure), point.ts)

        oil_level = point.metrics.get("oil_level_pct")
        if isinstance(oil_level, (int, float)) and not isinstance(oil_level, bool):
            ensure_oil_level_alerts(session, device_id, float(oil_level), point.ts)

        drip_oil_level = point.metrics.get("drip_oil_level_pct")
        if isinstance(drip_oil_level, (int, float)) and not isinstance(drip_oil_level, bool):
            ensure_drip_oil_level_alerts(session, device_id, float(drip_oil_level), point.ts)

        oil_life = point.metrics.get("oil_life_pct")
        if isinstance(oil_life, (int, float)) and not isinstance(oil_life, bool):
            ensure_oil_life_alerts(session, device_id, float(oil_life), point.ts)

        battery_v = point.metrics.get("battery_v")
        if isinstance(battery_v, (int, float)) and not isinstance(battery_v, bool):
            ensure_battery_alerts(session, device_id, float(battery_v), point.ts)

        signal_rssi = point.metrics.get("signal_rssi_dbm")
        if isinstance(signal_rssi, (int, float)) and not isinstance(signal_rssi, bool):
            ensure_signal_alerts(session, device_id, float(signal_rssi), point.ts)

    if newest_ts is not None:
        device = session.query(Device).filter(Device.device_id == device_id).one_or_none()
        if device is not None:
            last_seen_at = device.last_seen_at
            if last_seen_at is not None and last_seen_at.tzinfo is None:
                last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
            if last_seen_at is None or newest_ts > last_seen_at:
                device.last_seen_at = newest_ts

    return accepted, duplicates, newest_ts


def update_ingestion_batch(
    session: Session,
    *,
    batch_id: str,
    points_accepted: int,
    duplicates: int,
    processing_status: str,
) -> None:
    batch = session.query(IngestionBatch).filter(IngestionBatch.id == batch_id).one_or_none()
    if batch is None:
        return
    batch.points_accepted = points_accepted
    batch.duplicates = duplicates
    batch.processing_status = processing_status


def record_drift_events(
    session: Session,
    *,
    batch_id: str,
    device_id: str,
    unknown_metric_keys: Sequence[str],
    type_mismatch_keys: Sequence[str],
    type_mismatch_count: int,
    unknown_keys_mode: str,
    type_mismatch_mode: str,
) -> None:
    if unknown_metric_keys and unknown_keys_mode == "flag":
        session.add(
            DriftEvent(
                batch_id=batch_id,
                device_id=device_id,
                event_type="unknown_keys",
                action="flagged",
                details={
                    "keys": list(unknown_metric_keys),
                    "count": len(unknown_metric_keys),
                },
            )
        )

    if type_mismatch_keys:
        if type_mismatch_mode == "reject":
            action = "rejected"
        elif type_mismatch_mode == "quarantine":
            action = "quarantined"
        else:
            action = "flagged"

        session.add(
            DriftEvent(
                batch_id=batch_id,
                device_id=device_id,
                event_type="type_mismatch",
                action=action,
                details={
                    "keys": list(type_mismatch_keys),
                    "count": int(type_mismatch_count),
                },
            )
        )


def record_quarantined_points(
    session: Session,
    *,
    batch_id: str,
    device_id: str,
    points: Sequence[QuarantinedPoint],
) -> None:
    for point in points:
        session.add(
            QuarantinedTelemetry(
                batch_id=batch_id,
                device_id=device_id,
                message_id=point.message_id,
                ts=point.ts,
                metrics=dict(point.metrics),
                errors=list(point.errors),
            )
        )
