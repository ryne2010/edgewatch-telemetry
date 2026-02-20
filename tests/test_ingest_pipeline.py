from __future__ import annotations

from datetime import datetime, timezone

from api.app.contracts import load_telemetry_contract
from api.app.services.ingest_pipeline import (
    CandidatePoint,
    build_pubsub_batch_payload,
    parse_ingest_source,
    parse_pubsub_batch_payload,
    prepare_points,
)


def test_prepare_points_reject_mode_keeps_drift_summary_deterministic() -> None:
    contract = load_telemetry_contract("v1")

    points = [
        CandidatePoint(
            message_id="m-1",
            ts=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            metrics={"water_pressure_psi": 40.0, "new_metric": 1},
        ),
        CandidatePoint(
            message_id="m-2",
            ts=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
            metrics={"water_pressure_psi": "bad"},
        ),
    ]

    prepared = prepare_points(
        points=points,
        contract=contract,
        unknown_keys_mode="flag",
        type_mismatch_mode="reject",
    )

    assert [p.message_id for p in prepared.accepted_points] == ["m-1"]
    assert prepared.quarantined_points == []
    assert prepared.unknown_metric_keys == ["new_metric"]
    assert prepared.type_mismatch_keys == ["water_pressure_psi"]
    assert prepared.type_mismatch_count == 1
    assert len(prepared.reject_errors) == 1

    assert prepared.drift_summary == {
        "unknown_keys": ["new_metric"],
        "unknown_key_count": 1,
        "unknown_keys_mode": "flag",
        "type_mismatch_keys": ["water_pressure_psi"],
        "type_mismatch_count": 1,
        "type_mismatch_mode": "reject",
        "points_quarantined": 0,
    }


def test_prepare_points_quarantine_mode_moves_bad_points() -> None:
    contract = load_telemetry_contract("v1")

    points = [
        CandidatePoint(
            message_id="m-1",
            ts=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            metrics={"water_pressure_psi": "bad"},
        )
    ]

    prepared = prepare_points(
        points=points,
        contract=contract,
        unknown_keys_mode="allow",
        type_mismatch_mode="quarantine",
    )

    assert prepared.accepted_points == []
    assert len(prepared.quarantined_points) == 1
    assert prepared.quarantined_points[0].message_id == "m-1"
    assert "water_pressure_psi" in prepared.quarantined_points[0].errors[0]
    assert prepared.reject_errors == []


def test_pubsub_batch_payload_round_trip() -> None:
    point = CandidatePoint(
        message_id="m-1",
        ts=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        metrics={"water_pressure_psi": 42.5},
    )
    payload = build_pubsub_batch_payload(
        batch_id="batch-1",
        device_id="dev-1",
        source="replay",
        points=[point],
    )

    parsed = parse_pubsub_batch_payload(payload)
    assert parsed.batch_id == "batch-1"
    assert parsed.device_id == "dev-1"
    assert parsed.source == "replay"
    assert len(parsed.points) == 1
    assert parsed.points[0].message_id == "m-1"


def test_parse_ingest_source_defaults_to_device_for_unknown_values() -> None:
    assert parse_ingest_source("replay") == "replay"
    assert parse_ingest_source("unknown") == "device"
    assert parse_ingest_source(None) == "device"
