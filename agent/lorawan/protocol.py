from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import zlib
from dataclasses import dataclass
from enum import IntEnum, IntFlag


PROTOCOL_VERSION = 1
UPLINK_MAGIC = b"EW"
WAKE_MAGIC = b"WK"
MIN_UNIX_TIMESTAMP = 1_577_836_800  # 2020-01-01T00:00:00Z
MAX_UINT32 = (1 << 32) - 1

_UPLINK_BODY = struct.Struct(">2sBBIIBBBHH8s")
_UPLINK_PACKET = struct.Struct(">2sBBIIBBBHH8sI")
UPLINK_SIZE = _UPLINK_PACKET.size

_WAKE_BODY = struct.Struct(">2sBB8sIIH")
_WAKE_PACKET = struct.Struct(">2sBB8sIIH8s")
WAKE_SIZE = _WAKE_PACKET.size


class ProtocolError(ValueError):
    """Raised when a LoRaWAN application payload violates the closed protocol."""


class MessageType(IntEnum):
    TELEMETRY = 1
    HEALTH = 2
    EVENT = 3


class EquipmentState(IntEnum):
    UNKNOWN = 0
    RUNNING = 1
    STOPPED = 2
    FAULT = 3


class HealthFlag(IntFlag):
    POWER_INPUT_OUT_OF_RANGE = 1 << 0
    POWER_UNSUSTAINABLE = 1 << 1
    LOW_BATTERY = 1 << 2
    SENTINEL_TRIGGERED = 1 << 3
    CAMERA_OK = 1 << 4
    AUDIO_OK = 1 << 5
    MAINTENANCE_READY = 1 << 6
    DEGRADED = 1 << 7


_KNOWN_HEALTH_FLAGS = sum(int(flag) for flag in HealthFlag)


class WakeOperation(IntEnum):
    MAINTENANCE = 1


@dataclass(frozen=True)
class UplinkFrame:
    message_type: MessageType
    sequence: int
    timestamp: int
    equipment_state: EquipmentState
    visual_confidence_pct: int
    audio_confidence_pct: int
    battery_mv: int
    flags: HealthFlag
    model_digest: bytes
    version: int = PROTOCOL_VERSION


@dataclass(frozen=True)
class WakeFrame:
    command_token: bytes
    expires_at: int
    nonce: int
    readiness_timeout_s: int
    operation: WakeOperation = WakeOperation.MAINTENANCE
    version: int = PROTOCOL_VERSION


