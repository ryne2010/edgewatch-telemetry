from __future__ import annotations

from pathlib import Path

from agent.device_policy import load_cached_policy, parse_device_policy, save_cached_policy


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
            "microphone_offline_db": 60.0,
            "microphone_offline_open_consecutive_samples": 2,
            "microphone_offline_resolve_consecutive_samples": 1,
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
    payload["alert_thresholds"].pop("microphone_offline_db")  # type: ignore[index]
    policy = parse_device_policy(payload)
    assert policy.cost_caps.max_bytes_per_day == 50_000_000
    assert policy.cost_caps.max_snapshots_per_day == 48
    assert policy.cost_caps.max_media_uploads_per_day == 48
    assert policy.alert_thresholds.microphone_offline_db == 60.0


def test_parse_device_policy_defaults_power_management_when_missing() -> None:
    payload = _base_policy_payload()
    policy = parse_device_policy(payload)

    assert policy.operation_mode == "active"
    assert policy.sleep_poll_interval_s == 7 * 24 * 3600
    assert policy.disable_requires_manual_restart is True
    assert policy.pending_control_command is None
    assert policy.power_management.enabled is True
    assert policy.power_management.mode == "dual"
    assert policy.power_management.input_warn_min_v == 11.8
    assert policy.power_management.input_warn_max_v == 14.8
    assert policy.power_management.input_critical_min_v == 11.4
    assert policy.power_management.input_critical_max_v == 15.2
    assert policy.power_management.sustainable_input_w == 15.0
    assert policy.power_management.unsustainable_window_s == 900
    assert policy.power_management.battery_trend_window_s == 1800
    assert policy.power_management.battery_drop_warn_v == 0.25
    assert policy.power_management.saver_sample_interval_s == 1200
    assert policy.power_management.saver_heartbeat_interval_s == 1800
    assert policy.power_management.media_disabled_in_saver is True


def test_parse_device_policy_reads_power_management_values() -> None:
    payload = _base_policy_payload()
    payload["power_management"] = {
        "enabled": True,
        "mode": "fallback",
        "input_warn_min_v": 11.9,
        "input_warn_max_v": 14.7,
        "input_critical_min_v": 11.5,
        "input_critical_max_v": 15.1,
        "sustainable_input_w": 12.5,
        "unsustainable_window_s": 600,
        "battery_trend_window_s": 1200,
        "battery_drop_warn_v": 0.35,
        "saver_sample_interval_s": 1500,
        "saver_heartbeat_interval_s": 2100,
        "media_disabled_in_saver": False,
    }
    policy = parse_device_policy(payload)

    assert policy.power_management.mode == "fallback"
    assert policy.power_management.input_warn_min_v == 11.9
    assert policy.power_management.input_warn_max_v == 14.7
    assert policy.power_management.input_critical_min_v == 11.5
    assert policy.power_management.input_critical_max_v == 15.1
    assert policy.power_management.sustainable_input_w == 12.5
    assert policy.power_management.unsustainable_window_s == 600
    assert policy.power_management.battery_trend_window_s == 1200
    assert policy.power_management.battery_drop_warn_v == 0.35
    assert policy.power_management.saver_sample_interval_s == 1500
    assert policy.power_management.saver_heartbeat_interval_s == 2100
    assert policy.power_management.media_disabled_in_saver is False


def test_parse_device_policy_reads_operation_controls() -> None:
    payload = _base_policy_payload()
    payload["operation_mode"] = "sleep"
    payload["sleep_poll_interval_s"] = 3600
    payload["disable_requires_manual_restart"] = False

    policy = parse_device_policy(payload)
    assert policy.operation_mode == "sleep"
    assert policy.sleep_poll_interval_s == 3600
    assert policy.disable_requires_manual_restart is False


def test_parse_device_policy_reads_pending_control_command() -> None:
    payload = _base_policy_payload()
    payload["pending_control_command"] = {
        "id": "cmd-123",
        "issued_at": "2026-02-27T00:00:00Z",
        "expires_at": "2026-08-26T00:00:00Z",
        "operation_mode": "sleep",
        "sleep_poll_interval_s": 7200,
        "shutdown_requested": True,
        "shutdown_grace_s": 45,
        "alerts_muted_until": "2026-03-10T00:00:00Z",
        "alerts_muted_reason": "offseason",
    }

    policy = parse_device_policy(payload)
    assert policy.pending_control_command is not None
    assert policy.pending_control_command.id == "cmd-123"
    assert policy.pending_control_command.operation_mode == "sleep"
    assert policy.pending_control_command.sleep_poll_interval_s == 7200
    assert policy.pending_control_command.shutdown_requested is True
    assert policy.pending_control_command.shutdown_grace_s == 45


def test_cached_policy_roundtrip_includes_power_management(tmp_path: Path) -> None:
    payload = _base_policy_payload()
    payload["power_management"] = {
        "enabled": True,
        "mode": "hardware",
        "input_warn_min_v": 11.8,
        "input_warn_max_v": 14.8,
        "input_critical_min_v": 11.4,
        "input_critical_max_v": 15.2,
        "sustainable_input_w": 14.0,
        "unsustainable_window_s": 900,
        "battery_trend_window_s": 1800,
        "battery_drop_warn_v": 0.25,
        "saver_sample_interval_s": 1200,
        "saver_heartbeat_interval_s": 1800,
        "media_disabled_in_saver": True,
    }
    policy = parse_device_policy(payload)

    cache_path = tmp_path / "policy_cache.json"
    save_cached_policy(policy, "etag-1", path=cache_path)
    cached = load_cached_policy(path=cache_path)
    assert cached is not None
    assert cached.policy.power_management.mode == "hardware"
    assert cached.policy.power_management.sustainable_input_w == 14.0
