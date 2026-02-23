from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc

from ..auth.audit import audit_actor_from_principal
from ..auth.principal import Principal
from ..auth.rbac import require_admin_role
from ..config import settings
from ..db import db_session
from ..edge_policy import EdgePolicy, load_edge_policy_source, save_edge_policy_source
from ..models import (
    AdminEvent,
    Device,
    DriftEvent,
    ExportBatch,
    IngestionBatch,
    NotificationDestination,
    NotificationEvent,
)
from ..observability import get_request_id
from ..schemas import (
    AdminEventOut,
    AdminDeviceCreate,
    AdminDeviceUpdate,
    DeviceOut,
    DriftEventOut,
    EdgePolicyAlertThresholdsOut,
    EdgePolicyContractOut,
    EdgePolicyContractSourceOut,
    EdgePolicyContractUpdateIn,
    EdgePolicyCostCapsOut,
    EdgePolicyReportingOut,
    ExportBatchOut,
    IngestionBatchOut,
    NotificationDestinationCreate,
    NotificationDestinationOut,
    NotificationDestinationUpdate,
    NotificationEventOut,
)
from ..security import hash_token, token_fingerprint
from ..services.admin_audit import record_admin_event
from ..services.monitor import compute_status
from ..services.notifications import destination_fingerprint, mask_webhook_url

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin_role)])


def _normalize_webhook_url(value: str) -> str:
    candidate = (value or "").strip()
    if not candidate:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="webhook_url is required")
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="webhook_url must be an absolute http(s) URL",
        )
    return candidate


def _notification_destination_out(row: NotificationDestination) -> NotificationDestinationOut:
    return NotificationDestinationOut(
        id=row.id,
        name=row.name,
        channel=row.channel,
        kind=row.kind,
        enabled=row.enabled,
        webhook_url_masked=mask_webhook_url(row.webhook_url),
        destination_fingerprint=destination_fingerprint(row.webhook_url),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _edge_policy_contract_out(policy: EdgePolicy) -> EdgePolicyContractOut:
    return EdgePolicyContractOut(
        policy_version=policy.version,
        policy_sha256=policy.sha256,
        cache_max_age_s=policy.cache_max_age_s,
        reporting=EdgePolicyReportingOut(
            sample_interval_s=policy.reporting.sample_interval_s,
            alert_sample_interval_s=policy.reporting.alert_sample_interval_s,
            heartbeat_interval_s=policy.reporting.heartbeat_interval_s,
            alert_report_interval_s=policy.reporting.alert_report_interval_s,
            max_points_per_batch=policy.reporting.max_points_per_batch,
            buffer_max_points=policy.reporting.buffer_max_points,
            buffer_max_age_s=policy.reporting.buffer_max_age_s,
            backoff_initial_s=policy.reporting.backoff_initial_s,
            backoff_max_s=policy.reporting.backoff_max_s,
        ),
        delta_thresholds={k: policy.delta_thresholds[k] for k in sorted(policy.delta_thresholds)},
        alert_thresholds=EdgePolicyAlertThresholdsOut(
            water_pressure_low_psi=policy.alert_thresholds.water_pressure_low_psi,
            water_pressure_recover_psi=policy.alert_thresholds.water_pressure_recover_psi,
            oil_pressure_low_psi=policy.alert_thresholds.oil_pressure_low_psi,
            oil_pressure_recover_psi=policy.alert_thresholds.oil_pressure_recover_psi,
            oil_level_low_pct=policy.alert_thresholds.oil_level_low_pct,
            oil_level_recover_pct=policy.alert_thresholds.oil_level_recover_pct,
            drip_oil_level_low_pct=policy.alert_thresholds.drip_oil_level_low_pct,
            drip_oil_level_recover_pct=policy.alert_thresholds.drip_oil_level_recover_pct,
            oil_life_low_pct=policy.alert_thresholds.oil_life_low_pct,
            oil_life_recover_pct=policy.alert_thresholds.oil_life_recover_pct,
            battery_low_v=policy.alert_thresholds.battery_low_v,
            battery_recover_v=policy.alert_thresholds.battery_recover_v,
            signal_low_rssi_dbm=policy.alert_thresholds.signal_low_rssi_dbm,
            signal_recover_rssi_dbm=policy.alert_thresholds.signal_recover_rssi_dbm,
        ),
        cost_caps=EdgePolicyCostCapsOut(
            max_bytes_per_day=policy.cost_caps.max_bytes_per_day,
            max_snapshots_per_day=policy.cost_caps.max_snapshots_per_day,
            max_media_uploads_per_day=policy.cost_caps.max_media_uploads_per_day,
        ),
    )


@router.get(
    "/contracts/edge-policy/source",
    response_model=EdgePolicyContractSourceOut,
)
def get_edge_policy_contract_source_admin() -> EdgePolicyContractSourceOut:
    version = settings.edge_policy_version
    try:
        yaml_text = load_edge_policy_source(version)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="edge policy contract is not available",
        ) from exc
    return EdgePolicyContractSourceOut(policy_version=version, yaml_text=yaml_text)


