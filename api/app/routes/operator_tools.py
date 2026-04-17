from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, List

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import Text, cast, or_
from sqlalchemy.orm import joinedload

from ..auth.principal import Principal
from ..auth.rbac import require_viewer_role
from ..db import db_session
from ..models import (
    AdminEvent,
    Alert,
    Deployment,
    DeploymentEvent,
    Device,
    DeviceEvent,
    DeviceProcedureDefinition,
    DeviceProcedureInvocation,
    DriftEvent,
    Fleet,
    ExportBatch,
    IngestionBatch,
    NotificationDestination,
    NotificationEvent,
    ReleaseManifest,
)
from ..schemas import (
    OperatorEventOut,
    OperatorEventPageOut,
    OperatorSearchPageOut,
    OperatorSearchResultOut,
)
from ..services.device_access import accessible_device_ids_subquery, ensure_device_access
from ..services.device_identity import safe_display_name


router = APIRouter(prefix="/api/v1", tags=["operator-tools"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _operator_events_page(
    *,
    principal: Principal,
    device_id: str | None,
    source_kinds: list[str],
    event_name: str | None,
    limit: int,
    offset: int,
) -> OperatorEventPageOut:
    normalized_limit = limit if isinstance(limit, int) else 50
    normalized_offset = offset if isinstance(offset, int) else 0
    requested_sources = {value.strip() for value in source_kinds if value.strip()}
    fetch_limit = max(1, min(normalized_limit + normalized_offset, 5000))
    event_pattern = f"%{event_name.strip()}%" if event_name and event_name.strip() else None
    items: list[OperatorEventOut] = []
    with db_session() as session:
        accessible_ids = accessible_device_ids_subquery(
            session, principal=principal, min_access_role="viewer"
        )
        if device_id:
            ensure_device_access(session, principal=principal, device_id=device_id, min_access_role="viewer")

        if not requested_sources or "alert" in requested_sources:
            q = session.query(Alert)
            if accessible_ids is not None:
                q = q.filter(Alert.device_id.in_(accessible_ids))
            if device_id:
                q = q.filter(Alert.device_id == device_id)
            if event_pattern:
                q = q.filter(Alert.alert_type.ilike(event_pattern))
            rows = q.order_by(Alert.created_at.desc(), Alert.id.desc()).limit(fetch_limit).all()
            items.extend(
                OperatorEventOut(
                    source_kind="alert",
                    entity_id=row.id,
                    device_id=row.device_id,
                    event_name=row.alert_type,
                    severity=row.severity,
                    created_at=row.created_at,
                    payload={"message": row.message},
                )
                for row in rows
            )

        if principal.role == "admin" and (not requested_sources or "notification_event" in requested_sources):
            q = session.query(NotificationEvent)
            if device_id:
                q = q.filter(NotificationEvent.device_id == device_id)
            if event_pattern:
                q = q.filter(NotificationEvent.alert_type.ilike(event_pattern))
            rows = (
                q.order_by(NotificationEvent.created_at.desc(), NotificationEvent.id.desc())
                .limit(fetch_limit)
                .all()
            )
            items.extend(
                OperatorEventOut(
                    source_kind="notification_event",
                    entity_id=row.id,
                    device_id=row.device_id,
                    event_name=row.alert_type,
                    severity="info",
                    created_at=row.created_at,
                    payload={
                        "channel": row.channel,
                        "decision": row.decision,
                        "reason": row.reason,
                        "source_kind": row.source_kind,
                    },
                )
                for row in rows
            )

        if not requested_sources or "device_event" in requested_sources:
            q = session.query(DeviceEvent)
            if accessible_ids is not None:
                q = q.filter(DeviceEvent.device_id.in_(accessible_ids))
            if device_id:
                q = q.filter(DeviceEvent.device_id == device_id)
            if event_pattern:
                q = q.filter(DeviceEvent.event_type.ilike(event_pattern))
            rows = q.order_by(DeviceEvent.created_at.desc(), DeviceEvent.id.desc()).limit(fetch_limit).all()
            items.extend(
                OperatorEventOut(
                    source_kind="device_event",
                    entity_id=row.id,
                    device_id=row.device_id,
                    event_name=row.event_type,
                    severity=row.severity,
                    created_at=row.created_at,
                    payload=row.body,
                )
                for row in rows
            )

        if not requested_sources or "procedure_invocation" in requested_sources:
            q = session.query(DeviceProcedureInvocation).options(
                joinedload(DeviceProcedureInvocation.definition)
            )
            if accessible_ids is not None:
                q = q.filter(DeviceProcedureInvocation.device_id.in_(accessible_ids))
            if device_id:
                q = q.filter(DeviceProcedureInvocation.device_id == device_id)
            if event_pattern:
                q = q.join(
                    DeviceProcedureDefinition,
                    DeviceProcedureDefinition.id == DeviceProcedureInvocation.definition_id,
                ).filter(DeviceProcedureDefinition.name.ilike(event_pattern))
            rows = (
                q.order_by(DeviceProcedureInvocation.issued_at.desc(), DeviceProcedureInvocation.id.desc())
                .limit(fetch_limit)
                .all()
            )
            items.extend(
                OperatorEventOut(
                    source_kind="procedure_invocation",
                    entity_id=row.id,
                    device_id=row.device_id,
                    event_name=row.definition.name if row.definition is not None else row.definition_id,
                    severity="info",
                    created_at=row.issued_at,
                    payload={"status": row.status, "request_payload": row.request_payload},
                )
                for row in rows
            )

        if principal.role == "admin" and (not requested_sources or "deployment_event" in requested_sources):
            q = session.query(DeploymentEvent)
            if device_id:
                q = q.filter(DeploymentEvent.device_id == device_id)
            if event_pattern:
                q = q.filter(DeploymentEvent.event_type.ilike(event_pattern))
            rows = (
                q.order_by(DeploymentEvent.created_at.desc(), DeploymentEvent.id.desc())
                .limit(fetch_limit)
                .all()
            )
            items.extend(
                OperatorEventOut(
                    source_kind="deployment_event",
                    entity_id=row.id,
                    device_id=row.device_id,
                    event_name=row.event_type,
                    severity="info",
                    created_at=row.created_at,
                    payload={"deployment_id": row.deployment_id, **dict(row.details or {})},
                )
                for row in rows
            )

        if principal.role == "admin" and (
            not requested_sources or "release_manifest_event" in requested_sources
        ):
            q = session.query(AdminEvent).filter(AdminEvent.target_type == "release_manifest")
            if event_pattern:
                q = q.filter(AdminEvent.action.ilike(event_pattern))
            rows = q.order_by(AdminEvent.created_at.desc(), AdminEvent.id.desc()).limit(fetch_limit).all()
            items.extend(
                OperatorEventOut(
                    source_kind="release_manifest_event",
                    entity_id=row.id,
                    device_id=row.target_device_id,
                    event_name=row.action,
                    severity="info",
                    created_at=row.created_at,
                    payload={"actor_email": row.actor_email, **dict(row.details or {})},
                )
                for row in rows
            )

        if principal.role == "admin" and (not requested_sources or "admin_event" in requested_sources):
            q = session.query(AdminEvent).filter(AdminEvent.target_type != "release_manifest")
            rows = q.order_by(AdminEvent.created_at.desc(), AdminEvent.id.desc()).limit(fetch_limit).all()
            items.extend(
                OperatorEventOut(
                    source_kind="admin_event",
                    entity_id=row.id,
                    device_id=row.target_device_id,
                    event_name=row.action,
                    severity="info",
                    created_at=row.created_at,
                    payload={
                        "actor_email": row.actor_email,
                        "target_type": row.target_type,
                        "target_device_id": row.target_device_id,
                        **dict(row.details or {}),
                    },
                )
                for row in rows
            )

    items.sort(key=lambda row: row.created_at, reverse=True)
    return OperatorEventPageOut(
        items=items[normalized_offset : normalized_offset + normalized_limit],
        total=len(items),
        limit=normalized_limit,
        offset=normalized_offset,
    )


@router.get("/search", response_model=List[OperatorSearchResultOut])
def operator_search(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=5000),
    entity_types: list[str] | None = Query(default=None, alias="entity_type"),
    principal: Principal = Depends(require_viewer_role),
) -> List[OperatorSearchResultOut]:
    pattern = f"%{q.strip()}%"
    raw_entity_types = entity_types if isinstance(entity_types, list) else []
    requested_types = {value.strip() for value in raw_entity_types if value.strip()}
    normalized_limit = limit if isinstance(limit, int) else 50
    normalized_offset = offset if isinstance(offset, int) else 0
    fetch_limit = max(1, min(normalized_limit + normalized_offset, 5000))
    out: list[OperatorSearchResultOut] = []
    with db_session() as session:
        accessible_ids = accessible_device_ids_subquery(
            session, principal=principal, min_access_role="viewer"
        )

        if not requested_types or "device" in requested_types:
            devices_q = session.query(Device)
            if accessible_ids is not None:
                devices_q = devices_q.filter(Device.device_id.in_(accessible_ids))
            devices = (
                devices_q.filter(or_(Device.device_id.ilike(pattern), Device.display_name.ilike(pattern)))
                .order_by(Device.created_at.desc(), Device.device_id.asc())
                .limit(fetch_limit)
                .all()
            )
            out.extend(
                OperatorSearchResultOut(
                    entity_type="device",
                    entity_id=row.device_id,
                    title=safe_display_name(row.device_id, row.display_name),
                    subtitle=row.device_id,
                    device_id=row.device_id,
                    created_at=row.created_at,
                    metadata={"ota_channel": row.ota_channel, "enabled": row.enabled},
                )
                for row in devices
            )

        if not requested_types or "fleet" in requested_types:
            if principal.role == "admin":
                fleets_q = session.query(Fleet)
            else:
                from ..models import FleetAccessGrant

                fleets_q = (
                    session.query(Fleet)
                    .join(FleetAccessGrant, FleetAccessGrant.fleet_id == Fleet.id)
                    .filter(FleetAccessGrant.principal_email == principal.email.lower())
                )
            fleets = (
                fleets_q.filter(or_(Fleet.name.ilike(pattern), Fleet.description.ilike(pattern)))
                .order_by(Fleet.created_at.desc(), Fleet.name.asc())
                .limit(fetch_limit)
                .all()
            )
            out.extend(
                OperatorSearchResultOut(
                    entity_type="fleet",
                    entity_id=row.id,
                    title=row.name,
                    subtitle=row.description,
                    created_at=row.created_at,
                    metadata={"default_ota_channel": row.default_ota_channel},
                )
                for row in fleets
            )

        if not requested_types or "alert" in requested_types:
            alerts_q = session.query(Alert)
            if accessible_ids is not None:
                alerts_q = alerts_q.filter(Alert.device_id.in_(accessible_ids))
            alerts = (
                alerts_q.filter(
                    or_(
                        Alert.device_id.ilike(pattern),
                        Alert.alert_type.ilike(pattern),
                        Alert.message.ilike(pattern),
                    )
                )
                .order_by(Alert.created_at.desc())
                .limit(fetch_limit)
                .all()
            )
            out.extend(
                OperatorSearchResultOut(
                    entity_type="alert",
                    entity_id=row.id,
                    title=row.alert_type,
                    subtitle=row.message,
                    device_id=row.device_id,
                    created_at=row.created_at,
                    metadata={"severity": row.severity},
                )
                for row in alerts
            )

        if principal.role == "admin" and (not requested_types or "ingestion_batch" in requested_types):
            ingestion_batches = (
                session.query(IngestionBatch)
                .filter(
                    or_(
                        IngestionBatch.device_id.ilike(pattern),
                        IngestionBatch.contract_version.ilike(pattern),
                        IngestionBatch.processing_status.ilike(pattern),
                    )
                )
                .order_by(IngestionBatch.received_at.desc())
                .limit(fetch_limit)
                .all()
            )
            out.extend(
                OperatorSearchResultOut(
                    entity_type="ingestion_batch",
                    entity_id=row.id,
                    title=row.processing_status,
                    subtitle=row.contract_version,
                    device_id=row.device_id,
                    created_at=row.received_at,
                    metadata={"duplicates": row.duplicates, "source": row.source},
                )
                for row in ingestion_batches
            )

        if principal.role == "admin" and (not requested_types or "drift_event" in requested_types):
            drift_events = (
                session.query(DriftEvent)
                .filter(
                    or_(
                        DriftEvent.device_id.ilike(pattern),
                        DriftEvent.event_type.ilike(pattern),
                        DriftEvent.action.ilike(pattern),
                        cast(DriftEvent.details, Text).ilike(pattern),
                    )
                )
                .order_by(DriftEvent.created_at.desc())
                .limit(fetch_limit)
                .all()
            )
            out.extend(
                OperatorSearchResultOut(
                    entity_type="drift_event",
                    entity_id=row.id,
                    title=row.event_type,
                    subtitle=row.action,
                    device_id=row.device_id,
                    created_at=row.created_at,
                    metadata={"batch_id": row.batch_id},
                )
                for row in drift_events
            )

        if principal.role == "admin" and (not requested_types or "procedure_definition" in requested_types):
            procedure_definitions = (
                session.query(DeviceProcedureDefinition)
                .filter(
                    or_(
                        DeviceProcedureDefinition.name.ilike(pattern),
                        DeviceProcedureDefinition.description.ilike(pattern),
                    )
                )
                .order_by(DeviceProcedureDefinition.updated_at.desc())
                .limit(fetch_limit)
                .all()
            )
            out.extend(
                OperatorSearchResultOut(
                    entity_type="procedure_definition",
                    entity_id=row.id,
                    title=row.name,
                    subtitle=row.description,
                    created_at=row.updated_at,
                    metadata={"enabled": row.enabled, "timeout_s": row.timeout_s},
                )
                for row in procedure_definitions
            )

        if not requested_types or "device_event" in requested_types:
            device_events_q = session.query(DeviceEvent)
            if accessible_ids is not None:
                device_events_q = device_events_q.filter(DeviceEvent.device_id.in_(accessible_ids))
            device_events = (
                device_events_q.filter(
                    or_(
                        DeviceEvent.device_id.ilike(pattern),
                        DeviceEvent.event_type.ilike(pattern),
                        cast(DeviceEvent.body, Text).ilike(pattern),
                    )
                )
                .order_by(DeviceEvent.created_at.desc())
                .limit(fetch_limit)
                .all()
            )
            out.extend(
                OperatorSearchResultOut(
                    entity_type="device_event",
                    entity_id=row.id,
                    title=row.event_type,
                    subtitle=row.source,
                    device_id=row.device_id,
                    created_at=row.created_at,
                    metadata={"severity": row.severity},
                )
                for row in device_events
            )

        if not requested_types or "procedure_invocation" in requested_types:
            invocations_q = session.query(DeviceProcedureInvocation).options(
                joinedload(DeviceProcedureInvocation.definition)
            )
            if accessible_ids is not None:
                invocations_q = invocations_q.filter(DeviceProcedureInvocation.device_id.in_(accessible_ids))
            invocations = (
                invocations_q.filter(
                    or_(
                        DeviceProcedureInvocation.device_id.ilike(pattern),
                        cast(DeviceProcedureInvocation.request_payload, Text).ilike(pattern),
                    )
                )
                .order_by(DeviceProcedureInvocation.issued_at.desc())
                .limit(fetch_limit)
                .all()
            )
            out.extend(
                OperatorSearchResultOut(
                    entity_type="procedure_invocation",
                    entity_id=row.id,
                    title=row.definition.name if row.definition is not None else row.definition_id,
                    subtitle=row.status,
                    device_id=row.device_id,
                    created_at=row.issued_at,
                    metadata={"status": row.status},
                )
                for row in invocations
            )

        if principal.role == "admin" and (not requested_types or "deployment" in requested_types):
            deployments = (
                session.query(Deployment)
                .filter(or_(Deployment.id.ilike(pattern), Deployment.status.ilike(pattern)))
                .order_by(Deployment.created_at.desc())
                .limit(fetch_limit)
                .all()
            )
            out.extend(
                OperatorSearchResultOut(
                    entity_type="deployment",
                    entity_id=row.id,
                    title=row.id,
                    subtitle=row.status,
                    created_at=row.created_at,
                    metadata={"manifest_id": row.manifest_id, "stage": row.stage},
                )
                for row in deployments
            )

        if principal.role == "admin" and (not requested_types or "release_manifest" in requested_types):
            manifests = (
                session.query(ReleaseManifest)
                .filter(
                    or_(
                        ReleaseManifest.id.ilike(pattern),
                        ReleaseManifest.git_tag.ilike(pattern),
                        ReleaseManifest.status.ilike(pattern),
                    )
                )
                .order_by(ReleaseManifest.created_at.desc())
                .limit(fetch_limit)
                .all()
            )
            out.extend(
                OperatorSearchResultOut(
                    entity_type="release_manifest",
                    entity_id=row.id,
                    title=row.git_tag,
                    subtitle=row.status,
                    created_at=row.created_at,
                    metadata={"update_type": row.update_type},
                )
                for row in manifests
            )

        if principal.role == "admin" and (not requested_types or "admin_event" in requested_types):
            admin_events = (
                session.query(AdminEvent)
                .filter(
                    or_(
                        AdminEvent.action.ilike(pattern),
                        AdminEvent.target_type.ilike(pattern),
                        cast(AdminEvent.details, Text).ilike(pattern),
                    )
                )
                .order_by(AdminEvent.created_at.desc())
                .limit(fetch_limit)
                .all()
            )
            out.extend(
                OperatorSearchResultOut(
                    entity_type="admin_event",
                    entity_id=row.id,
                    title=row.action,
                    subtitle=row.target_type,
                    device_id=row.target_device_id,
                    created_at=row.created_at,
                    metadata={"request_id": row.request_id, **dict(row.details or {})},
                )
                for row in admin_events
            )

        if principal.role == "admin" and (not requested_types or "notification_event" in requested_types):
            notification_events = (
                session.query(NotificationEvent)
                .filter(
                    or_(
                        NotificationEvent.device_id.ilike(pattern),
                        NotificationEvent.alert_type.ilike(pattern),
                        NotificationEvent.channel.ilike(pattern),
                        NotificationEvent.reason.ilike(pattern),
                    )
                )
                .order_by(NotificationEvent.created_at.desc())
                .limit(fetch_limit)
                .all()
            )
            out.extend(
                OperatorSearchResultOut(
                    entity_type="notification_event",
                    entity_id=row.id,
                    title=row.alert_type,
                    subtitle=row.reason,
                    device_id=row.device_id,
                    created_at=row.created_at,
                    metadata={
                        "channel": row.channel,
                        "decision": row.decision,
                        "source_kind": row.source_kind,
                        "delivered": row.delivered,
                    },
                )
                for row in notification_events
            )

        if principal.role == "admin" and (
            not requested_types or "notification_destination" in requested_types
        ):
            notification_destinations = (
                session.query(NotificationDestination)
                .filter(
                    or_(
                        NotificationDestination.name.ilike(pattern),
                        NotificationDestination.channel.ilike(pattern),
                        NotificationDestination.kind.ilike(pattern),
                        cast(NotificationDestination.source_types, Text).ilike(pattern),
                        cast(NotificationDestination.event_types, Text).ilike(pattern),
                    )
                )
                .order_by(NotificationDestination.updated_at.desc())
                .limit(fetch_limit)
                .all()
            )
            out.extend(
                OperatorSearchResultOut(
                    entity_type="notification_destination",
                    entity_id=row.id,
                    title=row.name,
                    subtitle=row.kind,
                    created_at=row.updated_at,
                    metadata={
                        "channel": row.channel,
                        "enabled": row.enabled,
                    },
                )
                for row in notification_destinations
            )

        if principal.role == "admin" and (not requested_types or "export_batch" in requested_types):
            export_batches = (
                session.query(ExportBatch)
                .filter(
                    or_(
                        ExportBatch.status.ilike(pattern),
                        ExportBatch.contract_version.ilike(pattern),
                        ExportBatch.gcs_uri.ilike(pattern),
                    )
                )
                .order_by(ExportBatch.started_at.desc())
                .limit(fetch_limit)
                .all()
            )
            out.extend(
                OperatorSearchResultOut(
                    entity_type="export_batch",
                    entity_id=row.id,
                    title=row.status,
                    subtitle=row.contract_version,
                    created_at=row.started_at,
                    metadata={"gcs_uri": row.gcs_uri, "row_count": row.row_count},
                )
                for row in export_batches
            )

    out.sort(key=lambda row: row.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out[normalized_offset : normalized_offset + normalized_limit]


@router.get("/search-page", response_model=OperatorSearchPageOut)
def operator_search_page(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=5000),
    entity_types: list[str] | None = Query(default=None, alias="entity_type"),
    principal: Principal = Depends(require_viewer_role),
) -> OperatorSearchPageOut:
    normalized_limit = limit if isinstance(limit, int) else 50
    normalized_offset = offset if isinstance(offset, int) else 0
    raw_entity_types = entity_types if isinstance(entity_types, list) else []
    all_results = operator_search(
        q=q,
        limit=5000,
        offset=0,
        entity_types=raw_entity_types,
        principal=principal,
    )
    return OperatorSearchPageOut(
        items=all_results[normalized_offset : normalized_offset + normalized_limit],
        total=len(all_results),
        limit=normalized_limit,
        offset=normalized_offset,
    )


@router.get("/operator-events", response_model=OperatorEventPageOut)
def operator_events(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=5000),
    device_id: str | None = None,
    source_kinds: list[str] | None = Query(default=None, alias="source_kind"),
    event_name: str | None = Query(default=None),
    principal: Principal = Depends(require_viewer_role),
) -> OperatorEventPageOut:
    raw_source_kinds = source_kinds if isinstance(source_kinds, list) else []
    return _operator_events_page(
        principal=principal,
        device_id=device_id,
        source_kinds=[value.strip() for value in raw_source_kinds if value.strip()],
        event_name=event_name if isinstance(event_name, str) else None,
        limit=limit,
        offset=offset,
    )


