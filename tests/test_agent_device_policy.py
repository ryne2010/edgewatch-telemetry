from __future__ import annotations

from agent.device_policy import parse_device_policy


def _base_policy_payload() -> dict[str, object]:
    return {
        "device_id": "demo-001",
        "policy_version": "v1",
        "policy_sha256": "abc",
        "cache_max_age_s": 3600,
        "heartbeat_interval_s": 300,
        "offline_after_s": 900,
        "reporting": {
            "sample_interval_s": 30,
            "alert_sample_interval_s": 10,
            "heartbeat_interval_s": 300,
            "alert_report_interval_s": 60,
            "max_points_per_batch": 50,
            "buffer_max_points": 5000,
            "buffer_max_age_s": 604800,
            "backoff_initial_s": 5,
            "backoff_max_s": 300,
        },
        "delta_thresholds": {
            "water_pressure_psi": 1.0,
            "battery_v": 0.05,
        },
        "alert_thresholds": {
            "water_pressure_low_psi": 30.0,
            "water_pressure_recover_psi": 32.0,
            "oil_pressure_low_psi": 20.0,
            "oil_pressure_recover_psi": 22.0,
            "oil_level_low_pct": 20.0,
            "oil_level_recover_pct": 25.0,
            "drip_oil_level_low_pct": 20.0,
            "drip_oil_level_recover_pct": 25.0,
            "oil_life_low_pct": 15.0,
            "oil_life_recover_pct": 20.0,
            "battery_low_v": 11.8,
            "battery_recover_v": 12.0,
            "signal_low_rssi_dbm": -95.0,
            "signal_recover_rssi_dbm": -90.0,
        },
    }


def test_parse_device_policy_reads_cost_caps() -> None:
    payload = _base_policy_payload()
    payload["cost_caps"] = {
        "max_bytes_per_day": 25_000_000,
        "max_snapshots_per_day": 24,
        "max_media_uploads_per_day": 24,
    }
    policy = parse_device_policy(payload)
    assert policy.cost_caps.max_bytes_per_day == 25_000_000
    assert policy.cost_caps.max_snapshots_per_day == 24
    assert policy.cost_caps.max_media_uploads_per_day == 24


def test_parse_device_policy_falls_back_when_cost_caps_missing() -> None:
    payload = _base_policy_payload()
    policy = parse_device_policy(payload)
    assert policy.cost_caps.max_bytes_per_day == 50_000_000
    assert policy.cost_caps.max_snapshots_per_day == 48
    assert policy.cost_caps.max_media_uploads_per_day == 48
