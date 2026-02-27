from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from api.app.db import Base
from api.app.edge_policy import load_edge_policy, load_edge_policy_source, save_edge_policy_source
from api.app.models import Device, DeviceControlCommand
from api.app.routes import device_policy as device_policy_routes
from api.app.routes.device_policy import get_device_policy
from api.app.schemas import DevicePolicyOut
from fastapi import Response
from starlette.responses import Response as StarletteResponse


def _device(*, heartbeat_interval_s: int = 300, offline_after_s: int = 900) -> Device:
    # Unmapped instance; sufficient for route function.
    return Device(
        device_id="demo-001",
        display_name="Demo",
        token_hash="x",
        token_fingerprint="y",
        heartbeat_interval_s=heartbeat_interval_s,
        offline_after_s=offline_after_s,
        operation_mode="active",
        sleep_poll_interval_s=7 * 24 * 3600,
        last_seen_at=None,
        enabled=True,
    )


def _request(headers: dict[str, str] | None = None) -> Request:
    hdrs = []
    if headers:
        for k, v in headers.items():
            hdrs.append((k.lower().encode("utf-8"), v.encode("utf-8")))

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/device-policy",
        "headers": hdrs,
    }
    return Request(scope)


def test_load_edge_policy_v1_has_expected_fields() -> None:
    p = load_edge_policy("v1")
    assert p.version == "v1"
    assert p.reporting.heartbeat_interval_s > 0
    assert p.alert_thresholds.microphone_offline_db > 0
    assert p.alert_thresholds.microphone_offline_open_consecutive_samples == 2
    assert p.alert_thresholds.microphone_offline_resolve_consecutive_samples == 1
    assert p.alert_thresholds.water_pressure_low_psi > 0
    assert p.cost_caps.max_bytes_per_day > 0
    assert p.power_management.enabled is True
    assert p.power_management.mode == "dual"
    assert p.operation_defaults.admin_remote_shutdown_enabled is True
    assert p.operation_defaults.shutdown_grace_s_default == 30


def test_device_policy_sets_etag_and_supports_304() -> None:
    device = _device()

    req1 = _request()
    resp1 = Response()
    out1 = get_device_policy(req1, resp1, device)

    assert resp1.headers.get("etag")
    assert resp1.headers.get("cache-control")
    assert isinstance(out1, DevicePolicyOut)
    assert out1.device_id == device.device_id
    assert out1.reporting.heartbeat_interval_s == device.heartbeat_interval_s
    assert out1.alert_thresholds.microphone_offline_db > 0
    assert out1.alert_thresholds.microphone_offline_open_consecutive_samples >= 1
    assert out1.alert_thresholds.microphone_offline_resolve_consecutive_samples >= 1
    assert out1.cost_caps.max_bytes_per_day > 0
    assert out1.power_management.mode == "dual"
    assert out1.operation_mode == "active"
    assert out1.sleep_poll_interval_s == 7 * 24 * 3600
    assert out1.disable_requires_manual_restart is True

    etag = resp1.headers.get("etag") or resp1.headers.get("ETag")
    assert etag

    req2 = _request({"If-None-Match": etag})
    resp2 = Response()
    out2 = get_device_policy(req2, resp2, device)

    # When ETag matches, route returns a Starlette Response with 304.
    assert isinstance(out2, StarletteResponse)
    assert out2.status_code == 304


