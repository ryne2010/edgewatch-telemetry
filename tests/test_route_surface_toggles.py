from __future__ import annotations

from api.app.config import load_settings
from api.app.main import create_app


def _paths(app) -> set[str]:
    paths: set[str] = set()
    for r in app.router.routes:
        p = getattr(r, "path", None)
        if isinstance(p, str):
            paths.add(p)
    return paths


def test_default_route_surface_includes_ui_read_ingest(monkeypatch) -> None:
    # Minimal env for settings load.
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///./test_toggle.db")
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin")

    settings = load_settings()
    app = create_app(settings)

    paths = _paths(app)

    # UI
    assert "/" in paths

    # Ingest surface
    assert "/api/v1/ingest" in paths
    assert "/api/v1/device-policy" in paths
    assert "/api/v1/device-commands/{command_id}/ack" in paths

    # Read surface
    assert "/api/v1/devices" in paths
    assert "/api/v1/alerts" in paths
    assert "/api/v1/contracts/telemetry" in paths
    assert "/api/v1/devices/{device_id}/controls" in paths

    # Admin surface
    assert "/api/v1/admin/contracts/edge-policy" in paths
    assert "/api/v1/admin/devices/{device_id}/access" in paths
    assert "/api/v1/admin/devices/{device_id}/controls/shutdown" in paths


def test_disable_ui_removes_ui_routes(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///./test_toggle.db")
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin")
    monkeypatch.setenv("ENABLE_UI", "0")

    settings = load_settings()
    app = create_app(settings)

    paths = _paths(app)
    assert "/" not in paths


def test_disable_read_routes_removes_dashboard_endpoints(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///./test_toggle.db")
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin")
    monkeypatch.setenv("ENABLE_READ_ROUTES", "0")

    settings = load_settings()
    app = create_app(settings)

    paths = _paths(app)

    assert "/api/v1/devices" not in paths
    assert "/api/v1/alerts" not in paths
    assert "/api/v1/contracts/telemetry" not in paths
    assert "/api/v1/devices/{device_id}/controls" not in paths


def test_disable_ingest_routes_removes_ingest_endpoints(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///./test_toggle.db")
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin")
    monkeypatch.setenv("ENABLE_INGEST_ROUTES", "0")

    settings = load_settings()
    app = create_app(settings)

    paths = _paths(app)

    assert "/api/v1/ingest" not in paths
    assert "/api/v1/device-policy" not in paths
    assert "/api/v1/device-commands/{command_id}/ack" not in paths
    assert "/api/v1/internal/pubsub/push" not in paths


def test_disable_admin_routes_removes_admin_endpoints(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///./test_toggle.db")
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin")
    monkeypatch.setenv("ENABLE_ADMIN_ROUTES", "0")

    settings = load_settings()
    app = create_app(settings)

    paths = _paths(app)

    assert "/api/v1/admin/contracts/edge-policy" not in paths
    assert "/api/v1/admin/devices/{device_id}/controls/shutdown" not in paths


def test_admin_api_key_is_trimmed(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///./test_toggle.db")
    monkeypatch.setenv("ADMIN_API_KEY", "  test-admin-key  ")

    settings = load_settings()
    assert settings.admin_api_key == "test-admin-key"