@router.patch(
    "/contracts/edge-policy",
    response_model=EdgePolicyContractOut,
)
def update_edge_policy_contract_admin(
    req: EdgePolicyContractUpdateIn,
    principal: Principal = Depends(require_admin_role),
) -> EdgePolicyContractOut:
    actor = audit_actor_from_principal(principal)
    version = settings.edge_policy_version
    try:
        policy = save_edge_policy_source(version, req.yaml_text)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="edge policy contract update failed",
        ) from exc

    with db_session() as session:
        record_admin_event(
            session,
            actor_email=actor.email,
            actor_subject=actor.subject,
            action="edge_policy_contract.update",
            target_type="edge_policy_contract",
            target_device_id=None,
            details={
                "policy_version": policy.version,
                "policy_sha256": policy.sha256,
                "actor_role": actor.role,
                "actor_source": actor.source,
            },
            request_id=get_request_id(),
        )
    return _edge_policy_contract_out(policy)


@router.post("/devices", response_model=DeviceOut)
def create_device(req: AdminDeviceCreate, principal: Principal = Depends(require_admin_role)) -> DeviceOut:
    actor = audit_actor_from_principal(principal)
    with db_session() as session:
        existing = session.query(Device).filter(Device.device_id == req.device_id).one_or_none()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device already exists")

        d = Device(
            device_id=req.device_id,
            display_name=req.display_name,
            token_hash=hash_token(req.token),
            token_fingerprint=token_fingerprint(req.token),
            heartbeat_interval_s=req.heartbeat_interval_s,
            offline_after_s=req.offline_after_s,
            enabled=True,
        )
        session.add(d)
        record_admin_event(
            session,
            actor_email=actor.email,
            actor_subject=actor.subject,
            action="device.create",
            target_type="device",
            target_device_id=d.device_id,
            details={
                "enabled": True,
                "heartbeat_interval_s": req.heartbeat_interval_s,
                "offline_after_s": req.offline_after_s,
                "actor_role": actor.role,
                "actor_source": actor.source,
            },
            request_id=get_request_id(),
        )

        now = datetime.now(timezone.utc)
        status_str, seconds = compute_status(d, now)
        return DeviceOut(
            device_id=d.device_id,
            display_name=d.display_name,
            heartbeat_interval_s=d.heartbeat_interval_s,
            offline_after_s=d.offline_after_s,
            last_seen_at=d.last_seen_at,
            enabled=d.enabled,
            status=status_str,
            seconds_since_last_seen=seconds,
        )


