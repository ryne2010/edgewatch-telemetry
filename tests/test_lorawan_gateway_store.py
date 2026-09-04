from __future__ import annotations

import base64
import json
from dataclasses import replace
from pathlib import Path
import pytest

from agent.lorawan.chirpstack import ChirpStackUplink, parse_uplink_event
from agent.lorawan.config import DeviceIdentity, DeviceRegistry
from agent.lorawan.maintenance import MaintenanceWakeCoordinator
from agent.lorawan.protocol import (
    EquipmentState,
    HealthFlag,
    MessageType,
    UplinkFrame,
    command_token,
    encode_uplink,
)
from agent.lorawan.store import GatewayStore, StoreConflictError


NOW = 1_780_000_000
DEV_EUI = "0102030405060708"


def _identity() -> DeviceIdentity:
    return DeviceIdentity(
        device_id="camera-1",
        application_id="app-1",
        dev_eui=DEV_EUI,
        join_eui="1122334455667788",
        app_key="11" * 16,
        wake_key="22" * 32,
    )


def _uplink(
    *,
    sequence: int = 1,
    flags: HealthFlag = HealthFlag.CAMERA_OK,
    model_digest: bytes = bytes.fromhex("0011223344556677"),
) -> ChirpStackUplink:
    frame = encode_uplink(
        UplinkFrame(
            message_type=MessageType.EVENT,
            sequence=sequence,
            timestamp=NOW + sequence,
            equipment_state=EquipmentState.FAULT,
            visual_confidence_pct=98,
            audio_confidence_pct=91,
            battery_mv=12_300,
            flags=flags,
            model_digest=model_digest,
        )
    )
    event = {
        "deviceInfo": {"applicationId": "app-1", "devEui": DEV_EUI},
        "fPort": 10,
        "data": base64.b64encode(frame).decode("ascii"),
    }
    return parse_uplink_event(
        f"application/app-1/device/{DEV_EUI}/event/up",
        json.dumps(event),
        DeviceRegistry([_identity()]),
    )


def test_uplink_dedupe_and_outbox_delivery_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "gateway.sqlite"
    store = GatewayStore(path)
    uplink = _uplink()

    assert store.enqueue_uplink(uplink, received_at=NOW)
    assert not store.enqueue_uplink(uplink, received_at=NOW + 1)
    assert path.stat().st_mode & 0o777 == 0o600

    [claimed] = store.claim_outbox("worker-a", now=NOW, lease_s=10)
    assert claimed.message_id == uplink.message_id
    assert claimed.device_id == "camera-1"
    assert claimed.payload == uplink.canonical_point
    assert claimed.attempts == 1
    assert GatewayStore(path).claim_outbox("worker-b", now=NOW + 9) == ()
    [reclaimed] = GatewayStore(path).claim_outbox("worker-b", now=NOW + 10, lease_s=10)
    assert reclaimed.attempts == 2
    assert not store.mark_outbox_delivered(uplink.message_id, "worker-a", now=NOW + 11)
    assert store.mark_outbox_delivered(uplink.message_id, "worker-b", now=NOW + 11)
    assert GatewayStore(path).outbox_counts() == {"pending": 0, "sending": 0, "delivered": 1}


def test_alert_trigger_lease_and_completion_are_durable(tmp_path: Path) -> None:
    path = tmp_path / "gateway.sqlite"
    store = GatewayStore(path)
    uplink = _uplink()
    assert store.enqueue_uplink(uplink, received_at=NOW)

    [claimed] = store.claim_alert_triggers("worker-a", now=NOW, lease_s=10)
    assert claimed.message_id == uplink.message_id
    assert claimed.attempts == 1
    assert GatewayStore(path).claim_alert_triggers("worker-b", now=NOW + 9) == ()

    [reclaimed] = GatewayStore(path).claim_alert_triggers("worker-b", now=NOW + 10)
    assert reclaimed.message_id == uplink.message_id
    assert reclaimed.attempts == 2
    assert not store.mark_alert_trigger_completed(uplink.message_id, "worker-a", now=NOW + 11)
    assert store.mark_alert_trigger_completed(uplink.message_id, "worker-b", now=NOW + 11)
    assert GatewayStore(path).alert_trigger_counts() == {
        "pending": 0,
        "processing": 0,
        "completed": 1,
    }
    assert GatewayStore(path).claim_alert_triggers("worker-c", now=NOW + 100) == ()


def test_outbox_retry_is_durable_and_bounded_by_availability(tmp_path: Path) -> None:
    store = GatewayStore(tmp_path / "gateway.sqlite")
    uplink = _uplink()
    store.enqueue_uplink(uplink, received_at=NOW)
    [item] = store.claim_outbox("worker", now=NOW)

    assert store.retry_outbox(
        item.message_id,
        "worker",
        failure_code="telegram_unavailable",
        retry_after_s=30,
        now=NOW,
    )
    assert store.claim_outbox("worker", now=NOW + 29) == ()
    [retried] = GatewayStore(store.path).claim_outbox("worker", now=NOW + 30)
    assert retried.attempts == 2
    with pytest.raises(ValueError, match="safe identifier"):
        store.retry_outbox(
            retried.message_id,
            "worker",
            failure_code="secret could appear here",
            retry_after_s=1,
            now=NOW + 31,
        )


