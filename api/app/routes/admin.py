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
from ..edge_policy import EdgePolicy, load_edge_policy, load_edge_policy_source, save_edge_policy_source
from ..models import (
    AdminEvent,
    Device,
    DeviceAccessGrant,
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
    AdminDeviceShutdownIn,
    AdminDeviceUpdate,
    DeviceAccessRole,
    DeviceAccessGrantOut,
    DeviceAccessGrantPutIn,
    DeviceControlsOut,
    DeviceOut,
    DriftEventOut,
    EdgePolicyAlertThresholdsOut,
    EdgePolicyContractOut,
    EdgePolicyContractSourceOut,
    EdgePolicyContractUpdateIn,
    EdgePolicyCostCapsOut,
    EdgePolicyOperationDefaultsOut,
    EdgePolicyPowerManagementOut,
    EdgePolicyReportingOut,
    ExportBatchOut,
    IngestionBatchOut,
    OperationMode,
    NotificationDestinationCreate,
    NotificationDestinationOut,
    NotificationDestinationUpdate,
    NotificationEventOut,
)
from ..security import hash_token, token_fingerprint
from ..services.admin_audit import record_admin_event
from ..services.device_access import normalize_access_role, normalize_principal_email
from ..services.device_commands import enqueue_device_shutdown_command, pending_command_summary
from ..services.device_identity import safe_display_name
from ..services.monitor import compute_status
from ..services.notifications import destination_fingerprint, mask_webhook_url

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin_role)])


def _normalized_operation_mode(value: object) -> OperationMode:
    mode = str(value or "active").strip().lower()
    if mode == "sleep":
        return "sleep"
    if mode == "disabled":
        return "disabled"
    return "active"


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


def _device_out(row: Device, *, now: datetime) -> DeviceOut:
    status_str, seconds = compute_status(row, now)
    return DeviceOut(
        device_id=row.device_id,
        display_name=safe_display_name(row.device_id, row.display_name),
        heartbeat_interval_s=row.heartbeat_interval_s,
        offline_after_s=row.offline_after_s,
        last_seen_at=row.last_seen_at,
        enabled=row.enabled,
        operation_mode=_normalized_operation_mode(getattr(row, "operation_mode", "active")),
        sleep_poll_interval_s=int(getattr(row, "sleep_poll_interval_s", 7 * 24 * 3600) or (7 * 24 * 3600)),
        alerts_muted_until=getattr(row, "alerts_muted_until", None),
        alerts_muted_reason=getattr(row, "alerts_muted_reason", None),
        status=status_str,
        seconds_since_last_seen=seconds,
    )


def _device_controls_out(
    row: Device,
    *,
    disable_requires_manual_restart: bool,
    pending_command_count: int,
    latest_pending_command_expires_at: datetime | None,
    latest_pending_operation_mode: OperationMode | None = None,
    latest_pending_shutdown_requested: bool = False,
    latest_pending_shutdown_grace_s: int | None = None,
) -> DeviceControlsOut:
    return DeviceControlsOut(
        device_id=row.device_id,
        operation_mode=_normalized_operation_mode(getattr(row, "operation_mode", "active")),
        sleep_poll_interval_s=int(getattr(row, "sleep_poll_interval_s", 7 * 24 * 3600) or (7 * 24 * 3600)),
        disable_requires_manual_restart=disable_requires_manual_restart,
        alerts_muted_until=getattr(row, "alerts_muted_until", None),
        alerts_muted_reason=getattr(row, "alerts_muted_reason", None),
        pending_command_count=pending_command_count,
        latest_pending_command_expires_at=latest_pending_command_expires_at,
        latest_pending_operation_mode=latest_pending_operation_mode,
        latest_pending_shutdown_requested=latest_pending_shutdown_requested,
        latest_pending_shutdown_grace_s=latest_pending_shutdown_grace_s,
    )