@router.patch("/devices/{device_id}", response_model=DeviceOut)
def update_device(
    device_id: str, req: AdminDeviceUpdate, principal: Principal = Depends(require_admin_role)
) -> DeviceOut:
    actor = audit_actor_from_principal(principal)
    with db_session() as session:
        d = session.query(Device).filter(Device.device_id == device_id).one_or_none()
        if not d:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

        changed_fields: list[str] = []
        if req.display_name is not None:
            d.display_name = req.display_name
            changed_fields.append("display_name")
        if req.token is not None:
            d.token_fingerprint = token_fingerprint(req.token)
            d.token_hash = hash_token(req.token)
            changed_fields.append("token")
        if req.heartbeat_interval_s is not None:
            d.heartbeat_interval_s = req.heartbeat_interval_s
            changed_fields.append("heartbeat_interval_s")
        if req.offline_after_s is not None:
            d.offline_after_s = req.offline_after_s
            changed_fields.append("offline_after_s")
        if req.enabled is not None:
            d.enabled = req.enabled
            changed_fields.append("enabled")

        if changed_fields:
            record_admin_event(
                session,
                actor_email=actor.email,
                actor_subject=actor.subject,
                action="device.update",
                target_type="device",
                target_device_id=d.device_id,
                details={
                    "changed_fields": changed_fields,
                    "actor_role": actor.role,
                    "actor_source": actor.source,
                },
                request_id=get_request_id(),
            )

        now = datetime.now(timezone.utc)
        status_str, seconds = compute_status(d, now)
        return DeviceOut(
            device_id=d.device_id,
            display_name=d.display_name,
            heartbeat_interval_s=d.heartbeat_interval_s,
            offline_after_s=d.offline_after_s,
            last_seen_at=d.last_seen_at,
            enabled=d.enabled,
            status=status_str,
            seconds_since_last_seen=seconds,
        )


@router.get("/devices", response_model=List[DeviceOut])
def list_devices_admin() -> List[DeviceOut]:
    now = datetime.now(timezone.utc)
    with db_session() as session:
        devices = session.query(Device).order_by(Device.device_id.asc()).all()
        out: List[DeviceOut] = []
        for d in devices:
            status_str, seconds = compute_status(d, now)
            out.append(
                DeviceOut(
                    device_id=d.device_id,
                    display_name=d.display_name,
                    heartbeat_interval_s=d.heartbeat_interval_s,
                    offline_after_s=d.offline_after_s,
                    last_seen_at=d.last_seen_at,
                    enabled=d.enabled,
                    status=status_str,
                    seconds_since_last_seen=seconds,
                )
            )
        return out


@router.get("/events", response_model=List[AdminEventOut])
def list_admin_events(limit: int = Query(default=200, ge=1, le=2000)) -> List[AdminEventOut]:
    with db_session() as session:
        rows = session.query(AdminEvent).order_by(desc(AdminEvent.created_at)).limit(limit).all()
        return [
            AdminEventOut(
                id=row.id,
                actor_email=row.actor_email,
                actor_subject=row.actor_subject,
                action=row.action,
                target_type=row.target_type,
                target_device_id=row.target_device_id,
                details=dict(row.details or {}),
                request_id=row.request_id,
                created_at=row.created_at,
            )
            for row in rows
        ]


@router.get("/ingestions", response_model=List[IngestionBatchOut])
def list_ingestions_admin(
    device_id: Optional[str] = Query(default=None, description="Optional device_id filter"),
    limit: int = Query(default=200, ge=1, le=2000),
) -> List[IngestionBatchOut]:
    """List recent ingestion batches.

    This endpoint is designed for ops/debugging:
    - contract version/hash visibility
    - duplicate counts
    - additive drift (unknown metric keys)
    """

    with db_session() as session:
        q = session.query(IngestionBatch)
        if device_id:
            q = q.filter(IngestionBatch.device_id == device_id)
        q = q.order_by(IngestionBatch.received_at.desc()).limit(limit)
        rows = q.all()

        return [
            IngestionBatchOut(
                id=r.id,
                device_id=r.device_id,
                received_at=r.received_at,
                contract_version=r.contract_version,
                contract_hash=r.contract_hash,
                points_submitted=r.points_submitted,
                points_accepted=r.points_accepted,
                duplicates=r.duplicates,
                points_quarantined=r.points_quarantined,
                client_ts_min=r.client_ts_min,
                client_ts_max=r.client_ts_max,
                unknown_metric_keys=list(r.unknown_metric_keys or []),
                type_mismatch_keys=list(r.type_mismatch_keys or []),
                drift_summary=dict(r.drift_summary or {}),
                source=r.source,
                pipeline_mode=r.pipeline_mode,
                processing_status=r.processing_status,
            )
            for r in rows
        ]


