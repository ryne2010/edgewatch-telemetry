from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..models import Device, DriftEvent, IngestionBatch, QuarantinedTelemetry, TelemetryPoint
from .ingest_pipeline import CandidatePoint, QuarantinedPoint, candidate_rows
from .monitor import ensure_water_pressure_alerts


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

    stmt = (
        insert(TelemetryPoint)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["device_id", "message_id"])
        .returning(TelemetryPoint.message_id)
    )

    inserted_message_ids = list(session.execute(stmt).scalars().all())
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

    if newest_ts is not None:
        device = session.query(Device).filter(Device.device_id == device_id).one_or_none()
        if device is not None and (device.last_seen_at is None or newest_ts > device.last_seen_at):
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
