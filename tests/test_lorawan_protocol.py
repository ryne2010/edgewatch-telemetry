from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from agent.lorawan.protocol import (
    UPLINK_SIZE,
    WAKE_SIZE,
    EquipmentState,
    HealthFlag,
    MessageType,
    ProtocolError,
    UplinkFrame,
    WakeOperation,
    canonical_message_id,
    decode_uplink,
    decode_wake,
    encode_uplink,
    encode_wake,
    model_digest_prefix,
)


NOW = 1_780_000_000


def _frame(**overrides: object) -> UplinkFrame:
    values: dict[str, object] = {
        "message_type": MessageType.EVENT,
        "sequence": 42,
        "timestamp": NOW,
        "equipment_state": EquipmentState.FAULT,
        "visual_confidence_pct": 96,
        "audio_confidence_pct": 83,
        "battery_mv": 12_650,
        "flags": HealthFlag.SENTINEL_TRIGGERED | HealthFlag.CAMERA_OK | HealthFlag.AUDIO_OK,
        "model_digest": bytes.fromhex("0123456789abcdef"),
    }
    values.update(overrides)
    return UplinkFrame(**values)  # type: ignore[arg-type]


def test_uplink_v1_is_fixed_width_and_round_trips_exactly() -> None:
    frame = _frame()
    payload = encode_uplink(frame)

    assert len(payload) == UPLINK_SIZE == 31
    assert decode_uplink(payload) == frame
    assert set(MessageType) == {MessageType.TELEMETRY, MessageType.HEALTH, MessageType.EVENT}
    assert set(EquipmentState) == {
        EquipmentState.UNKNOWN,
        EquipmentState.RUNNING,
        EquipmentState.STOPPED,
        EquipmentState.FAULT,
    }


def test_uplink_rejects_corruption_extensions_and_unknown_values() -> None:
    payload = bytearray(encode_uplink(_frame()))
    payload[10] ^= 0x01

    with pytest.raises(ProtocolError, match="checksum"):
        decode_uplink(bytes(payload))
    with pytest.raises(ProtocolError, match="exactly"):
        decode_uplink(encode_uplink(_frame()) + b"extra")
    with pytest.raises(ProtocolError, match="message_type"):
        encode_uplink(_frame(message_type=cast(MessageType, 99)))
    with pytest.raises(ProtocolError, match="flags"):
        encode_uplink(_frame(flags=cast(HealthFlag, 1 << 15)))
    with pytest.raises(ProtocolError, match="visual_confidence"):
        encode_uplink(_frame(visual_confidence_pct=101))


def test_message_identity_is_deterministic_bounded_and_device_scoped() -> None:
    payload = encode_uplink(_frame())
    first = canonical_message_id("0102030405060708", payload)

    assert first == canonical_message_id("0102030405060708", payload)
    assert first != canonical_message_id("0102030405060709", payload)
    assert first != canonical_message_id("0102030405060708", encode_uplink(replace(_frame(), sequence=43)))
    assert first.startswith("lw1_")
    assert len(first) == 56


def test_model_digest_uses_a_strict_sha256_prefix() -> None:
    digest = "0123456789abcdef" + "00" * 24
    assert model_digest_prefix(digest) == bytes.fromhex("0123456789abcdef")
    with pytest.raises(ProtocolError, match="64 hexadecimal"):
        model_digest_prefix("not-a-digest")


def test_wake_is_authenticated_expiring_and_the_only_downlink_operation() -> None:
    key = bytes(range(32))
    payload = encode_wake(
        command_id="cmd-123",
        expires_at=NOW + 600,
        nonce=1234,
        readiness_timeout_s=300,
        key=key,
    )

    assert len(payload) == WAKE_SIZE == 30
    decoded = decode_wake(payload, key=key, now=NOW)
    assert decoded.operation is WakeOperation.MAINTENANCE
    assert decoded.nonce == 1234
    assert set(WakeOperation) == {WakeOperation.MAINTENANCE}

    tampered = bytearray(payload)
    tampered[12] ^= 0x01
    with pytest.raises(ProtocolError, match="authentication"):
        decode_wake(bytes(tampered), key=key, now=NOW)
    with pytest.raises(ProtocolError, match="expired"):
        decode_wake(payload, key=key, now=NOW + 601)
    with pytest.raises(ProtocolError, match="future lifetime"):
        decode_wake(payload, key=key, now=NOW - 86_000, maximum_future_s=60)