def test_device_policy_etag_changes_when_pending_command_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "device_policy_pending.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    @contextmanager
    def _db_session_override():
        session = session_local()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(device_policy_routes, "db_session", _db_session_override)

    with session_local() as session:
        session.add(
            Device(
                device_id="demo-002",
                display_name="Demo 2",
                token_hash="x",
                token_fingerprint="y2",
                heartbeat_interval_s=300,
                offline_after_s=900,
                operation_mode="active",
                sleep_poll_interval_s=7 * 24 * 3600,
                enabled=True,
            )
        )
        session.commit()

    device = _device()
    device.device_id = "demo-002"

    req1 = _request()
    resp1 = Response()
    out1 = get_device_policy(req1, resp1, device)
    assert isinstance(out1, DevicePolicyOut)
    etag1 = resp1.headers.get("etag")
    assert etag1
    assert out1.pending_control_command is None

    with session_local() as session:
        session.add(
            DeviceControlCommand(
                device_id="demo-002",
                command_payload={
                    "operation_mode": "sleep",
                    "sleep_poll_interval_s": 7200,
                    "shutdown_requested": True,
                    "shutdown_grace_s": 45,
                    "alerts_muted_until": None,
                    "alerts_muted_reason": "offseason",
                },
                status="pending",
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        session.commit()

    req2 = _request()
    resp2 = Response()
    out2 = get_device_policy(req2, resp2, device)
    assert isinstance(out2, DevicePolicyOut)
    etag2 = resp2.headers.get("etag")
    assert etag2
    assert etag2 != etag1
    assert out2.pending_control_command is not None
    assert out2.pending_control_command.operation_mode == "sleep"
    assert out2.pending_control_command.shutdown_requested is True
    assert out2.pending_control_command.shutdown_grace_s == 45


def test_save_edge_policy_source_reloads_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "v1.yaml"
    path.write_text(
        """
version: v1
cache_max_age_s: 3600
reporting:
  sample_interval_s: 30
  alert_sample_interval_s: 10
  heartbeat_interval_s: 300
  alert_report_interval_s: 60
  max_points_per_batch: 50
  buffer_max_points: 5000
  buffer_max_age_s: 604800
  backoff_initial_s: 5
  backoff_max_s: 300
delta_thresholds:
  water_pressure_psi: 1.0
alert_thresholds:
  microphone_offline_db: 60.0
  water_pressure_low_psi: 30.0
  water_pressure_recover_psi: 32.0
  oil_pressure_low_psi: 25.0
  oil_pressure_recover_psi: 28.0
  oil_level_low_pct: 20.0
  oil_level_recover_pct: 25.0
  drip_oil_level_low_pct: 20.0
  drip_oil_level_recover_pct: 25.0
  oil_life_low_pct: 15.0
  oil_life_recover_pct: 20.0
  battery_low_v: 11.8
  battery_recover_v: 12.0
  signal_low_rssi_dbm: -95
  signal_recover_rssi_dbm: -90
cost_caps:
  max_bytes_per_day: 50000000
  max_snapshots_per_day: 48
  max_media_uploads_per_day: 48
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("api.app.edge_policy._policy_path", lambda _: path)
    load_edge_policy.cache_clear()

    original = load_edge_policy("v1")
    assert original.reporting.heartbeat_interval_s == 300
    assert original.power_management.enabled is True
    assert original.power_management.mode == "dual"
    assert original.operation_defaults.default_sleep_poll_interval_s == 7 * 24 * 3600
    assert original.operation_defaults.admin_remote_shutdown_enabled is True
    assert original.operation_defaults.shutdown_grace_s_default == 30
    assert original.operation_defaults.control_command_ttl_s == 180 * 24 * 3600

    saved = save_edge_policy_source(
        "v1",
        load_edge_policy_source("v1").replace("heartbeat_interval_s: 300", "heartbeat_interval_s: 120"),
    )
    assert saved.reporting.heartbeat_interval_s == 120
    assert load_edge_policy("v1").reporting.heartbeat_interval_s == 120

    load_edge_policy.cache_clear()


def test_save_edge_policy_source_rejects_invalid_thresholds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "v1.yaml"
    path.write_text(
        """
version: v1
cache_max_age_s: 3600
reporting:
  sample_interval_s: 30
  alert_sample_interval_s: 10
  heartbeat_interval_s: 300
  alert_report_interval_s: 60
  max_points_per_batch: 50
  buffer_max_points: 5000
  buffer_max_age_s: 604800
  backoff_initial_s: 5
  backoff_max_s: 300
delta_thresholds:
  water_pressure_psi: 1.0
alert_thresholds:
  microphone_offline_db: 60.0
  water_pressure_low_psi: 30.0
  water_pressure_recover_psi: 32.0
  oil_pressure_low_psi: 25.0
  oil_pressure_recover_psi: 28.0
  oil_level_low_pct: 20.0
  oil_level_recover_pct: 25.0
  drip_oil_level_low_pct: 20.0
  drip_oil_level_recover_pct: 25.0
  oil_life_low_pct: 15.0
  oil_life_recover_pct: 20.0
  battery_low_v: 11.8
  battery_recover_v: 12.0
  signal_low_rssi_dbm: -95
  signal_recover_rssi_dbm: -90
cost_caps:
  max_bytes_per_day: 50000000
  max_snapshots_per_day: 48
  max_media_uploads_per_day: 48
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("api.app.edge_policy._policy_path", lambda _: path)
    load_edge_policy.cache_clear()

    invalid = load_edge_policy_source("v1").replace(
        "water_pressure_recover_psi: 32.0", "water_pressure_recover_psi: 20.0"
    )
    with pytest.raises(ValueError):
        save_edge_policy_source("v1", invalid)

    # Invalid edits are rejected without modifying on-disk contract content.
    assert "water_pressure_recover_psi: 32.0" in load_edge_policy_source("v1")
    load_edge_policy.cache_clear()
