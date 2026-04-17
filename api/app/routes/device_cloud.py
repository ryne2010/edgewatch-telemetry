from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import joinedload

from ..auth.audit import audit_actor_from_principal
from ..auth.principal import Principal
from ..auth.rbac import require_admin_role, require_operator_role, require_viewer_role
from ..db import db_session
from ..models import (
    Device,
    DeviceEvent,
    DeviceProcedureDefinition,
    DeviceProcedureInvocation,
    DeviceReportedState,
)
from ..observability import get_request_id
from ..schemas import (
    DeviceEventIn,
    DeviceEventOut,
    DeviceProcedureDefinitionCreateIn,
    DeviceProcedureDefinitionOut,
    DeviceProcedureDefinitionUpdateIn,
    DeviceProcedureInvocationOut,
    DeviceProcedureInvokeIn,
    DeviceProcedureResultIn,
    DeviceReportedStateIn,
    DeviceReportedStateItemOut,
    PendingProcedureInvocationOut,
)
from ..security import require_device_auth
from ..services.admin_audit import record_admin_event
from ..services.device_access import accessible_device_ids_subquery, ensure_device_access
from ..services.notifications import PlatformEvent, process_platform_event
from ..services.device_procedures import (
    complete_invocation,
    create_definition,
    enqueue_invocation,
    expire_invocations,
)


