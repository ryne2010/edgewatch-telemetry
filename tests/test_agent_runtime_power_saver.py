from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

agent_main = importlib.import_module("edgewatch_agent")


def test_resolve_runtime_cadence_uses_power_saver_intervals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAMPLE_INTERVAL_S", "100")
    monkeypatch.setenv("ALERT_SAMPLE_INTERVAL_S", "50")
    monkeypatch.setenv("HEARTBEAT_INTERVAL_S", "300")
    monkeypatch.setenv("POWER_SAVER_SAMPLE_INTERVAL_S", "900")
    monkeypatch.setenv("POWER_SAVER_HEARTBEAT_INTERVAL_S", "1200")
    policy = agent_main._default_policy("demo-well-001")

    normal = agent_main._resolve_runtime_cadence(
        policy=policy,
        critical_active=False,
        power_saver_active=False,
        operation_mode="active",
        sleep_poll_interval_s=7 * 24 * 3600,
    )
    critical = agent_main._resolve_runtime_cadence(
        policy=policy,
        critical_active=True,
        power_saver_active=False,
        operation_mode="active",
        sleep_poll_interval_s=7 * 24 * 3600,
    )
    saver = agent_main._resolve_runtime_cadence(
        policy=policy,
        critical_active=True,
        power_saver_active=True,
        operation_mode="active",
        sleep_poll_interval_s=7 * 24 * 3600,
    )
    sleep = agent_main._resolve_runtime_cadence(
        policy=policy,
        critical_active=False,
        power_saver_active=False,
        operation_mode="sleep",
        sleep_poll_interval_s=604800,
    )

    assert normal == (100, 300)
    assert critical == (50, 300)
    assert saver == (900, 1200)
    assert sleep == (604800, 604800)


def test_media_disabled_by_power_respects_policy_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POWER_MEDIA_DISABLED_IN_SAVER", "true")
    policy_disabled = agent_main._default_policy("demo-well-001")
    assert agent_main._media_disabled_by_power(policy=policy_disabled, power_saver_active=False) is False
    assert agent_main._media_disabled_by_power(policy=policy_disabled, power_saver_active=True) is True

    monkeypatch.setenv("POWER_MEDIA_DISABLED_IN_SAVER", "false")
    policy_enabled = agent_main._default_policy("demo-well-001")
    assert agent_main._media_disabled_by_power(policy=policy_enabled, power_saver_active=True) is False


def test_minimal_heartbeat_metrics_includes_power_fields() -> None:
    metrics = {
        "microphone_level_db": 62.0,
        "power_input_v": 12.6,
        "power_input_a": 1.3,
        "power_input_w": 16.2,
        "power_source": "battery",
        "power_input_out_of_range": False,
        "power_unsustainable": True,
        "power_saver_active": True,
        "custom_metric": 123,
    }

    selected = agent_main._minimal_heartbeat_metrics(metrics)
    assert selected["microphone_level_db"] == 62.0
    assert selected["power_input_v"] == 12.6
    assert selected["power_input_a"] == 1.3
    assert selected["power_input_w"] == 16.2
    assert selected["power_source"] == "battery"
    assert selected["power_input_out_of_range"] is False
    assert selected["power_unsustainable"] is True
    assert selected["power_saver_active"] is True
    assert "custom_metric" not in selected