def _device_access_grant_out(row: DeviceAccessGrant) -> DeviceAccessGrantOut:
    access_role: DeviceAccessRole = "viewer"
    if row.access_role == "operator":
        access_role = "operator"
    elif row.access_role == "owner":
        access_role = "owner"
    return DeviceAccessGrantOut(
        device_id=row.device_id,
        principal_email=row.principal_email,
        access_role=access_role,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _normalized_owner_emails(raw: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in raw or []:
        email = normalize_principal_email(value)
        if email in seen:
            continue
        seen.add(email)
        out.append(email)
    return out


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
            microphone_offline_db=policy.alert_thresholds.microphone_offline_db,
            microphone_offline_open_consecutive_samples=(
                policy.alert_thresholds.microphone_offline_open_consecutive_samples
            ),
            microphone_offline_resolve_consecutive_samples=(
                policy.alert_thresholds.microphone_offline_resolve_consecutive_samples
            ),
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
        power_management=EdgePolicyPowerManagementOut(
            enabled=policy.power_management.enabled,
            mode=policy.power_management.mode,
            input_warn_min_v=policy.power_management.input_warn_min_v,
            input_warn_max_v=policy.power_management.input_warn_max_v,
            input_critical_min_v=policy.power_management.input_critical_min_v,
            input_critical_max_v=policy.power_management.input_critical_max_v,
            sustainable_input_w=policy.power_management.sustainable_input_w,
            unsustainable_window_s=policy.power_management.unsustainable_window_s,
            battery_trend_window_s=policy.power_management.battery_trend_window_s,
            battery_drop_warn_v=policy.power_management.battery_drop_warn_v,
            saver_sample_interval_s=policy.power_management.saver_sample_interval_s,
            saver_heartbeat_interval_s=policy.power_management.saver_heartbeat_interval_s,
            media_disabled_in_saver=policy.power_management.media_disabled_in_saver,
        ),
        operation_defaults=EdgePolicyOperationDefaultsOut(
            default_sleep_poll_interval_s=policy.operation_defaults.default_sleep_poll_interval_s,
            disable_requires_manual_restart=policy.operation_defaults.disable_requires_manual_restart,
            admin_remote_shutdown_enabled=policy.operation_defaults.admin_remote_shutdown_enabled,
            shutdown_grace_s_default=policy.operation_defaults.shutdown_grace_s_default,
            control_command_ttl_s=policy.operation_defaults.control_command_ttl_s,
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
    display_name = safe_display_name(req.device_id, req.display_name)
    try:
        owner_emails = _normalized_owner_emails(req.owner_emails)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    with db_session() as session:
        existing = session.query(Device).filter(Device.device_id == req.device_id).one_or_none()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device already exists")

        d = Device(
            device_id=req.device_id,
            display_name=display_name,
            token_hash=hash_token(req.token),
            token_fingerprint=token_fingerprint(req.token),
            heartbeat_interval_s=req.heartbeat_interval_s,
            offline_after_s=req.offline_after_s,
            enabled=True,
        )
        session.add(d)
        for email in owner_emails:
            session.add(
                DeviceAccessGrant(
                    device_id=d.device_id,
                    principal_email=email,
                    access_role="owner",
                )
            )
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
                "owner_emails": owner_emails,
                "actor_role": actor.role,
                "actor_source": actor.source,
            },
            request_id=get_request_id(),
        )

        now = datetime.now(timezone.utc)
        return _device_out(d, now=now)


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
        return _device_out(d, now=now)


@router.get("/devices", response_model=List[DeviceOut])
def list_devices_admin() -> List[DeviceOut]:
    now = datetime.now(timezone.utc)
    with db_session() as session:
        devices = session.query(Device).order_by(Device.device_id.asc()).all()
        out: List[DeviceOut] = []
        for d in devices:
            out.append(_device_out(d, now=now))
        return out


@router.post("/devices/{device_id}/controls/shutdown", response_model=DeviceControlsOut)
def shutdown_device_admin(
    device_id: str,
    req: AdminDeviceShutdownIn,
    principal: Principal = Depends(require_admin_role),
) -> DeviceControlsOut:
    actor = audit_actor_from_principal(principal)
    reason = req.reason.strip()
    if not reason:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="reason is required")

    policy = load_edge_policy(settings.edge_policy_version)
    if not policy.operation_defaults.admin_remote_shutdown_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Admin remote shutdown is disabled by policy",
        )

    shutdown_grace_s = req.shutdown_grace_s
    if shutdown_grace_s is None:
        shutdown_grace_s = policy.operation_defaults.shutdown_grace_s_default

    with db_session() as session:
        device = session.query(Device).filter(Device.device_id == device_id).one_or_none()
        if device is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

        device.operation_mode = "disabled"
        command = enqueue_device_shutdown_command(
            session,
            device=device,
            reason=reason,
            shutdown_grace_s=shutdown_grace_s,
            ttl_s=policy.operation_defaults.control_command_ttl_s,
        )
        pending_count, latest_pending_expires = pending_command_summary(session, device_id=device_id)
        record_admin_event(
            session,
            actor_email=actor.email,
            actor_subject=actor.subject,
            action="device_control.shutdown.enqueue",
            target_type="device_control_command",
            target_device_id=device.device_id,
            details={
                "command_id": command.id,
                "shutdown_grace_s": shutdown_grace_s,
                "reason": reason,
                "actor_role": actor.role,
                "actor_source": actor.source,
            },
            request_id=get_request_id(),
        )
        return _device_controls_out(
            device,
            disable_requires_manual_restart=policy.operation_defaults.disable_requires_manual_restart,
            pending_command_count=pending_count,
            latest_pending_command_expires_at=latest_pending_expires,
            latest_pending_operation_mode="disabled",
            latest_pending_shutdown_requested=True,
            latest_pending_shutdown_grace_s=int(
                command.command_payload.get("shutdown_grace_s", shutdown_grace_s)
            ),
        )