def test_stable_message_id_rejects_conflicting_immutable_uplink(tmp_path: Path) -> None:
    store = GatewayStore(tmp_path / "gateway.sqlite")
    uplink = _uplink()
    store.enqueue_uplink(uplink, received_at=NOW)
    conflicting = replace(uplink, device_id="different-device")

    with pytest.raises(StoreConflictError, match="different immutable"):
        store.enqueue_uplink(conflicting, received_at=NOW + 1)


def test_class_a_wake_waits_for_uplink_then_for_bounded_readiness(tmp_path: Path) -> None:
    registry = DeviceRegistry([_identity()])
    store = GatewayStore(tmp_path / "gateway.sqlite")
    published: list[tuple[str, bytes, int]] = []

    def _publish(identity: DeviceIdentity, payload: bytes, now: int) -> bool:
        published.append((identity.device_id, payload, now))
        return True

    coordinator = MaintenanceWakeCoordinator(registry, store, _publish)
    wake = coordinator.request_wake(
        "cmd-1",
        "camera-1",
        expires_at=NOW + 600,
        readiness_timeout_s=120,
        now=NOW,
        nonce=123,
    )

    assert wake.state == "waiting_uplink"
    assert published == []
    result = coordinator.handle_uplink(_uplink(), now=NOW + 10)
    assert result.published_command_id == "cmd-1"
    assert len(published) == 1
    waiting = store.get_wake("cmd-1")
    assert waiting is not None and waiting.state == "waiting_ready"
    assert waiting.ready_deadline == NOW + 130

    duplicate = coordinator.handle_uplink(_uplink(), now=NOW + 11)
    assert duplicate.published_command_id is None
    assert len(published) == 1

    ready = coordinator.handle_uplink(
        _uplink(
            sequence=2,
            flags=HealthFlag.MAINTENANCE_READY,
            model_digest=command_token("cmd-1"),
        ),
        now=NOW + 20,
    )
    assert ready.ready_command_ids == ("cmd-1",)
    completed = store.get_wake("cmd-1")
    assert completed is not None and completed.state == "ready"
    assert completed.ready_at == NOW + 20


def test_stale_readiness_receipt_cannot_unlock_a_different_wake(tmp_path: Path) -> None:
    registry = DeviceRegistry([_identity()])
    store = GatewayStore(tmp_path / "gateway.sqlite")
    coordinator = MaintenanceWakeCoordinator(registry, store, lambda *_args: True)
    coordinator.request_wake("cmd-new", "camera-1", expires_at=NOW + 600, now=NOW, nonce=123)
    assert coordinator.handle_uplink(_uplink(), now=NOW + 1).published_command_id == "cmd-new"

    stale = coordinator.handle_uplink(
        _uplink(
            sequence=2,
            flags=HealthFlag.MAINTENANCE_READY,
            model_digest=command_token("cmd-old"),
        ),
        now=NOW + 2,
    )

    assert stale.ready_command_ids == ()
    wake = store.get_wake("cmd-new")
    assert wake is not None and wake.state == "waiting_ready"


def test_wake_publish_retry_and_timeout_are_durable(tmp_path: Path) -> None:
    registry = DeviceRegistry([_identity()])
    path = tmp_path / "gateway.sqlite"
    store = GatewayStore(path)
    results = iter([False, True])
    coordinator = MaintenanceWakeCoordinator(
        registry,
        store,
        lambda _identity, _payload, _now: next(results),
        publish_retry_s=5,
    )
    coordinator.request_wake(
        "cmd-retry",
        "camera-1",
        expires_at=NOW + 600,
        readiness_timeout_s=5,
        now=NOW,
        nonce=456,
    )

    first = coordinator.handle_uplink(_uplink(), now=NOW + 1)
    assert first.publish_deferred
    assert GatewayStore(path).get_wake("cmd-retry").state == "waiting_uplink"  # type: ignore[union-attr]
    assert coordinator.handle_uplink(_uplink(), now=NOW + 5).published_command_id is None
    assert coordinator.handle_uplink(_uplink(), now=NOW + 6).published_command_id == "cmd-retry"
    assert GatewayStore(path).expire_wakes(now=NOW + 12) == 1
    timed_out = GatewayStore(path).get_wake("cmd-retry")
    assert timed_out is not None and timed_out.state == "timed_out"


def test_only_one_active_wake_per_device_and_intent_replay_is_stable(tmp_path: Path) -> None:
    registry = DeviceRegistry([_identity()])
    store = GatewayStore(tmp_path / "gateway.sqlite")
    coordinator = MaintenanceWakeCoordinator(registry, store, lambda *_args: True)
    first = coordinator.request_wake("cmd-1", "camera-1", expires_at=NOW + 600, now=NOW, nonce=1)
    replay = coordinator.request_wake("cmd-1", "camera-1", expires_at=NOW + 600, now=NOW + 1, nonce=999)
    assert replay.payload == first.payload
    assert replay.nonce == 1
    late_replay = coordinator.request_wake(
        "cmd-1",
        "camera-1",
        expires_at=NOW + 600,
        now=NOW + 700,
        nonce=999,
    )
    assert late_replay.payload == first.payload

    with pytest.raises(StoreConflictError, match="active maintenance wake"):
        coordinator.request_wake("cmd-2", "camera-1", expires_at=NOW + 600, now=NOW, nonce=2)
