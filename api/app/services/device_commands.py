from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Device, DeviceControlCommand


PENDING = "pending"
SUPERSEDED = "superseded"
EXPIRED = "expired"
ACKNOWLEDGED = "acknowledged"
DEFAULT_SHUTDOWN_GRACE_S = 30


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_mode(value: object) -> str:
    mode = str(value or "active").strip().lower()
    if mode in {"active", "sleep", "disabled"}:
        return mode
    return "active"


def _normalize_opt_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_reason(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _safe_shutdown_grace_s(value: object) -> int:
    if isinstance(value, bool):
        parsed = int(value)
    elif isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        parsed = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return DEFAULT_SHUTDOWN_GRACE_S
        try:
            parsed = int(text)
        except ValueError:
            return DEFAULT_SHUTDOWN_GRACE_S
    else:
        return DEFAULT_SHUTDOWN_GRACE_S
    if parsed < 1:
        return 1
    if parsed > 3600:
        return 3600
    return parsed


def command_payload_from_device(device: Device) -> dict[str, Any]:
    muted_until = _normalize_opt_utc(getattr(device, "alerts_muted_until", None))
    return {
        "operation_mode": _normalize_mode(getattr(device, "operation_mode", "active")),
        "sleep_poll_interval_s": int(
            getattr(device, "sleep_poll_interval_s", 7 * 24 * 3600) or (7 * 24 * 3600)
        ),
        "shutdown_requested": False,
        "shutdown_grace_s": DEFAULT_SHUTDOWN_GRACE_S,
        "alerts_muted_until": muted_until.isoformat() if muted_until is not None else None,
        "alerts_muted_reason": _normalize_reason(getattr(device, "alerts_muted_reason", None)),
    }


def expire_commands(session: Session, *, device_id: str | None = None, now: datetime | None = None) -> int:
    ts = _normalize_opt_utc(now) or utcnow()
    q = session.query(DeviceControlCommand).filter(
        DeviceControlCommand.status == PENDING,
        DeviceControlCommand.expires_at <= ts,
    )
    if device_id:
        q = q.filter(DeviceControlCommand.device_id == device_id)
    rows = q.all()
    for row in rows:
        row.status = EXPIRED
    return len(rows)


def supersede_pending_commands(
    session: Session, *, device_id: str, now: datetime | None = None, exclude_id: str | None = None
) -> int:
    ts = _normalize_opt_utc(now) or utcnow()
    q = session.query(DeviceControlCommand).filter(
        DeviceControlCommand.device_id == device_id,
        DeviceControlCommand.status == PENDING,
    )
    if exclude_id:
        q = q.filter(DeviceControlCommand.id != exclude_id)
    rows = q.all()
    for row in rows:
        row.status = SUPERSEDED
        row.superseded_at = ts
    return len(rows)


def enqueue_device_control_command(
    session: Session,
    *,
    device: Device,
    ttl_s: int,
    payload_overrides: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> DeviceControlCommand:
    ts = _normalize_opt_utc(now) or utcnow()
    expire_commands(session, device_id=device.device_id, now=ts)
    supersede_pending_commands(session, device_id=device.device_id, now=ts)
    expires_at = ts + timedelta(seconds=max(1, int(ttl_s)))

    payload = command_payload_from_device(device)
    if payload_overrides:
        payload.update(dict(payload_overrides))
    command = DeviceControlCommand(
        device_id=device.device_id,
        command_payload=payload,
        status=PENDING,
        issued_at=ts,
        expires_at=expires_at,
    )
    session.add(command)
    session.flush()
    return command


def enqueue_device_shutdown_command(
    session: Session,
    *,
    device: Device,
    reason: str,
    shutdown_grace_s: int,
    ttl_s: int,
    now: datetime | None = None,
) -> DeviceControlCommand:
    normalized_reason = _normalize_reason(reason)
    if normalized_reason is None:
        raise ValueError("shutdown reason is required")

    # Hybrid disable semantics: command latches logical disable and may optionally
    # trigger remote shutdown on nodes configured to allow it.
    return enqueue_device_control_command(
        session,
        device=device,
        ttl_s=ttl_s,
        payload_overrides={
            "operation_mode": "disabled",
            "shutdown_requested": True,
            "shutdown_grace_s": _safe_shutdown_grace_s(shutdown_grace_s),
            "shutdown_reason": normalized_reason,
        },
        now=now,
    )


def get_pending_device_command(
    session: Session,
    *,
    device_id: str,
    now: datetime | None = None,
) -> DeviceControlCommand | None:
    ts = _normalize_opt_utc(now) or utcnow()
    expire_commands(session, device_id=device_id, now=ts)
    return (
        session.query(DeviceControlCommand)
        .filter(
            DeviceControlCommand.device_id == device_id,
            DeviceControlCommand.status == PENDING,
            DeviceControlCommand.expires_at > ts,
        )
        .order_by(DeviceControlCommand.issued_at.desc(), DeviceControlCommand.id.desc())
        .first()
    )


def ack_device_command(
    session: Session,
    *,
    device_id: str,
    command_id: str,
    now: datetime | None = None,
) -> DeviceControlCommand | None:
    ts = _normalize_opt_utc(now) or utcnow()
    row = (
        session.query(DeviceControlCommand)
        .filter(
            DeviceControlCommand.id == command_id,
            DeviceControlCommand.device_id == device_id,
        )
        .one_or_none()
    )
    if row is None:
        return None

    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if row.status == PENDING and expires_at <= ts:
        row.status = EXPIRED

    if row.status == PENDING:
        row.status = ACKNOWLEDGED
        row.acknowledged_at = row.acknowledged_at or ts
    elif row.status == ACKNOWLEDGED:
        row.acknowledged_at = row.acknowledged_at or ts

    return row


def pending_command_summary(
    session: Session, *, device_id: str, now: datetime | None = None
) -> tuple[int, datetime | None]:
    ts = _normalize_opt_utc(now) or utcnow()
    expire_commands(session, device_id=device_id, now=ts)

    count = (
        session.query(func.count(DeviceControlCommand.id))
        .filter(
            DeviceControlCommand.device_id == device_id,
            DeviceControlCommand.status == PENDING,
            DeviceControlCommand.expires_at > ts,
        )
        .scalar()
    )
    latest = (
        session.query(DeviceControlCommand.expires_at)
        .filter(
            DeviceControlCommand.device_id == device_id,
            DeviceControlCommand.status == PENDING,
            DeviceControlCommand.expires_at > ts,
        )
        .order_by(DeviceControlCommand.expires_at.desc())
        .first()
    )
    latest_expires = latest[0] if latest else None
    return int(count or 0), latest_expires


def control_command_etag_fragment(session: Session, *, device_id: str, now: datetime | None = None) -> str:
    pending = get_pending_device_command(session, device_id=device_id, now=now)
    if pending is None:
        return "none"
    return f"{pending.id}:{pending.expires_at.isoformat()}:{pending.status}"