admin_router = APIRouter(
    prefix="/api/v1/admin", tags=["device-cloud-admin"], dependencies=[Depends(require_admin_role)]
)
operator_router = APIRouter(prefix="/api/v1", tags=["device-cloud"])
device_router = APIRouter(prefix="/api/v1", tags=["device-cloud-device"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _definition_out(row: DeviceProcedureDefinition) -> DeviceProcedureDefinitionOut:
    return DeviceProcedureDefinitionOut(
        id=row.id,
        name=row.name,
        description=row.description,
        request_schema=dict(row.request_schema or {}),
        response_schema=dict(row.response_schema or {}),
        timeout_s=int(row.timeout_s),
        enabled=bool(row.enabled),
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _invocation_out(row: DeviceProcedureInvocation) -> DeviceProcedureInvocationOut:
    definition = row.definition
    definition_name = definition.name if definition is not None else ""
    return DeviceProcedureInvocationOut(
        id=row.id,
        device_id=row.device_id,
        definition_id=row.definition_id,
        definition_name=definition_name,
        request_payload=dict(row.request_payload or {}),
        result_payload=dict(row.result_payload or {})
        if isinstance(row.result_payload, dict)
        else row.result_payload,
        status=cast("Any", row.status),
        reason_code=row.reason_code,
        reason_detail=row.reason_detail,
        requester_email=row.requester_email,
        issued_at=row.issued_at,
        expires_at=row.expires_at,
        acknowledged_at=row.acknowledged_at,
        completed_at=row.completed_at,
        superseded_at=row.superseded_at,
    )


def _pending_invocation_out(row: DeviceProcedureInvocation | None) -> PendingProcedureInvocationOut | None:
    if row is None:
        return None
    definition = row.definition
    return PendingProcedureInvocationOut(
        id=row.id,
        definition_id=row.definition_id,
        definition_name=definition.name if definition is not None else "",
        request_payload=dict(row.request_payload or {}),
        issued_at=row.issued_at,
        expires_at=row.expires_at,
        timeout_s=int(definition.timeout_s if definition is not None else 300),
    )


def _state_item_out(row: DeviceReportedState) -> DeviceReportedStateItemOut:
    return DeviceReportedStateItemOut(
        key=row.key,
        value_json=row.value_json,
        schema_type=row.schema_type,
        updated_at=row.updated_at,
    )


def _event_out(row: DeviceEvent) -> DeviceEventOut:
    return DeviceEventOut(
        id=row.id,
        device_id=row.device_id,
        event_type=row.event_type,
        severity=row.severity,
        source=row.source,
        body=dict(row.body or {}),
        created_at=row.created_at,
    )


@admin_router.post(
    "/procedures/definitions",
    response_model=DeviceProcedureDefinitionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_device_procedure_definition(
    req: DeviceProcedureDefinitionCreateIn,
    principal: Principal = Depends(require_admin_role),
) -> DeviceProcedureDefinitionOut:
    actor = audit_actor_from_principal(principal)
    with db_session() as session:
        existing = (
            session.query(DeviceProcedureDefinition)
            .filter(DeviceProcedureDefinition.name == req.name.strip())
            .one_or_none()
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Procedure definition already exists"
            )
        row = create_definition(
            session,
            name=req.name,
            description=req.description,
            request_schema=req.request_schema,
            response_schema=req.response_schema,
            timeout_s=req.timeout_s,
            enabled=req.enabled,
            created_by=actor.email,
        )
        record_admin_event(
            session,
            actor_email=actor.email,
            actor_subject=actor.subject,
            action="device_procedure_definition.create",
            target_type="device_procedure_definition",
            target_device_id=None,
            details={"definition_id": row.id, "name": row.name},
            request_id=get_request_id(),
        )
        return _definition_out(row)


@admin_router.get("/procedures/definitions", response_model=List[DeviceProcedureDefinitionOut])
def list_device_procedure_definitions() -> List[DeviceProcedureDefinitionOut]:
    with db_session() as session:
        rows = session.query(DeviceProcedureDefinition).order_by(DeviceProcedureDefinition.name.asc()).all()
        return [_definition_out(row) for row in rows]


@admin_router.patch("/procedures/definitions/{definition_id}", response_model=DeviceProcedureDefinitionOut)
def update_device_procedure_definition(
    definition_id: str,
    req: DeviceProcedureDefinitionUpdateIn,
    principal: Principal = Depends(require_admin_role),
) -> DeviceProcedureDefinitionOut:
    actor = audit_actor_from_principal(principal)
    with db_session() as session:
        row = (
            session.query(DeviceProcedureDefinition)
            .filter(DeviceProcedureDefinition.id == definition_id)
            .one_or_none()
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Procedure definition not found"
            )
        changed_fields: list[str] = []
        if req.description is not None:
            row.description = req.description
            changed_fields.append("description")
        if req.request_schema is not None:
            row.request_schema = dict(req.request_schema)
            changed_fields.append("request_schema")
        if req.response_schema is not None:
            row.response_schema = dict(req.response_schema)
            changed_fields.append("response_schema")
        if req.timeout_s is not None:
            row.timeout_s = req.timeout_s
            changed_fields.append("timeout_s")
        if req.enabled is not None:
            row.enabled = req.enabled
            changed_fields.append("enabled")
        row.updated_at = _utcnow()
        if changed_fields:
            record_admin_event(
                session,
                actor_email=actor.email,
                actor_subject=actor.subject,
                action="device_procedure_definition.update",
                target_type="device_procedure_definition",
                target_device_id=None,
                details={"definition_id": row.id, "changed_fields": changed_fields},
                request_id=get_request_id(),
            )
        return _definition_out(row)


@operator_router.post(
    "/devices/{device_id}/procedures/{definition_name}/invoke",
    response_model=DeviceProcedureInvocationOut,
    status_code=status.HTTP_201_CREATED,
)
def invoke_device_procedure(
    device_id: str,
    definition_name: str,
    req: DeviceProcedureInvokeIn,
    principal: Principal = Depends(require_operator_role),
) -> DeviceProcedureInvocationOut:
    actor = audit_actor_from_principal(principal)
    with db_session() as session:
        ensure_device_access(session, principal=principal, device_id=device_id, min_access_role="operator")
        definition = (
            session.query(DeviceProcedureDefinition)
            .filter(
                DeviceProcedureDefinition.name == definition_name.strip(),
                DeviceProcedureDefinition.enabled.is_(True),
            )
            .one_or_none()
        )
        if definition is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Procedure definition not found"
            )
        invocation = enqueue_invocation(
            session,
            device_id=device_id,
            definition=definition,
            requester_email=actor.email,
            request_payload=req.request_payload,
            ttl_s=req.ttl_s,
        )
        record_admin_event(
            session,
            actor_email=actor.email,
            actor_subject=actor.subject,
            action="device_procedure_invocation.create",
            target_type="device_procedure_invocation",
            target_device_id=device_id,
            details={
                "invocation_id": invocation.id,
                "definition_id": definition.id,
                "definition_name": definition.name,
            },
            request_id=get_request_id(),
        )
        session.refresh(invocation)
        return _invocation_out(invocation)


@operator_router.get(
    "/devices/{device_id}/procedure-invocations", response_model=List[DeviceProcedureInvocationOut]
)
def list_device_procedure_invocations(
    device_id: str,
    limit: int = Query(100, ge=1, le=1000),
    principal: Principal = Depends(require_viewer_role),
) -> List[DeviceProcedureInvocationOut]:
    with db_session() as session:
        ensure_device_access(session, principal=principal, device_id=device_id, min_access_role="viewer")
        expire_invocations(session, device_id=device_id)
        rows = (
            session.query(DeviceProcedureInvocation)
            .options(joinedload(DeviceProcedureInvocation.definition))
            .filter(DeviceProcedureInvocation.device_id == device_id)
            .order_by(DeviceProcedureInvocation.issued_at.desc(), DeviceProcedureInvocation.id.desc())
            .limit(limit)
            .all()
        )
        return [_invocation_out(row) for row in rows]


@operator_router.get("/devices/{device_id}/state", response_model=List[DeviceReportedStateItemOut])
def get_device_reported_state(
    device_id: str,
    principal: Principal = Depends(require_viewer_role),
) -> List[DeviceReportedStateItemOut]:
    with db_session() as session:
        ensure_device_access(session, principal=principal, device_id=device_id, min_access_role="viewer")
        rows = (
            session.query(DeviceReportedState)
            .filter(DeviceReportedState.device_id == device_id)
            .order_by(DeviceReportedState.key.asc())
            .all()
        )
        return [_state_item_out(row) for row in rows]


@operator_router.get("/device-events", response_model=List[DeviceEventOut])
def list_device_events(
    device_id: str | None = None,
    event_type: str | None = None,
    limit: int = Query(200, ge=1, le=2000),
    principal: Principal = Depends(require_viewer_role),
) -> List[DeviceEventOut]:
    with db_session() as session:
        q = session.query(DeviceEvent)
        accessible_ids = accessible_device_ids_subquery(
            session, principal=principal, min_access_role="viewer"
        )
        if accessible_ids is not None:
            q = q.filter(DeviceEvent.device_id.in_(accessible_ids))
        if device_id:
            ensure_device_access(session, principal=principal, device_id=device_id, min_access_role="viewer")
            q = q.filter(DeviceEvent.device_id == device_id)
        if event_type:
            q = q.filter(DeviceEvent.event_type == event_type.strip())
        rows = q.order_by(DeviceEvent.created_at.desc(), DeviceEvent.id.desc()).limit(limit).all()
        return [_event_out(row) for row in rows]


@device_router.post("/device-state/report", response_model=List[DeviceReportedStateItemOut])
def report_device_state(
    req: DeviceReportedStateIn,
    device: Device = Depends(require_device_auth),
) -> List[DeviceReportedStateItemOut]:
    now = _utcnow()
    with db_session() as session:
        rows_out: list[DeviceReportedStateItemOut] = []
        for key, value in req.state.items():
            key_text = str(key).strip()
            if not key_text:
                continue
            row = (
                session.query(DeviceReportedState)
                .filter(
                    DeviceReportedState.device_id == device.device_id,
                    DeviceReportedState.key == key_text,
                )
                .one_or_none()
            )
            if row is None:
                row = DeviceReportedState(
                    device_id=device.device_id,
                    key=key_text,
                    value_json={"value": value},
                    schema_type=req.schema_types.get(key_text),
                    updated_at=now,
                )
                session.add(row)
            else:
                row.value_json = {"value": value}
                row.schema_type = req.schema_types.get(key_text)
                row.updated_at = now
            rows_out.append(
                DeviceReportedStateItemOut(
                    key=key_text,
                    value_json=value,
                    schema_type=req.schema_types.get(key_text),
                    updated_at=now,
                )
            )
        return rows_out


@device_router.post("/device-events", response_model=DeviceEventOut, status_code=status.HTTP_201_CREATED)
def publish_device_event(
    req: DeviceEventIn,
    device: Device = Depends(require_device_auth),
) -> DeviceEventOut:
    with db_session() as session:
        row = DeviceEvent(
            device_id=device.device_id,
            event_type=req.event_type.strip(),
            severity=req.severity,
            source=req.source.strip(),
            body=dict(req.body or {}),
        )
        session.add(row)
        session.flush()
        process_platform_event(
            session,
            PlatformEvent(
                source_kind="device_event",
                source_id=row.id,
                device_id=row.device_id,
                event_type=row.event_type,
                severity=row.severity,
                message=row.event_type,
                payload=dict(row.body or {}),
                created_at=row.created_at,
            ),
        )
        return _event_out(row)


@device_router.post(
    "/device-procedure-invocations/{invocation_id}/result", response_model=DeviceProcedureInvocationOut
)
def complete_device_procedure_invocation(
    invocation_id: str,
    req: DeviceProcedureResultIn,
    device: Device = Depends(require_device_auth),
) -> DeviceProcedureInvocationOut:
    with db_session() as session:
        row = complete_invocation(
            session,
            device_id=device.device_id,
            invocation_id=invocation_id,
            status=req.status,
            result_payload=req.result_payload,
            reason_code=req.reason_code,
            reason_detail=req.reason_detail,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Procedure invocation not found"
            )
        row = (
            session.query(DeviceProcedureInvocation)
            .options(joinedload(DeviceProcedureInvocation.definition))
            .filter(DeviceProcedureInvocation.id == row.id)
            .one()
        )
        process_platform_event(
            session,
            PlatformEvent(
                source_kind="procedure_invocation",
                source_id=row.id,
                device_id=row.device_id,
                event_type=(row.definition.name if row.definition is not None else row.definition_id),
                severity="info" if row.status == "succeeded" else "error",
                message=row.reason_detail or row.status,
                payload={
                    "status": row.status,
                    "reason_code": row.reason_code,
                    "reason_detail": row.reason_detail,
                    "result_payload": row.result_payload,
                },
                created_at=datetime.now(timezone.utc),
            ),
        )
        return _invocation_out(row)