def _validate_uint(value: object, *, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ProtocolError(f"{name} must be an integer from 0 through {maximum}")
    return value


def _coerce_message_type(value: object) -> MessageType:
    try:
        return MessageType(value)
    except (TypeError, ValueError) as exc:
        raise ProtocolError("message_type is not defined by protocol v1") from exc


def _coerce_equipment_state(value: object) -> EquipmentState:
    try:
        return EquipmentState(value)
    except (TypeError, ValueError) as exc:
        raise ProtocolError("equipment_state is not defined by protocol v1") from exc


def _coerce_health_flags(value: object) -> HealthFlag:
    raw = _validate_uint(value, name="flags", maximum=0xFFFF)
    if raw & ~_KNOWN_HEALTH_FLAGS:
        raise ProtocolError("flags contains bits not defined by protocol v1")
    return HealthFlag(raw)


def _validate_uplink(frame: UplinkFrame) -> UplinkFrame:
    if frame.version != PROTOCOL_VERSION:
        raise ProtocolError("unsupported uplink protocol version")
    message_type = _coerce_message_type(frame.message_type)
    sequence = _validate_uint(frame.sequence, name="sequence", maximum=MAX_UINT32)
    timestamp = _validate_uint(frame.timestamp, name="timestamp", maximum=MAX_UINT32)
    if timestamp < MIN_UNIX_TIMESTAMP:
        raise ProtocolError("timestamp predates the protocol epoch floor")
    equipment_state = _coerce_equipment_state(frame.equipment_state)
    visual = _validate_uint(frame.visual_confidence_pct, name="visual_confidence_pct", maximum=100)
    audio = _validate_uint(frame.audio_confidence_pct, name="audio_confidence_pct", maximum=100)
    battery_mv = _validate_uint(frame.battery_mv, name="battery_mv", maximum=20_000)
    flags = _coerce_health_flags(frame.flags)
    if not isinstance(frame.model_digest, bytes) or len(frame.model_digest) != 8:
        raise ProtocolError("model_digest must be exactly 8 bytes")
    return UplinkFrame(
        message_type=message_type,
        sequence=sequence,
        timestamp=timestamp,
        equipment_state=equipment_state,
        visual_confidence_pct=visual,
        audio_confidence_pct=audio,
        battery_mv=battery_mv,
        flags=flags,
        model_digest=frame.model_digest,
    )


def encode_uplink(frame: UplinkFrame) -> bytes:
    """Encode the complete, fixed-width v1 satellite uplink."""

    checked = _validate_uplink(frame)
    body = _UPLINK_BODY.pack(
        UPLINK_MAGIC,
        checked.version,
        int(checked.message_type),
        checked.sequence,
        checked.timestamp,
        int(checked.equipment_state),
        checked.visual_confidence_pct,
        checked.audio_confidence_pct,
        checked.battery_mv,
        int(checked.flags),
        checked.model_digest,
    )
    checksum = zlib.crc32(body) & MAX_UINT32
    return body + struct.pack(">I", checksum)


def decode_uplink(payload: bytes) -> UplinkFrame:
    """Decode a v1 uplink, rejecting truncation, extension, unknown values, and corruption."""

    if not isinstance(payload, bytes) or len(payload) != UPLINK_SIZE:
        raise ProtocolError(f"uplink payload must be exactly {UPLINK_SIZE} bytes")
    (
        magic,
        version,
        message_type,
        sequence,
        timestamp,
        equipment_state,
        visual,
        audio,
        battery_mv,
        flags,
        model_digest,
        checksum,
    ) = _UPLINK_PACKET.unpack(payload)
    if magic != UPLINK_MAGIC:
        raise ProtocolError("invalid uplink magic")
    expected_checksum = zlib.crc32(payload[:-4]) & MAX_UINT32
    if not hmac.compare_digest(struct.pack(">I", checksum), struct.pack(">I", expected_checksum)):
        raise ProtocolError("uplink checksum mismatch")
    return _validate_uplink(
        UplinkFrame(
            version=version,
            message_type=_coerce_message_type(message_type),
            sequence=sequence,
            timestamp=timestamp,
            equipment_state=_coerce_equipment_state(equipment_state),
            visual_confidence_pct=visual,
            audio_confidence_pct=audio,
            battery_mv=battery_mv,
            flags=_coerce_health_flags(flags),
            model_digest=model_digest,
        )
    )


def canonical_message_id(dev_eui: str, payload: bytes) -> str:
    """Return a stable <=64-character idempotency key for one device frame."""

    normalized = dev_eui.strip().lower()
    if len(normalized) != 16:
        raise ProtocolError("dev_eui must contain exactly 16 hexadecimal characters")
    try:
        eui_bytes = bytes.fromhex(normalized)
    except ValueError as exc:
        raise ProtocolError("dev_eui must contain exactly 16 hexadecimal characters") from exc
    if not isinstance(payload, bytes) or len(payload) != UPLINK_SIZE:
        raise ProtocolError(f"uplink payload must be exactly {UPLINK_SIZE} bytes")
    digest = hashlib.sha256(b"edgewatch-lorawan-v1\x00" + eui_bytes + payload).digest()
    encoded = base64.b32encode(digest).decode("ascii").rstrip("=").lower()
    return f"lw1_{encoded}"


def model_digest_prefix(sha256_hex: str) -> bytes:
    """Convert a full SHA-256 model identity to the on-air 64-bit prefix."""

    normalized = sha256_hex.strip().lower()
    if len(normalized) != 64:
        raise ProtocolError("model SHA-256 must contain exactly 64 hexadecimal characters")
    try:
        digest = bytes.fromhex(normalized)
    except ValueError as exc:
        raise ProtocolError("model SHA-256 must contain exactly 64 hexadecimal characters") from exc
    return digest[:8]


def command_token(command_id: str) -> bytes:
    if not isinstance(command_id, str) or not command_id.strip() or len(command_id) > 128:
        raise ProtocolError("command_id must be a non-empty string of at most 128 characters")
    return hashlib.sha256(command_id.strip().encode("utf-8")).digest()[:8]


def _validate_wake_key(key: bytes) -> bytes:
    if not isinstance(key, bytes) or len(key) != 32:
        raise ProtocolError("wake authentication key must be exactly 32 bytes")
    return key


def encode_wake(
    *,
    command_id: str,
    expires_at: int,
    nonce: int,
    readiness_timeout_s: int,
    key: bytes,
) -> bytes:
    """Encode the sole v1 downlink operation: authenticated, expiring maintenance wake."""

    auth_key = _validate_wake_key(key)
    expiry = _validate_uint(expires_at, name="expires_at", maximum=MAX_UINT32)
    if expiry < MIN_UNIX_TIMESTAMP:
        raise ProtocolError("expires_at predates the protocol epoch floor")
    checked_nonce = _validate_uint(nonce, name="nonce", maximum=MAX_UINT32)
    timeout = _validate_uint(readiness_timeout_s, name="readiness_timeout_s", maximum=3_600)
    if timeout < 5:
        raise ProtocolError("readiness_timeout_s must be from 5 through 3600")
    body = _WAKE_BODY.pack(
        WAKE_MAGIC,
        PROTOCOL_VERSION,
        int(WakeOperation.MAINTENANCE),
        command_token(command_id),
        expiry,
        checked_nonce,
        timeout,
    )
    tag = hmac.digest(auth_key, body, "sha256")[:8]
    return body + tag


def decode_wake(
    payload: bytes,
    *,
    key: bytes,
    now: int,
    maximum_future_s: int = 86_400,
) -> WakeFrame:
    """Authenticate and decode a wake, enforcing expiry and a bounded future lifetime."""

    auth_key = _validate_wake_key(key)
    checked_now = _validate_uint(now, name="now", maximum=MAX_UINT32)
    future_limit = _validate_uint(maximum_future_s, name="maximum_future_s", maximum=86_400)
    if future_limit < 60:
        raise ProtocolError("maximum_future_s must be from 60 through 86400")
    if not isinstance(payload, bytes) or len(payload) != WAKE_SIZE:
        raise ProtocolError(f"wake payload must be exactly {WAKE_SIZE} bytes")
    magic, version, operation, token, expires_at, nonce, timeout, tag = _WAKE_PACKET.unpack(payload)
    if magic != WAKE_MAGIC:
        raise ProtocolError("invalid wake magic")
    if version != PROTOCOL_VERSION:
        raise ProtocolError("unsupported wake protocol version")
    try:
        parsed_operation = WakeOperation(operation)
    except ValueError as exc:
        raise ProtocolError("wake operation is not defined by protocol v1") from exc
    expected_tag = hmac.digest(auth_key, payload[:-8], "sha256")[:8]
    if not hmac.compare_digest(tag, expected_tag):
        raise ProtocolError("wake authentication failed")
    if expires_at < checked_now:
        raise ProtocolError("wake command has expired")
    if expires_at - checked_now > future_limit:
        raise ProtocolError("wake expiry exceeds the allowed future lifetime")
    if not 5 <= timeout <= 3_600:
        raise ProtocolError("readiness_timeout_s must be from 5 through 3600")
    return WakeFrame(
        command_token=token,
        expires_at=expires_at,
        nonce=nonce,
        readiness_timeout_s=timeout,
        operation=parsed_operation,
        version=version,
    )
