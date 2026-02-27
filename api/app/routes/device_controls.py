from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth.principal import Principal
from ..auth.rbac import require_viewer_role
from ..config import settings
from ..db import db_session
from ..edge_policy import load_edge_policy
from ..models import Device
from ..schemas import (
    DeviceAlertsControlUpdateIn,
    DeviceControlsOut,
    DeviceOperationControlUpdateIn,
    OperationMode,
)
from ..services.device_access import ensure_device_access
from ..services.device_commands import (
    enqueue_device_control_command,
    get_pending_device_command,
    pending_command_summary,
)


router = APIRouter(prefix="/api/v1", tags=["device-controls"])


def _normalized_operation_mode(value: object) -> OperationMode:
    mode = str(value or "active").strip().lower()
    if mode == "sleep":
        return "sleep"
    if mode == "disabled":
        return "disabled"
    return "active"


def _as_controls_out(
    device: Device,
    *,
    disable_requires_manual_restart: bool,
    pending_command_count: int,
    latest_pending_command_expires_at: datetime | None,
    latest_pending_operation_mode: OperationMode | None = None,
    latest_pending_shutdown_requested: bool = False,
    latest_pending_shutdown_grace_s: int | None = None,
) -> DeviceControlsOut:
    return DeviceControlsOut(
        device_id=device.device_id,
        operation_mode=_normalized_operation_mode(getattr(device, "operation_mode", "active")),
        sleep_poll_interval_s=int(getattr(device, "sleep_poll_interval_s", 7 * 24 * 3600) or (7 * 24 * 3600)),
        disable_requires_manual_restart=disable_requires_manual_restart,
        alerts_muted_until=getattr(device, "alerts_muted_until", None),
        alerts_muted_reason=getattr(device, "alerts_muted_reason", None),
        pending_command_count=pending_command_count,
        latest_pending_command_expires_at=latest_pending_command_expires_at,
        latest_pending_operation_mode=latest_pending_operation_mode,
        latest_pending_shutdown_requested=latest_pending_shutdown_requested,
        latest_pending_shutdown_grace_s=latest_pending_shutdown_grace_s,
    )


def _normalize_opt_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _pending_payload_summary(command) -> tuple[OperationMode | None, bool, int | None]:
    if command is None:
        return None, False, None
    payload = command.command_payload if isinstance(command.command_payload, dict) else {}
    operation_mode = _normalized_operation_mode(payload.get("operation_mode"))
    raw_shutdown_requested = payload.get("shutdown_requested")
    if isinstance(raw_shutdown_requested, bool):
        shutdown_requested = raw_shutdown_requested
    elif isinstance(raw_shutdown_requested, str):
        shutdown_requested = raw_shutdown_requested.strip().lower() in {"1", "true", "yes", "on"}
    else:
        shutdown_requested = False
    shutdown_grace_s = None
    if payload.get("shutdown_grace_s") is not None:
        try:
            shutdown_grace_s = max(1, min(3600, int(payload["shutdown_grace_s"])))
        except (TypeError, ValueError):
            shutdown_grace_s = 30
    return operation_mode, shutdown_requested, shutdown_grace_s


@router.get("/devices/{device_id}/controls", response_model=DeviceControlsOut)
def get_device_controls(
    device_id: str,
    principal: Principal = Depends(require_viewer_role),
) -> DeviceControlsOut:
    policy = load_edge_policy(settings.edge_policy_version)
    with db_session() as session:
        device = session.query(Device).filter(Device.device_id == device_id).one_or_none()
        if device is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
        ensure_device_access(session, principal=principal, device_id=device_id, min_access_role="viewer")
        pending_count, latest_pending_expires = pending_command_summary(session, device_id=device_id)
        pending_command = get_pending_device_command(session, device_id=device_id)
        latest_pending_operation_mode, latest_pending_shutdown_requested, latest_pending_shutdown_grace_s = (
            _pending_payload_summary(pending_command)
        )
        return _as_controls_out(
            device,
            disable_requires_manual_restart=policy.operation_defaults.disable_requires_manual_restart,
            pending_command_count=pending_count,
            latest_pending_command_expires_at=latest_pending_expires,
            latest_pending_operation_mode=latest_pending_operation_mode,
            latest_pending_shutdown_requested=latest_pending_shutdown_requested,
            latest_pending_shutdown_grace_s=latest_pending_shutdown_grace_s,
        )


