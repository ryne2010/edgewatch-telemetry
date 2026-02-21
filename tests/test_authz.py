from __future__ import annotations

from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from api.app.auth.principal import Principal, require_admin_principal, require_request_principal
from api.app.auth.rbac import require_admin_role


def _set_authz_settings(monkeypatch, **overrides) -> None:
    state = {
        "app_env": "dev",
        "admin_auth_mode": "none",
        "admin_api_key": "dev-admin",
        "iap_auth_enabled": False,
        "authz_enabled": True,
        "authz_iap_default_role": "viewer",
        "authz_viewer_emails": [],
        "authz_operator_emails": [],
        "authz_admin_emails": ["admin@example.com"],
        "authz_dev_principal_enabled": True,
        "authz_dev_principal_email": "dev-admin@local.edgewatch",
        "authz_dev_principal_role": "admin",
    }
    state.update(overrides)
    monkeypatch.setattr("api.app.auth.principal.settings", SimpleNamespace(**state))
    monkeypatch.setattr("api.app.auth.rbac.settings", SimpleNamespace(**state))


def test_require_request_principal_maps_iap_admin_role(monkeypatch) -> None:
    _set_authz_settings(monkeypatch, authz_admin_emails=["ops.admin@example.com"])

    principal = require_request_principal(
        x_goog_authenticated_user_email="accounts.google.com:Ops.Admin@Example.com"
    )
    assert principal.email == "ops.admin@example.com"
    assert principal.role == "admin"


def test_require_request_principal_uses_dev_default(monkeypatch) -> None:
    _set_authz_settings(monkeypatch, authz_dev_principal_role="operator")

    principal = require_request_principal()
    assert principal.email == "dev-admin@local.edgewatch"
    assert principal.role == "operator"


def test_require_request_principal_fails_when_no_identity(monkeypatch) -> None:
    _set_authz_settings(
        monkeypatch,
        authz_dev_principal_enabled=False,
        authz_admin_emails=[],
        authz_operator_emails=[],
        authz_viewer_emails=[],
    )

    with pytest.raises(HTTPException) as err:
        require_request_principal()
    assert err.value.status_code == 401
    assert err.value.detail == "Missing authenticated principal"


def test_require_admin_role_rejects_viewer_principal(monkeypatch) -> None:
    _set_authz_settings(monkeypatch)
    principal = Principal(email="viewer@example.com", subject=None, role="viewer", source="iap")
    with pytest.raises(HTTPException) as err:
        require_admin_role(principal)
    assert err.value.status_code == 403
    assert err.value.detail == "admin role required"


def test_require_admin_principal_none_mode_uses_dev_principal(monkeypatch) -> None:
    _set_authz_settings(monkeypatch, admin_auth_mode="none", authz_dev_principal_role="viewer")
    principal = require_admin_principal()
    assert principal.role == "viewer"
    assert principal.source == "dev-principal"


def test_require_admin_principal_key_mode_requires_valid_key(monkeypatch) -> None:
    _set_authz_settings(monkeypatch, admin_auth_mode="key", admin_api_key="top-secret")

    with pytest.raises(HTTPException) as err:
        require_admin_principal(x_admin_key="wrong")
    assert err.value.status_code == 401
    assert err.value.detail == "Invalid admin key"

    principal = require_admin_principal(x_admin_key="top-secret")
    assert principal.role == "admin"
    assert principal.source == "dev-principal+admin-key"
