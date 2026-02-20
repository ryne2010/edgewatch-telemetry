from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Sequence

from ..contracts import TelemetryContract, TypeMismatch


UnknownKeysMode = Literal["allow", "flag"]
TypeMismatchMode = Literal["reject", "quarantine"]
_ALLOWED_SOURCES = {"device", "replay", "pubsub", "backfill"}


@dataclass(frozen=True)
class CandidatePoint:
    message_id: str
    ts: datetime
    metrics: dict[str, Any]


@dataclass(frozen=True)
class QuarantinedPoint:
    message_id: str
    ts: datetime
    metrics: dict[str, Any]
    errors: list[str]


@dataclass(frozen=True)
class PreparedIngest:
    accepted_points: list[CandidatePoint]
    quarantined_points: list[QuarantinedPoint]
    unknown_metric_keys: list[str]
    type_mismatch_keys: list[str]
    type_mismatch_count: int
    reject_errors: list[str]
    drift_summary: dict[str, Any]
    client_ts_min: datetime | None
    client_ts_max: datetime | None


@dataclass(frozen=True)
class ParsedPubSubBatch:
    batch_id: str
    device_id: str
    source: str
    points: list[CandidatePoint]


def normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_ingest_source(raw: str | None) -> str:
    source = (raw or "").strip().lower()
    if source in _ALLOWED_SOURCES:
        return source
    return "device"


def format_type_mismatch(mismatch: TypeMismatch) -> str:
    return f"metric '{mismatch.key}' expected type '{mismatch.expected}' but got '{mismatch.actual}'"


def prepare_points(
    *,
    points: Sequence[CandidatePoint],
    contract: TelemetryContract,
    unknown_keys_mode: UnknownKeysMode,
    type_mismatch_mode: TypeMismatchMode,
) -> PreparedIngest:
    accepted_points: list[CandidatePoint] = []
    quarantined_points: list[QuarantinedPoint] = []

    unknown_keys_union: set[str] = set()
    mismatch_keys_union: set[str] = set()
    reject_errors: list[str] = []

    client_ts_min: datetime | None = None
    client_ts_max: datetime | None = None
    type_mismatch_count = 0

    for point in points:
        ts = normalize_utc(point.ts)
        if client_ts_min is None or ts < client_ts_min:
            client_ts_min = ts
        if client_ts_max is None or ts > client_ts_max:
            client_ts_max = ts

        unknown_keys, mismatches = contract.validate_metrics_detailed(point.metrics)
        unknown_keys_union |= unknown_keys
        for mismatch in mismatches:
            mismatch_keys_union.add(mismatch.key)

        type_mismatch_count += len(mismatches)

        if mismatches:
            mismatch_errors = [format_type_mismatch(m) for m in mismatches]
            if type_mismatch_mode == "reject":
                reject_errors.extend(mismatch_errors)
                continue
            quarantined_points.append(
                QuarantinedPoint(
                    message_id=point.message_id,
                    ts=ts,
                    metrics=dict(point.metrics),
                    errors=mismatch_errors,
                )
            )
            continue

        accepted_points.append(
            CandidatePoint(message_id=point.message_id, ts=ts, metrics=dict(point.metrics))
        )

    unknown_metric_keys = sorted(unknown_keys_union)
    type_mismatch_keys = sorted(mismatch_keys_union)

    drift_summary = {
        "unknown_keys": unknown_metric_keys,
        "unknown_key_count": len(unknown_metric_keys),
        "unknown_keys_mode": unknown_keys_mode,
        "type_mismatch_keys": type_mismatch_keys,
        "type_mismatch_count": type_mismatch_count,
        "type_mismatch_mode": type_mismatch_mode,
        "points_quarantined": len(quarantined_points),
    }

    return PreparedIngest(
        accepted_points=accepted_points,
        quarantined_points=quarantined_points,
        unknown_metric_keys=unknown_metric_keys,
        type_mismatch_keys=type_mismatch_keys,
        type_mismatch_count=type_mismatch_count,
        reject_errors=reject_errors,
        drift_summary=drift_summary,
        client_ts_min=client_ts_min,
        client_ts_max=client_ts_max,
    )


def candidate_rows(
    *, device_id: str, batch_id: str, points: Sequence[CandidatePoint]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for point in points:
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "message_id": point.message_id,
                "device_id": device_id,
                "batch_id": batch_id,
                "ts": normalize_utc(point.ts),
                "metrics": dict(point.metrics),
            }
        )
    return rows


def build_pubsub_batch_payload(
    *,
    batch_id: str,
    device_id: str,
    source: str,
    points: Sequence[CandidatePoint],
) -> dict[str, Any]:
    return {
        "batch_id": batch_id,
        "device_id": device_id,
        "source": parse_ingest_source(source),
        "points": [
            {
                "message_id": point.message_id,
                "ts": normalize_utc(point.ts).isoformat(),
                "metrics": dict(point.metrics),
            }
            for point in points
        ],
    }


def _parse_dt(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    return normalize_utc(dt)


def parse_pubsub_batch_payload(payload: Mapping[str, Any]) -> ParsedPubSubBatch:
    batch_id = str(payload.get("batch_id") or "").strip()
    device_id = str(payload.get("device_id") or "").strip()
    source = parse_ingest_source(str(payload.get("source") or "pubsub"))

    if not batch_id:
        raise ValueError("pubsub payload missing batch_id")
    if not device_id:
        raise ValueError("pubsub payload missing device_id")

    points_raw = payload.get("points")
    if not isinstance(points_raw, list) or not points_raw:
        raise ValueError("pubsub payload points must be a non-empty list")

    points: list[CandidatePoint] = []
    for item in points_raw:
        if not isinstance(item, Mapping):
            raise ValueError("pubsub point must be an object")
        message_id = str(item.get("message_id") or "").strip()
        ts_raw = item.get("ts")
        metrics_raw = item.get("metrics")

        if not message_id:
            raise ValueError("pubsub point missing message_id")
        if not isinstance(ts_raw, str) or not ts_raw.strip():
            raise ValueError("pubsub point missing ts")
        if not isinstance(metrics_raw, Mapping):
            raise ValueError("pubsub point metrics must be an object")

        points.append(
            CandidatePoint(
                message_id=message_id,
                ts=_parse_dt(ts_raw),
                metrics=dict(metrics_raw),
            )
        )

    return ParsedPubSubBatch(batch_id=batch_id, device_id=device_id, source=source, points=points)