@router.get("/devices/{device_id}/access", response_model=List[DeviceAccessGrantOut])
def list_device_access_admin(device_id: str) -> List[DeviceAccessGrantOut]:
    with db_session() as session:
        exists = session.query(Device.device_id).filter(Device.device_id == device_id).one_or_none()
        if exists is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

        rows = (
            session.query(DeviceAccessGrant)
            .filter(DeviceAccessGrant.device_id == device_id)
            .order_by(DeviceAccessGrant.principal_email.asc())
            .all()
        )
        return [_device_access_grant_out(row) for row in rows]


@router.put("/devices/{device_id}/access/{principal_email}", response_model=DeviceAccessGrantOut)
def upsert_device_access_admin(
    device_id: str,
    principal_email: str,
    req: DeviceAccessGrantPutIn,
    principal: Principal = Depends(require_admin_role),
) -> DeviceAccessGrantOut:
    actor = audit_actor_from_principal(principal)
    try:
        normalized_email = normalize_principal_email(principal_email)
        role = normalize_access_role(req.access_role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    now = datetime.now(timezone.utc)

    with db_session() as session:
        exists = session.query(Device.device_id).filter(Device.device_id == device_id).one_or_none()
        if exists is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

        row = (
            session.query(DeviceAccessGrant)
            .filter(
                DeviceAccessGrant.device_id == device_id,
                DeviceAccessGrant.principal_email == normalized_email,
            )
            .one_or_none()
        )
        created = False
        if row is None:
            row = DeviceAccessGrant(
                device_id=device_id,
                principal_email=normalized_email,
                access_role=role,
                updated_at=now,
            )
            session.add(row)
            created = True
        else:
            row.access_role = role
            row.updated_at = now

        record_admin_event(
            session,
            actor_email=actor.email,
            actor_subject=actor.subject,
            action="device_access_grant.upsert",
            target_type="device_access_grant",
            target_device_id=device_id,
            details={
                "principal_email": normalized_email,
                "access_role": role,
                "created": created,
                "actor_role": actor.role,
                "actor_source": actor.source,
            },
            request_id=get_request_id(),
        )
        session.flush()
        return _device_access_grant_out(row)


@router.delete("/devices/{device_id}/access/{principal_email}", response_model=DeviceAccessGrantOut)
def delete_device_access_admin(
    device_id: str,
    principal_email: str,
    principal: Principal = Depends(require_admin_role),
) -> DeviceAccessGrantOut:
    actor = audit_actor_from_principal(principal)
    try:
        normalized_email = normalize_principal_email(principal_email)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    with db_session() as session:
        row = (
            session.query(DeviceAccessGrant)
            .filter(
                DeviceAccessGrant.device_id == device_id,
                DeviceAccessGrant.principal_email == normalized_email,
            )
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device access grant not found")

        out = _device_access_grant_out(row)
        record_admin_event(
            session,
            actor_email=actor.email,
            actor_subject=actor.subject,
            action="device_access_grant.delete",
            target_type="device_access_grant",
            target_device_id=device_id,
            details={
                "principal_email": normalized_email,
                "access_role": row.access_role,
                "actor_role": actor.role,
                "actor_source": actor.source,
            },
            request_id=get_request_id(),
        )
        session.delete(row)
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