@router.get(
    "/drift-events",
    response_model=List[DriftEventOut],
)
def list_drift_events_admin(
    device_id: Optional[str] = Query(default=None, description="Optional device_id filter"),
    limit: int = Query(default=200, ge=1, le=2000),
) -> List[DriftEventOut]:
    with db_session() as session:
        q = session.query(DriftEvent)
        if device_id:
            q = q.filter(DriftEvent.device_id == device_id)
        rows = q.order_by(desc(DriftEvent.created_at)).limit(limit).all()
        return [
            DriftEventOut(
                id=row.id,
                batch_id=row.batch_id,
                device_id=row.device_id,
                event_type=row.event_type,
                action=row.action,
                details=dict(row.details or {}),
                created_at=row.created_at,
            )
            for row in rows
        ]


@router.get(
    "/notifications",
    response_model=List[NotificationEventOut],
)
def list_notifications_admin(
    device_id: Optional[str] = Query(default=None, description="Optional device_id filter"),
    limit: int = Query(default=200, ge=1, le=2000),
) -> List[NotificationEventOut]:
    with db_session() as session:
        q = session.query(NotificationEvent)
        if device_id:
            q = q.filter(NotificationEvent.device_id == device_id)
        rows = q.order_by(desc(NotificationEvent.created_at)).limit(limit).all()
        return [
            NotificationEventOut(
                id=row.id,
                alert_id=row.alert_id,
                device_id=row.device_id,
                alert_type=row.alert_type,
                channel=row.channel,
                decision=row.decision,
                delivered=row.delivered,
                reason=row.reason,
                created_at=row.created_at,
            )
            for row in rows
        ]


@router.get(
    "/notification-destinations",
    response_model=List[NotificationDestinationOut],
)
def list_notification_destinations_admin() -> List[NotificationDestinationOut]:
    with db_session() as session:
        rows = session.query(NotificationDestination).order_by(desc(NotificationDestination.created_at)).all()
        return [_notification_destination_out(row) for row in rows]


