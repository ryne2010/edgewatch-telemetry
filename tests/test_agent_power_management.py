from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.device_policy import PowerManagement
from agent.power_management import PowerManager


class _Clock:
    def __init__(self, start: datetime) -> None:
        self._current = start

    def now(self) -> datetime:
        return self._current

    def advance(self, seconds: int) -> None:
        self._current = self._current + timedelta(seconds=seconds)


def _policy(
    *,
    enabled: bool = True,
    mode: str = "dual",
    input_warn_min_v: float = 11.8,
    input_warn_max_v: float = 14.8,
    input_critical_min_v: float = 11.4,
    input_critical_max_v: float = 15.2,
    sustainable_input_w: float = 15.0,
    unsustainable_window_s: int = 900,
    battery_trend_window_s: int = 1800,
    battery_drop_warn_v: float = 0.25,
    saver_sample_interval_s: int = 1200,
    saver_heartbeat_interval_s: int = 1800,
    media_disabled_in_saver: bool = True,
) -> PowerManagement:
    return PowerManagement(
        enabled=enabled,
        mode=mode,
        input_warn_min_v=input_warn_min_v,
        input_warn_max_v=input_warn_max_v,
        input_critical_min_v=input_critical_min_v,
        input_critical_max_v=input_critical_max_v,
        sustainable_input_w=sustainable_input_w,
        unsustainable_window_s=unsustainable_window_s,
        battery_trend_window_s=battery_trend_window_s,
        battery_drop_warn_v=battery_drop_warn_v,
        saver_sample_interval_s=saver_sample_interval_s,
        saver_heartbeat_interval_s=saver_heartbeat_interval_s,
        media_disabled_in_saver=media_disabled_in_saver,
    )


def _clock(start_iso: str = "2026-02-21T00:00:00+00:00") -> _Clock:
    return _Clock(datetime.fromisoformat(start_iso).astimezone(timezone.utc))


def test_power_manager_stable_in_range_writes_state(tmp_path: Path) -> None:
    clock = _clock()
    state_path = tmp_path / "power_state.json"
    manager = PowerManager(path=state_path, now_fn=clock.now)

    result = manager.evaluate(
        metrics={"power_input_v": 12.6, "power_input_w": 10.0, "battery_v": 12.7},
        policy=_policy(),
    )

    assert result.power_source == "battery"
    assert result.power_input_out_of_range is False
    assert result.power_unsustainable is False
    assert result.power_saver_active is False
    assert state_path.exists()

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(state["power_w_samples"]) == 1
    assert len(state["battery_v_samples"]) == 1


def test_power_manager_flags_warn_and_critical_voltage(tmp_path: Path) -> None:
    clock = _clock()
    manager = PowerManager(path=tmp_path / "power_state.json", now_fn=clock.now)
    policy = _policy()

    warn = manager.evaluate(metrics={"power_input_v": 11.7, "power_input_w": 10.0}, policy=policy)
    assert warn.power_input_out_of_range is True
    assert warn.power_unsustainable is False
    assert warn.power_saver_active is True

    clock.advance(60)
    critical = manager.evaluate(metrics={"power_input_v": 11.3, "power_input_w": 10.0}, policy=policy)
    assert critical.power_input_out_of_range is True
    assert critical.power_unsustainable is True
    assert critical.power_saver_active is True


def test_power_manager_detects_hardware_unsustainable_and_recovers(tmp_path: Path) -> None:
    clock = _clock()
    manager = PowerManager(path=tmp_path / "power_state.json", now_fn=clock.now)
    policy = _policy(mode="hardware", sustainable_input_w=15.0, unsustainable_window_s=600)

    manager.evaluate(metrics={"power_input_v": 12.4, "power_input_w": 20.0}, policy=policy)

    clock.advance(600)
    uns = manager.evaluate(metrics={"power_input_v": 12.4, "power_input_w": 20.0}, policy=policy)
    assert uns.power_unsustainable is True
    assert uns.power_saver_active is True

    clock.advance(600)
    recovered = manager.evaluate(metrics={"power_input_v": 12.4, "power_input_w": 5.0}, policy=policy)
    assert recovered.power_unsustainable is False
    assert recovered.power_saver_active is False


def test_power_manager_fallback_battery_drop_trigger_and_recovery(tmp_path: Path) -> None:
    clock = _clock()
    manager = PowerManager(path=tmp_path / "power_state.json", now_fn=clock.now)
    policy = _policy(mode="fallback", battery_trend_window_s=1800, battery_drop_warn_v=0.25)

    manager.evaluate(metrics={"battery_v": 12.7}, policy=policy)

    clock.advance(1800)
    uns = manager.evaluate(metrics={"battery_v": 12.4}, policy=policy)
    assert uns.power_source == "unknown"
    assert uns.power_unsustainable is True
    assert uns.power_saver_active is True

    clock.advance(1800)
    recovered = manager.evaluate(metrics={"battery_v": 12.5}, policy=policy)
    assert recovered.power_unsustainable is False
    assert recovered.power_saver_active is False


def test_power_manager_disabled_returns_flags_off(tmp_path: Path) -> None:
    clock = _clock()
    manager = PowerManager(path=tmp_path / "power_state.json", now_fn=clock.now)
    policy = _policy(enabled=False)

    result = manager.evaluate(
        metrics={"power_input_v": 11.0, "power_input_w": 100.0, "battery_v": 11.0},
        policy=policy,
    )
    assert result.power_source == "battery"
    assert result.power_input_out_of_range is False
    assert result.power_unsustainable is False
    assert result.power_saver_active is False
