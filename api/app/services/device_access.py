from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..auth.principal import Principal
from ..config import settings
from ..models import DeviceAccessGrant


_ACCESS_ROLE_ORDER: dict[str, int] = {
    "viewer": 0,
    "operator": 1,
    "owner": 2,
}


def normalize_access_role(value: str) -> str:
    role = (value or "").strip().lower()
    if role not in _ACCESS_ROLE_ORDER:
        raise ValueError("access_role must be one of: viewer, operator, owner")
    return role


def normalize_principal_email(value: str) -> str:
    email = (value or "").strip().lower()
    if "@" not in email:
        raise ValueError("principal_email must be a valid email")
    return email


def _allowed_access_roles(min_access_role: str) -> tuple[str, ...]:
    min_role = normalize_access_role(min_access_role)
    min_index = _ACCESS_ROLE_ORDER[min_role]
    return tuple(role for role, index in _ACCESS_ROLE_ORDER.items() if index >= min_index)


def accessible_device_ids_subquery(
    session: Session,
    *,
    principal: Principal,
    min_access_role: str = "viewer",
):
    if not settings.authz_enabled or principal.role == "admin":
        return None

    allowed_roles = _allowed_access_roles(min_access_role)
    return session.query(DeviceAccessGrant.device_id).filter(
        DeviceAccessGrant.principal_email == principal.email.lower(),
        DeviceAccessGrant.access_role.in_(allowed_roles),
    )


def ensure_device_access(
    session: Session,
    *,
    principal: Principal,
    device_id: str,
    min_access_role: str = "viewer",
) -> None:
    if not settings.authz_enabled or principal.role == "admin":
        return

    row = (
        session.query(DeviceAccessGrant.access_role)
        .filter(
            DeviceAccessGrant.device_id == device_id,
            DeviceAccessGrant.principal_email == principal.email.lower(),
        )
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="device access denied")

    granted = normalize_access_role(row[0])
    allowed_roles = _allowed_access_roles(min_access_role)
    if granted not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="device access denied")
