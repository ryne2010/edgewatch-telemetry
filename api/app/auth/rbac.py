from __future__ import annotations

from fastapi import Depends, HTTPException, status

from ..config import settings
from .principal import Principal, Role, require_admin_principal, require_request_principal


_ROLE_ORDER: dict[Role, int] = {
    "viewer": 0,
    "operator": 1,
    "admin": 2,
}


def _enforce_min_role(principal: Principal, *, min_role: Role) -> Principal:
    # Backward-compatible path for existing deployments.
    if not settings.authz_enabled:
        return principal
    if _ROLE_ORDER[principal.role] < _ROLE_ORDER[min_role]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{min_role} role required",
        )
    return principal


def require_viewer_role(principal: Principal = Depends(require_request_principal)) -> Principal:
    return _enforce_min_role(principal, min_role="viewer")


def require_operator_role(principal: Principal = Depends(require_request_principal)) -> Principal:
    return _enforce_min_role(principal, min_role="operator")


def require_admin_role(principal: Principal = Depends(require_admin_principal)) -> Principal:
    return _enforce_min_role(principal, min_role="admin")
