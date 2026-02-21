from __future__ import annotations

from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from api.app.security import hash_token, token_fingerprint, verify_token
from api.app.security import require_admin


def test_token_fingerprint_is_deterministic() -> None:
    t = "example-token"
    assert token_fingerprint(t) == token_fingerprint(t)
    assert token_fingerprint(t) != token_fingerprint(t + "-2")


def test_hash_and_verify_roundtrip() -> None:
    token = "super-secret-device-token"
    token_hash = hash_token(token)

    assert verify_token(token, token_hash) is True
    assert verify_token(token + "x", token_hash) is False


def _set_security_settings(monkeypatch, **overrides) -> None:
    state = {
        "app_env": "dev",
        "admin_auth_mode": "key",
        "admin_api_key": "dev-admin",
        "iap_auth_enabled": False,
        "authz_enabled": False,
        "authz_iap_default_role": "viewer",
        "authz_viewer_emails": [],
        "authz_operator_emails": [],
        "authz_admin_emails": [],
        "authz_dev_principal_enabled": True,
        "authz_dev_principal_email": "dev-admin@local.edgewatch",
        "authz_dev_principal_role": "admin",
    }
    state.update(overrides)
    monkeypatch.setattr("api.app.security.settings", SimpleNamespace(**state))
    monkeypatch.setattr("api.app.auth.principal.settings", SimpleNamespace(**state))


def test_require_admin_needs_iap_email_when_enabled(monkeypatch) -> None:
    _set_security_settings(monkeypatch, admin_auth_mode="none", iap_auth_enabled=True)

    with pytest.raises(HTTPException) as err:
        require_admin()
    assert err.value.status_code == 401
    assert err.value.detail == "Missing IAP authenticated user email"


def test_require_admin_normalizes_iap_email(monkeypatch) -> None:
    _set_security_settings(monkeypatch, admin_auth_mode="none", iap_auth_enabled=True)

    actor = require_admin(x_goog_authenticated_user_email="accounts.google.com:Ops.User@Example.COM")
    assert actor == "ops.user@example.com"


def test_require_admin_key_mode_uses_admin_key_fallback_actor(monkeypatch) -> None:
    _set_security_settings(monkeypatch, admin_auth_mode="key", admin_api_key="top-secret")

    actor = require_admin(x_admin_key="top-secret")
    assert actor == "dev-admin@local.edgewatch"