async def _stream_events(
    *,
    request: Request,
    principal: Principal,
    device_id: str | None,
    source_kinds: list[str],
    event_name: str | None,
    since_seconds: int,
) -> AsyncIterator[str]:
    baseline = _utcnow()
    last_seen = baseline - timedelta(seconds=max(0, int(since_seconds)))
    while True:
        if await request.is_disconnected():
            break
        payloads: list[dict[str, Any]] = []
        with db_session() as session:
            accessible_ids = accessible_device_ids_subquery(
                session, principal=principal, min_access_role="viewer"
            )
            if device_id:
                ensure_device_access(
                    session, principal=principal, device_id=device_id, min_access_role="viewer"
                )

            event_pattern = f"%{event_name.strip()}%" if event_name and event_name.strip() else None

            if not source_kinds or "alert" in source_kinds:
                q = session.query(Alert).filter(Alert.created_at > last_seen)
                if accessible_ids is not None:
                    q = q.filter(Alert.device_id.in_(accessible_ids))
                if device_id:
                    q = q.filter(Alert.device_id == device_id)
                if event_pattern:
                    q = q.filter(Alert.alert_type.ilike(event_pattern))
                for row in q.order_by(Alert.created_at.asc(), Alert.id.asc()).all():
                    payloads.append(
                        {
                            "type": "alert",
                            "id": row.id,
                            "device_id": row.device_id,
                            "event_type": row.alert_type,
                            "created_at": row.created_at.isoformat(),
                            "body": {"severity": row.severity, "message": row.message},
                        }
                    )

            if principal.role == "admin" and (not source_kinds or "notification_event" in source_kinds):
                q = session.query(NotificationEvent).filter(NotificationEvent.created_at > last_seen)
                if device_id:
                    q = q.filter(NotificationEvent.device_id == device_id)
                if event_pattern:
                    q = q.filter(NotificationEvent.alert_type.ilike(event_pattern))
                for row in q.order_by(NotificationEvent.created_at.asc(), NotificationEvent.id.asc()).all():
                    payloads.append(
                        {
                            "type": "notification_event",
                            "id": row.id,
                            "device_id": row.device_id,
                            "event_type": row.alert_type,
                            "created_at": row.created_at.isoformat(),
                            "body": {
                                "channel": row.channel,
                                "decision": row.decision,
                                "reason": row.reason,
                                "source_kind": row.source_kind,
                            },
                        }
                    )

            if not source_kinds or "device_event" in source_kinds:
                q = session.query(DeviceEvent).filter(DeviceEvent.created_at > last_seen)
                if accessible_ids is not None:
                    q = q.filter(DeviceEvent.device_id.in_(accessible_ids))
                if device_id:
                    q = q.filter(DeviceEvent.device_id == device_id)
                if event_pattern:
                    q = q.filter(DeviceEvent.event_type.ilike(event_pattern))
                for row in q.order_by(DeviceEvent.created_at.asc(), DeviceEvent.id.asc()).all():
                    payloads.append(
                        {
                            "type": "device_event",
                            "id": row.id,
                            "device_id": row.device_id,
                            "event_type": row.event_type,
                            "created_at": row.created_at.isoformat(),
                            "body": row.body,
                        }
                    )

            if not source_kinds or "procedure_invocation" in source_kinds:
                q = (
                    session.query(DeviceProcedureInvocation)
                    .options(joinedload(DeviceProcedureInvocation.definition))
                    .filter(DeviceProcedureInvocation.issued_at > last_seen)
                )
                if accessible_ids is not None:
                    q = q.filter(DeviceProcedureInvocation.device_id.in_(accessible_ids))
                if device_id:
                    q = q.filter(DeviceProcedureInvocation.device_id == device_id)
                if event_pattern:
                    q = q.join(
                        DeviceProcedureDefinition,
                        DeviceProcedureDefinition.id == DeviceProcedureInvocation.definition_id,
                    ).filter(DeviceProcedureDefinition.name.ilike(event_pattern))
                for row in q.order_by(
                    DeviceProcedureInvocation.issued_at.asc(), DeviceProcedureInvocation.id.asc()
                ).all():
                    payloads.append(
                        {
                            "type": "procedure_invocation",
                            "id": row.id,
                            "device_id": row.device_id,
                            "event_type": row.definition.name
                            if row.definition is not None
                            else row.definition_id,
                            "created_at": row.issued_at.isoformat(),
                            "body": {"status": row.status, "request_payload": row.request_payload},
                        }
                    )

            if principal.role == "admin" and (not source_kinds or "deployment_event" in source_kinds):
                q = session.query(DeploymentEvent).filter(DeploymentEvent.created_at > last_seen)
                if device_id:
                    q = q.filter(DeploymentEvent.device_id == device_id)
                if event_pattern:
                    q = q.filter(DeploymentEvent.event_type.ilike(event_pattern))
                for row in q.order_by(DeploymentEvent.created_at.asc(), DeploymentEvent.id.asc()).all():
                    payloads.append(
                        {
                            "type": "deployment_event",
                            "id": row.id,
                            "device_id": row.device_id,
                            "event_type": row.event_type,
                            "created_at": row.created_at.isoformat(),
                            "body": {"deployment_id": row.deployment_id, **dict(row.details or {})},
                        }
                    )

            if principal.role == "admin" and (not source_kinds or "release_manifest_event" in source_kinds):
                q = session.query(AdminEvent).filter(
                    AdminEvent.target_type == "release_manifest",
                    AdminEvent.created_at > last_seen,
                )
                if event_pattern:
                    q = q.filter(AdminEvent.action.ilike(event_pattern))
                for row in q.order_by(AdminEvent.created_at.asc(), AdminEvent.id.asc()).all():
                    payloads.append(
                        {
                            "type": "release_manifest_event",
                            "id": row.id,
                            "device_id": row.target_device_id,
                            "event_type": row.action,
                            "created_at": row.created_at.isoformat(),
                            "body": {"actor_email": row.actor_email, **dict(row.details or {})},
                        }
                    )

            if principal.role == "admin" and (not source_kinds or "admin_event" in source_kinds):
                q = session.query(AdminEvent).filter(
                    AdminEvent.target_type != "release_manifest",
                    AdminEvent.created_at > last_seen,
                )
                if event_pattern:
                    q = q.filter(AdminEvent.action.ilike(event_pattern))
                for row in q.order_by(AdminEvent.created_at.asc(), AdminEvent.id.asc()).all():
                    payloads.append(
                        {
                            "type": "admin_event",
                            "id": row.id,
                            "device_id": row.target_device_id,
                            "event_type": row.action,
                            "created_at": row.created_at.isoformat(),
                            "body": {
                                "actor_email": row.actor_email,
                                "target_type": row.target_type,
                                "target_device_id": row.target_device_id,
                                **dict(row.details or {}),
                            },
                        }
                    )

        payloads.sort(key=lambda row: row["created_at"])
        for item in payloads:
            yield f"event: {item['type']}\n"
            yield f"data: {json.dumps(item, sort_keys=True)}\n\n"
            seen_at = datetime.fromisoformat(item["created_at"])
            if seen_at.tzinfo is None:
                seen_at = seen_at.replace(tzinfo=timezone.utc)
            else:
                seen_at = seen_at.astimezone(timezone.utc)
            last_seen = max(last_seen, seen_at)
        yield "event: keepalive\ndata: {}\n\n"
        await asyncio.sleep(1.0)


@router.get("/event-stream")
async def event_stream(
    request: Request,
    device_id: str | None = None,
    event_types: list[str] | None = Query(default=None, alias="event_type"),
    source_kinds: list[str] | None = Query(default=None, alias="source_kind"),
    event_name: str | None = Query(default=None),
    since_seconds: int = Query(default=0, ge=0, le=7 * 24 * 3600),
    principal: Principal = Depends(require_viewer_role),
) -> StreamingResponse:
    legacy_event_types = [value.strip() for value in (event_types or []) if value.strip()]
    normalized_source_kinds: list[str] = []
    mapping = {
        "alerts": "alert",
        "device_events": "device_event",
        "procedure_invocations": "procedure_invocation",
    }
    for value in legacy_event_types + [value.strip() for value in (source_kinds or []) if value.strip()]:
        normalized = mapping.get(value, value)
        if normalized not in normalized_source_kinds:
            normalized_source_kinds.append(normalized)
    stream = _stream_events(
        request=request,
        principal=principal,
        device_id=device_id,
        source_kinds=normalized_source_kinds,
        event_name=event_name,
        since_seconds=since_seconds,
    )
    return StreamingResponse(stream, media_type="text/event-stream")
