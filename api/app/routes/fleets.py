from __future__ import annotations

from datetime import datetime, timezone
from typing import List, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func

from ..auth.audit import audit_actor_from_principal
from ..auth.principal import Principal
from ..auth.rbac import require_admin_role, require_viewer_role
from ..db import db_session
from ..models import Device, Fleet, FleetAccessGrant, FleetDeviceMembership
from ..observability import get_request_id
from ..schemas import (
    DeepSleepBackend,
    DeviceAccessRole,
    DeviceOut,
    FleetAccessGrantOut,
    FleetAccessGrantPutIn,
    FleetCreateIn,
    FleetMembershipOut,
    FleetOut,
    FleetUpdateIn,
    OperationMode,
    RuntimePowerMode,
)
from ..services.admin_audit import record_admin_event
from ..services.device_access import (
    accessible_device_ids_subquery,
    normalize_access_role,
    normalize_principal_email,
)
from ..services.device_identity import safe_display_name
from ..services.monitor import compute_status


admin_router = APIRouter(
    prefix="/api/v1/admin", tags=["fleets-admin"], dependencies=[Depends(require_admin_role)]
)
read_router = APIRouter(prefix="/api/v1", tags=["fleets"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fleet_out(session, row: Fleet) -> FleetOut:
    count = (
        session.query(func.count(FleetDeviceMembership.device_id))
        .filter(FleetDeviceMembership.fleet_id == row.id)
        .scalar()
        or 0
    )
    return FleetOut(
        id=row.id,
        name=row.name,
        description=row.description,
        default_ota_channel=row.default_ota_channel,
        created_at=row.created_at,
        updated_at=row.updated_at,
        device_count=int(count),
    )


def _fleet_access_out(row: FleetAccessGrant) -> FleetAccessGrantOut:
    access_role: DeviceAccessRole = "viewer"
    if row.access_role == "operator":
        access_role = "operator"
    elif row.access_role == "owner":
        access_role = "owner"
    return FleetAccessGrantOut(
        fleet_id=row.fleet_id,
        principal_email=row.principal_email,
        access_role=access_role,
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
        operation_mode=cast(OperationMode, str(getattr(row, "operation_mode", "active") or "active")),
        sleep_poll_interval_s=int(getattr(row, "sleep_poll_interval_s", 7 * 24 * 3600) or (7 * 24 * 3600)),
        runtime_power_mode=cast(
            RuntimePowerMode, str(getattr(row, "runtime_power_mode", "continuous") or "continuous")
        ),
        deep_sleep_backend=cast(DeepSleepBackend, str(getattr(row, "deep_sleep_backend", "auto") or "auto")),
        alerts_muted_until=getattr(row, "alerts_muted_until", None),
        alerts_muted_reason=getattr(row, "alerts_muted_reason", None),
        ota_channel=str(getattr(row, "ota_channel", "stable") or "stable"),
        ota_updates_enabled=bool(getattr(row, "ota_updates_enabled", True)),
        ota_busy_reason=getattr(row, "ota_busy_reason", None),
        ota_is_development=bool(getattr(row, "ota_is_development", False)),
        ota_locked_manifest_id=getattr(row, "ota_locked_manifest_id", None),
        status=status_str,
        seconds_since_last_seen=seconds,
    )


@admin_router.post("/fleets", response_model=FleetOut, status_code=status.HTTP_201_CREATED)
def create_fleet(req: FleetCreateIn, principal: Principal = Depends(require_admin_role)) -> FleetOut:
    actor = audit_actor_from_principal(principal)
    with db_session() as session:
        existing = session.query(Fleet).filter(Fleet.name == req.name.strip()).one_or_none()
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Fleet already exists")
        row = Fleet(
            name=req.name.strip(),
            description=req.description.strip()
            if isinstance(req.description, str) and req.description.strip()
            else None,
            default_ota_channel=req.default_ota_channel.strip(),
        )
        session.add(row)
        session.flush()
        record_admin_event(
            session,
            actor_email=actor.email,
            actor_subject=actor.subject,
            action="fleet.create",
            target_type="fleet",
            target_device_id=None,
            details={"fleet_id": row.id, "name": row.name},
            request_id=get_request_id(),
        )
        return _fleet_out(session, row)


@admin_router.get("/fleets", response_model=List[FleetOut])
def list_fleets_admin() -> List[FleetOut]:
    with db_session() as session:
        rows = session.query(Fleet).order_by(Fleet.name.asc()).all()
        return [_fleet_out(session, row) for row in rows]


@admin_router.patch("/fleets/{fleet_id}", response_model=FleetOut)
def update_fleet(
    fleet_id: str, req: FleetUpdateIn, principal: Principal = Depends(require_admin_role)
) -> FleetOut:
    actor = audit_actor_from_principal(principal)
    with db_session() as session:
        row = session.query(Fleet).filter(Fleet.id == fleet_id).one_or_none()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fleet not found")
        changed_fields: list[str] = []
        if req.description is not None:
            row.description = req.description
            changed_fields.append("description")
        if req.default_ota_channel is not None:
            row.default_ota_channel = req.default_ota_channel.strip()
            changed_fields.append("default_ota_channel")
        row.updated_at = _utcnow()
        if changed_fields:
            record_admin_event(
                session,
                actor_email=actor.email,
                actor_subject=actor.subject,
                action="fleet.update",
                target_type="fleet",
                target_device_id=None,
                details={"fleet_id": row.id, "changed_fields": changed_fields},
                request_id=get_request_id(),
            )
        return _fleet_out(session, row)


@admin_router.put("/fleets/{fleet_id}/devices/{device_id}", response_model=FleetMembershipOut)
def add_device_to_fleet(
    fleet_id: str, device_id: str, principal: Principal = Depends(require_admin_role)
) -> FleetMembershipOut:
    actor = audit_actor_from_principal(principal)
    with db_session() as session:
        fleet = session.query(Fleet).filter(Fleet.id == fleet_id).one_or_none()
        if fleet is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fleet not found")
        device = session.query(Device).filter(Device.device_id == device_id).one_or_none()
        if device is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
        row = (
            session.query(FleetDeviceMembership)
            .filter(
                FleetDeviceMembership.fleet_id == fleet_id,
                FleetDeviceMembership.device_id == device_id,
            )
            .one_or_none()
        )
        if row is None:
            row = FleetDeviceMembership(fleet_id=fleet_id, device_id=device_id)
            session.add(row)
        device.ota_channel = fleet.default_ota_channel
        record_admin_event(
            session,
            actor_email=actor.email,
            actor_subject=actor.subject,
            action="fleet.membership.add",
            target_type="fleet_membership",
            target_device_id=device.device_id,
            details={"fleet_id": fleet.id, "device_id": device.device_id},
            request_id=get_request_id(),
        )
        session.flush()
        return FleetMembershipOut(fleet_id=row.fleet_id, device_id=row.device_id, added_at=row.added_at)


@admin_router.delete("/fleets/{fleet_id}/devices/{device_id}", response_model=FleetMembershipOut)
def remove_device_from_fleet(
    fleet_id: str, device_id: str, principal: Principal = Depends(require_admin_role)
) -> FleetMembershipOut:
    actor = audit_actor_from_principal(principal)
    with db_session() as session:
        row = (
            session.query(FleetDeviceMembership)
            .filter(
                FleetDeviceMembership.fleet_id == fleet_id,
                FleetDeviceMembership.device_id == device_id,
            )
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fleet membership not found")
        out = FleetMembershipOut(fleet_id=row.fleet_id, device_id=row.device_id, added_at=row.added_at)
        session.delete(row)
        record_admin_event(
            session,
            actor_email=actor.email,
            actor_subject=actor.subject,
            action="fleet.membership.remove",
            target_type="fleet_membership",
            target_device_id=device_id,
            details={"fleet_id": fleet_id, "device_id": device_id},
            request_id=get_request_id(),
        )
        return out


@admin_router.get("/fleets/{fleet_id}/access", response_model=List[FleetAccessGrantOut])
def list_fleet_access_admin(fleet_id: str) -> List[FleetAccessGrantOut]:
    with db_session() as session:
        rows = (
            session.query(FleetAccessGrant)
            .filter(FleetAccessGrant.fleet_id == fleet_id)
            .order_by(FleetAccessGrant.principal_email.asc())
            .all()
        )
        return [_fleet_access_out(row) for row in rows]


@admin_router.put("/fleets/{fleet_id}/access/{principal_email}", response_model=FleetAccessGrantOut)
def put_fleet_access_admin(
    fleet_id: str,
    principal_email: str,
    req: FleetAccessGrantPutIn,
    principal: Principal = Depends(require_admin_role),
) -> FleetAccessGrantOut:
    actor = audit_actor_from_principal(principal)
    normalized_email = normalize_principal_email(principal_email)
    access_role = normalize_access_role(req.access_role)
    with db_session() as session:
        fleet = session.query(Fleet).filter(Fleet.id == fleet_id).one_or_none()
        if fleet is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fleet not found")
        row = (
            session.query(FleetAccessGrant)
            .filter(
                FleetAccessGrant.fleet_id == fleet_id,
                FleetAccessGrant.principal_email == normalized_email,
            )
            .one_or_none()
        )
        if row is None:
            row = FleetAccessGrant(
                fleet_id=fleet_id, principal_email=normalized_email, access_role=access_role
            )
            session.add(row)
        else:
            row.access_role = access_role
            row.updated_at = _utcnow()
        record_admin_event(
            session,
            actor_email=actor.email,
            actor_subject=actor.subject,
            action="fleet.access.put",
            target_type="fleet_access_grant",
            target_device_id=None,
            details={"fleet_id": fleet_id, "principal_email": normalized_email, "access_role": access_role},
            request_id=get_request_id(),
        )
        session.flush()
        return _fleet_access_out(row)


@admin_router.delete("/fleets/{fleet_id}/access/{principal_email}", response_model=FleetAccessGrantOut)
def delete_fleet_access_admin(
    fleet_id: str,
    principal_email: str,
    principal: Principal = Depends(require_admin_role),
) -> FleetAccessGrantOut:
    actor = audit_actor_from_principal(principal)
    normalized_email = normalize_principal_email(principal_email)
    with db_session() as session:
        row = (
            session.query(FleetAccessGrant)
            .filter(
                FleetAccessGrant.fleet_id == fleet_id,
                FleetAccessGrant.principal_email == normalized_email,
            )
            .one_or_none()
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fleet access grant not found")
        out = _fleet_access_out(row)
        session.delete(row)
        record_admin_event(
            session,
            actor_email=actor.email,
            actor_subject=actor.subject,
            action="fleet.access.delete",
            target_type="fleet_access_grant",
            target_device_id=None,
            details={"fleet_id": fleet_id, "principal_email": normalized_email},
            request_id=get_request_id(),
        )
        return out


@read_router.get("/fleets", response_model=List[FleetOut])
def list_accessible_fleets(principal: Principal = Depends(require_viewer_role)) -> List[FleetOut]:
    with db_session() as session:
        if principal.role == "admin":
            rows = session.query(Fleet).order_by(Fleet.name.asc()).all()
        else:
            rows = (
                session.query(Fleet)
                .join(FleetAccessGrant, FleetAccessGrant.fleet_id == Fleet.id)
                .filter(FleetAccessGrant.principal_email == principal.email.lower())
                .order_by(Fleet.name.asc())
                .all()
            )
        return [_fleet_out(session, row) for row in rows]


@read_router.get("/fleets/{fleet_id}/devices", response_model=List[DeviceOut])
def list_fleet_devices(fleet_id: str, principal: Principal = Depends(require_viewer_role)) -> List[DeviceOut]:
    now = _utcnow()
    with db_session() as session:
        q = (
            session.query(Device)
            .join(FleetDeviceMembership, FleetDeviceMembership.device_id == Device.device_id)
            .filter(FleetDeviceMembership.fleet_id == fleet_id)
        )
        accessible_ids = accessible_device_ids_subquery(
            session, principal=principal, min_access_role="viewer"
        )
        if accessible_ids is not None:
            q = q.filter(Device.device_id.in_(accessible_ids))
        rows = q.order_by(Device.device_id.asc()).all()
        return [_device_out(row, now=now) for row in rows]
