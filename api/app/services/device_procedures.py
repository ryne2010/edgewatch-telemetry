from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy.orm import Session

from ..models import DeviceProcedureDefinition, DeviceProcedureInvocation


STATUS_QUEUED = "queued"
STATUS_IN_PROGRESS = "in_progress"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_EXPIRED = "expired"
STATUS_SUPERSEDED = "superseded"

TERMINAL_STATUSES = {STATUS_SUCCEEDED, STATUS_FAILED, STATUS_EXPIRED, STATUS_SUPERSEDED}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def expire_invocations(session: Session, *, device_id: str | None = None, now: datetime | None = None) -> int:
    ts = now or utcnow()
    q = session.query(DeviceProcedureInvocation).filter(
        DeviceProcedureInvocation.status.in_([STATUS_QUEUED, STATUS_IN_PROGRESS]),
        DeviceProcedureInvocation.expires_at <= ts,
    )
    if device_id:
        q = q.filter(DeviceProcedureInvocation.device_id == device_id)
    rows = q.all()
    for row in rows:
        row.status = STATUS_EXPIRED
        row.completed_at = row.completed_at or ts
    return len(rows)


def supersede_pending_invocations(
    session: Session,
    *,
    device_id: str,
    now: datetime | None = None,
    exclude_id: str | None = None,
) -> int:
    ts = now or utcnow()
    q = session.query(DeviceProcedureInvocation).filter(
        DeviceProcedureInvocation.device_id == device_id,
        DeviceProcedureInvocation.status.in_([STATUS_QUEUED, STATUS_IN_PROGRESS]),
    )
    if exclude_id:
        q = q.filter(DeviceProcedureInvocation.id != exclude_id)
    rows = q.all()
    for row in rows:
        row.status = STATUS_SUPERSEDED
        row.superseded_at = ts
        row.completed_at = row.completed_at or ts
    return len(rows)


def create_definition(
    session: Session,
    *,
    name: str,
    description: str | None,
    request_schema: Mapping[str, Any] | None,
    response_schema: Mapping[str, Any] | None,
    timeout_s: int,
    enabled: bool,
    created_by: str,
) -> DeviceProcedureDefinition:
    row = DeviceProcedureDefinition(
        name=name.strip(),
        description=(description.strip() if isinstance(description, str) and description.strip() else None),
        request_schema=dict(request_schema or {}),
        response_schema=dict(response_schema or {}),
        timeout_s=max(1, int(timeout_s)),
        enabled=bool(enabled),
        created_by=created_by.strip(),
    )
    session.add(row)
    session.flush()
    return row


def enqueue_invocation(
    session: Session,
    *,
    device_id: str,
    definition: DeviceProcedureDefinition,
    requester_email: str,
    request_payload: Mapping[str, Any] | None,
    ttl_s: int,
    now: datetime | None = None,
) -> DeviceProcedureInvocation:
    ts = now or utcnow()
    expire_invocations(session, device_id=device_id, now=ts)
    supersede_pending_invocations(session, device_id=device_id, now=ts)
    row = DeviceProcedureInvocation(
        device_id=device_id,
        definition_id=definition.id,
        request_payload=dict(request_payload or {}),
        status=STATUS_QUEUED,
        requester_email=requester_email.strip(),
        issued_at=ts,
        expires_at=ts + timedelta(seconds=max(1, int(ttl_s))),
    )
    session.add(row)
    session.flush()
    return row


def get_pending_invocation(
    session: Session,
    *,
    device_id: str,
    now: datetime | None = None,
) -> DeviceProcedureInvocation | None:
    ts = now or utcnow()
    expire_invocations(session, device_id=device_id, now=ts)
    return (
        session.query(DeviceProcedureInvocation)
        .filter(
            DeviceProcedureInvocation.device_id == device_id,
            DeviceProcedureInvocation.status == STATUS_QUEUED,
            DeviceProcedureInvocation.expires_at > ts,
        )
        .order_by(DeviceProcedureInvocation.issued_at.desc(), DeviceProcedureInvocation.id.desc())
        .first()
    )


def pending_invocation_etag_fragment(
    session: Session,
    *,
    device_id: str,
    now: datetime | None = None,
) -> str:
    pending = get_pending_invocation(session, device_id=device_id, now=now)
    if pending is None:
        return "none"
    return f"{pending.id}:{pending.definition_id}:{pending.expires_at.isoformat()}"


def complete_invocation(
    session: Session,
    *,
    device_id: str,
    invocation_id: str,
    status: str,
    result_payload: Mapping[str, Any] | None,
    reason_code: str | None,
    reason_detail: str | None,
    now: datetime | None = None,
) -> DeviceProcedureInvocation | None:
    ts = now or utcnow()
    row = (
        session.query(DeviceProcedureInvocation)
        .filter(
            DeviceProcedureInvocation.id == invocation_id,
            DeviceProcedureInvocation.device_id == device_id,
        )
        .one_or_none()
    )
    if row is None:
        return None
    normalized = status.strip().lower()
    if normalized not in {STATUS_SUCCEEDED, STATUS_FAILED}:
        raise ValueError("unsupported procedure result status")
    row.status = normalized
    row.acknowledged_at = row.acknowledged_at or ts
    row.completed_at = ts
    row.result_payload = dict(result_payload or {}) if result_payload is not None else None
    row.reason_code = reason_code.strip() if isinstance(reason_code, str) and reason_code.strip() else None
    row.reason_detail = (
        reason_detail.strip() if isinstance(reason_detail, str) and reason_detail.strip() else None
    )
    return row