@router.patch("/devices/{device_id}/controls/operation", response_model=DeviceControlsOut)
def update_device_operation_controls(
    device_id: str,
    req: DeviceOperationControlUpdateIn,
    principal: Principal = Depends(require_viewer_role),
) -> DeviceControlsOut:
    policy = load_edge_policy(settings.edge_policy_version)
    with db_session() as session:
        device = session.query(Device).filter(Device.device_id == device_id).one_or_none()
        if device is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
        ensure_device_access(session, principal=principal, device_id=device_id, min_access_role="operator")

        device.operation_mode = req.operation_mode
        if req.sleep_poll_interval_s is not None:
            device.sleep_poll_interval_s = req.sleep_poll_interval_s
        enqueue_device_control_command(
            session,
            device=device,
            ttl_s=policy.operation_defaults.control_command_ttl_s,
        )
        pending_count, latest_pending_expires = pending_command_summary(session, device_id=device_id)
        pending_command = get_pending_device_command(session, device_id=device_id)
        latest_pending_operation_mode, latest_pending_shutdown_requested, latest_pending_shutdown_grace_s = (
            _pending_payload_summary(pending_command)
        )
        return _as_controls_out(
            device,
            disable_requires_manual_restart=policy.operation_defaults.disable_requires_manual_restart,
            pending_command_count=pending_count,
            latest_pending_command_expires_at=latest_pending_expires,
            latest_pending_operation_mode=latest_pending_operation_mode,
            latest_pending_shutdown_requested=latest_pending_shutdown_requested,
            latest_pending_shutdown_grace_s=latest_pending_shutdown_grace_s,
        )


@router.patch("/devices/{device_id}/controls/alerts", response_model=DeviceControlsOut)
def update_device_alert_controls(
    device_id: str,
    req: DeviceAlertsControlUpdateIn,
    principal: Principal = Depends(require_viewer_role),
) -> DeviceControlsOut:
    policy = load_edge_policy(settings.edge_policy_version)
    with db_session() as session:
        device = session.query(Device).filter(Device.device_id == device_id).one_or_none()
        if device is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
        ensure_device_access(session, principal=principal, device_id=device_id, min_access_role="operator")

        muted_until = _normalize_opt_utc(req.alerts_muted_until)
        if muted_until is None:
            device.alerts_muted_until = None
            device.alerts_muted_reason = None
        else:
            device.alerts_muted_until = muted_until
            reason = (req.alerts_muted_reason or "").strip()
            device.alerts_muted_reason = reason or None

        enqueue_device_control_command(
            session,
            device=device,
            ttl_s=policy.operation_defaults.control_command_ttl_s,
        )
        pending_count, latest_pending_expires = pending_command_summary(session, device_id=device_id)
        pending_command = get_pending_device_command(session, device_id=device_id)
        latest_pending_operation_mode, latest_pending_shutdown_requested, latest_pending_shutdown_grace_s = (
            _pending_payload_summary(pending_command)
        )
        return _as_controls_out(
            device,
            disable_requires_manual_restart=policy.operation_defaults.disable_requires_manual_restart,
            pending_command_count=pending_count,
            latest_pending_command_expires_at=latest_pending_expires,
            latest_pending_operation_mode=latest_pending_operation_mode,
            latest_pending_shutdown_requested=latest_pending_shutdown_requested,
            latest_pending_shutdown_grace_s=latest_pending_shutdown_grace_s,
        )
