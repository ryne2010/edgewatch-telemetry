from __future__ import annotations

from pathlib import Path

import pytest
from starlette.requests import Request

from api.app.edge_policy import load_edge_policy, load_edge_policy_source, save_edge_policy_source
from api.app.models import Device
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
    assert p.alert_thresholds.water_pressure_low_psi > 0
    assert p.cost_caps.max_bytes_per_day > 0


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
    assert out1.cost_caps.max_bytes_per_day > 0

    etag = resp1.headers.get("etag") or resp1.headers.get("ETag")
    assert etag

    req2 = _request({"If-None-Match": etag})
    resp2 = Response()
    out2 = get_device_policy(req2, resp2, device)

    # When ETag matches, route returns a Starlette Response with 304.
    assert isinstance(out2, StarletteResponse)
    assert out2.status_code == 304


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
