from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Literal

from fastapi import Header, HTTPException, status

from ..config import settings


Role = Literal["viewer", "operator", "admin"]


@dataclass(frozen=True)
class Principal:
    email: str
    role: Role
    source: str
    subject: str | None = None


_VALID_ROLES: set[str] = {"viewer", "operator", "admin"}


def _normalize_iap_email(raw: object) -> str | None:
    if raw is None or not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    if ":" in value:
        _, value = value.split(":", 1)
    email = value.strip().lower()
    if "@" not in email:
        return None
    return email


def _normalize_iap_subject(raw: object) -> str | None:
    if raw is None or not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    if ":" in value:
        _, value = value.split(":", 1)
    subject = value.strip()
    return subject or None


def _normalize_role(raw: object, default: Role) -> Role:
    if raw is None or not isinstance(raw, str):
        return default
    value = raw.strip().lower() or default
    if value not in _VALID_ROLES:
        return default
    return value  # type: ignore[return-value]


def _principal_role_for_email(email: str) -> Role:
    if email in set(settings.authz_admin_emails):
        return "admin"
    if email in set(settings.authz_operator_emails):
        return "operator"
    if email in set(settings.authz_viewer_emails):
        return "viewer"
    return settings.authz_iap_default_role


def _principal_from_iap(
    *,
    x_goog_authenticated_user_email: object,
    x_goog_authenticated_user_id: object,
) -> Principal | None:
    email = _normalize_iap_email(x_goog_authenticated_user_email)
    if not email:
        return None
    return Principal(
        email=email,
        subject=_normalize_iap_subject(x_goog_authenticated_user_id),
        role=_principal_role_for_email(email),
        source="iap",
    )


def _principal_from_dev(
    *,
    x_edgewatch_dev_principal_email: object,
    x_edgewatch_dev_principal_role: object,
) -> Principal | None:
    if settings.app_env != "dev" or not settings.authz_dev_principal_enabled:
        return None

    header_email = (
        x_edgewatch_dev_principal_email.strip().lower()
        if isinstance(x_edgewatch_dev_principal_email, str)
        else ""
    )
    email = header_email or settings.authz_dev_principal_email
    if not email:
        return None
    role = _normalize_role(x_edgewatch_dev_principal_role, settings.authz_dev_principal_role)
    return Principal(email=email, subject=None, role=role, source="dev-principal")


def _principal_with_role(principal: Principal, role: Role, source_suffix: str) -> Principal:
    if principal.role == role and source_suffix == "":
        return principal
    suffix = f"+{source_suffix}" if source_suffix else ""
    return Principal(
        email=principal.email,
        subject=principal.subject,
        role=role,
        source=f"{principal.source}{suffix}",
    )


def require_request_principal(
    x_goog_authenticated_user_email: str | None = Header(
        default=None, alias="X-Goog-Authenticated-User-Email"
    ),
    x_goog_authenticated_user_id: str | None = Header(default=None, alias="X-Goog-Authenticated-User-Id"),
    x_edgewatch_dev_principal_email: str | None = Header(
        default=None, alias="X-EdgeWatch-Dev-Principal-Email"
    ),
    x_edgewatch_dev_principal_role: str | None = Header(default=None, alias="X-EdgeWatch-Dev-Principal-Role"),
) -> Principal:
    # Backward-compatible path: authz can remain disabled.
    if not settings.authz_enabled:
        return Principal(email="anonymous", subject=None, role="admin", source="authz-disabled")

    iap_principal = _principal_from_iap(
        x_goog_authenticated_user_email=x_goog_authenticated_user_email,
        x_goog_authenticated_user_id=x_goog_authenticated_user_id,
    )
    if iap_principal is not None:
        return iap_principal

    dev_principal = _principal_from_dev(
        x_edgewatch_dev_principal_email=x_edgewatch_dev_principal_email,
        x_edgewatch_dev_principal_role=x_edgewatch_dev_principal_role,
    )
    if dev_principal is not None:
        return dev_principal

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing authenticated principal",
    )


def require_admin_principal(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    x_goog_authenticated_user_email: str | None = Header(
        default=None, alias="X-Goog-Authenticated-User-Email"
    ),
    x_goog_authenticated_user_id: str | None = Header(default=None, alias="X-Goog-Authenticated-User-Id"),
    x_edgewatch_dev_principal_email: str | None = Header(
        default=None, alias="X-EdgeWatch-Dev-Principal-Email"
    ),
    x_edgewatch_dev_principal_role: str | None = Header(default=None, alias="X-EdgeWatch-Dev-Principal-Role"),
) -> Principal:
    iap_principal = _principal_from_iap(
        x_goog_authenticated_user_email=x_goog_authenticated_user_email,
        x_goog_authenticated_user_id=x_goog_authenticated_user_id,
    )
    if settings.iap_auth_enabled and iap_principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing IAP authenticated user email",
        )

    dev_principal = _principal_from_dev(
        x_edgewatch_dev_principal_email=x_edgewatch_dev_principal_email,
        x_edgewatch_dev_principal_role=x_edgewatch_dev_principal_role,
    )

    mode = getattr(settings, "admin_auth_mode", "key")
    if mode == "none":
        if iap_principal is not None:
            return iap_principal
        if dev_principal is not None:
            return dev_principal
        if not settings.authz_enabled:
            return Principal(email="perimeter", subject=None, role="admin", source="perimeter")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authenticated principal",
        )

    # key mode
    if (
        not isinstance(x_admin_key, str)
        or not x_admin_key
        or not settings.admin_api_key
        or not hmac.compare_digest(x_admin_key, settings.admin_api_key)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")

    if iap_principal is not None:
        return _principal_with_role(iap_principal, "admin", "admin-key")
    if dev_principal is not None:
        return _principal_with_role(dev_principal, "admin", "admin-key")
    return Principal(email="admin-key", subject=None, role="admin", source="admin-key")