@router.post(
    "/notification-destinations",
    response_model=NotificationDestinationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_notification_destination_admin(
    req: NotificationDestinationCreate, principal: Principal = Depends(require_admin_role)
) -> NotificationDestinationOut:
    actor = audit_actor_from_principal(principal)
    with db_session() as session:
        name = req.name.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name is required")

        existing = (
            session.query(NotificationDestination).filter(NotificationDestination.name == name).one_or_none()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Notification destination name already exists",
            )

        webhook_url = _normalize_webhook_url(req.webhook_url)
        row = NotificationDestination(
            name=name,
            channel=req.channel,
            kind=req.kind,
            webhook_url=webhook_url,
            enabled=req.enabled,
        )
        session.add(row)
        session.flush()

        record_admin_event(
            session,
            actor_email=actor.email,
            actor_subject=actor.subject,
            action="notification_destination.create",
            target_type="notification_destination",
            target_device_id=None,
            details={
                "destination_id": row.id,
                "name": row.name,
                "channel": row.channel,
                "kind": row.kind,
                "enabled": row.enabled,
                "destination_fingerprint": destination_fingerprint(row.webhook_url),
                "actor_role": actor.role,
                "actor_source": actor.source,
            },
            request_id=get_request_id(),
        )
        return _notification_destination_out(row)


@router.patch(
    "/notification-destinations/{destination_id}",
    response_model=NotificationDestinationOut,
)
def update_notification_destination_admin(
    destination_id: str,
    req: NotificationDestinationUpdate,
    principal: Principal = Depends(require_admin_role),
) -> NotificationDestinationOut:
    actor = audit_actor_from_principal(principal)
    with db_session() as session:
        row = (
            session.query(NotificationDestination)
            .filter(NotificationDestination.id == destination_id)
            .one_or_none()
        )
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Notification destination not found"
            )

        changed_fields: list[str] = []

        if req.name is not None:
            name = req.name.strip()
            if not name:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name is required")
            conflict = (
                session.query(NotificationDestination.id)
                .filter(
                    NotificationDestination.name == name,
                    NotificationDestination.id != row.id,
                )
                .first()
            )
            if conflict is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Notification destination name already exists",
                )
            row.name = name
            changed_fields.append("name")

        if req.channel is not None:
            row.channel = req.channel
            changed_fields.append("channel")

        if req.kind is not None:
            row.kind = req.kind
            changed_fields.append("kind")

        if req.webhook_url is not None:
            row.webhook_url = _normalize_webhook_url(req.webhook_url)
            changed_fields.append("webhook_url")

        if req.enabled is not None:
            row.enabled = req.enabled
            changed_fields.append("enabled")

        if changed_fields:
            row.updated_at = datetime.now(timezone.utc)
            record_admin_event(
                session,
                actor_email=actor.email,
                actor_subject=actor.subject,
                action="notification_destination.update",
                target_type="notification_destination",
                target_device_id=None,
                details={
                    "destination_id": row.id,
                    "changed_fields": changed_fields,
                    "name": row.name,
                    "channel": row.channel,
                    "kind": row.kind,
                    "enabled": row.enabled,
                    "destination_fingerprint": destination_fingerprint(row.webhook_url),
                    "actor_role": actor.role,
                    "actor_source": actor.source,
                },
                request_id=get_request_id(),
            )

        return _notification_destination_out(row)


@router.delete(
    "/notification-destinations/{destination_id}",
    response_model=NotificationDestinationOut,
)
def delete_notification_destination_admin(
    destination_id: str,
    principal: Principal = Depends(require_admin_role),
) -> NotificationDestinationOut:
    actor = audit_actor_from_principal(principal)
    with db_session() as session:
        row = (
            session.query(NotificationDestination)
            .filter(NotificationDestination.id == destination_id)
            .one_or_none()
        )
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Notification destination not found"
            )

        out = _notification_destination_out(row)

        record_admin_event(
            session,
            actor_email=actor.email,
            actor_subject=actor.subject,
            action="notification_destination.delete",
            target_type="notification_destination",
            target_device_id=None,
            details={
                "destination_id": row.id,
                "name": row.name,
                "channel": row.channel,
                "kind": row.kind,
                "enabled": row.enabled,
                "destination_fingerprint": destination_fingerprint(row.webhook_url),
                "actor_role": actor.role,
                "actor_source": actor.source,
            },
            request_id=get_request_id(),
        )
        session.delete(row)
        return out


@router.get(
    "/exports",
    response_model=List[ExportBatchOut],
)
def list_exports_admin(
    status_filter: Optional[str] = Query(default=None, description="Optional status filter"),
    limit: int = Query(default=200, ge=1, le=2000),
) -> List[ExportBatchOut]:
    with db_session() as session:
        q = session.query(ExportBatch)
        if status_filter:
            q = q.filter(ExportBatch.status == status_filter)
        rows = q.order_by(desc(ExportBatch.started_at)).limit(limit).all()
        return [
            ExportBatchOut(
                id=row.id,
                started_at=row.started_at,
                finished_at=row.finished_at,
                watermark_from=row.watermark_from,
                watermark_to=row.watermark_to,
                contract_version=row.contract_version,
                contract_hash=row.contract_hash,
                gcs_uri=row.gcs_uri,
                row_count=row.row_count,
                status=row.status,
                error_message=row.error_message,
            )
            for row in rows
        ]
