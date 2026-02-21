from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from agent.sensors.base import Metrics
from agent.sensors.backends.composite import CompositeSensorBackend
from agent.sensors.backends.derived import DerivedOilLifeBackend
from agent.sensors.derived.oil_life import OilLifeStateStore


def _metric_float(value: Any) -> float:
    assert isinstance(value, (float, int)) and not isinstance(value, bool)
    return float(value)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.current = start

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current = self.current + timedelta(seconds=seconds)


def test_derived_oil_life_decreases_only_while_running(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 2, 21, 12, 0, 0, tzinfo=timezone.utc))
    backend = DerivedOilLifeBackend(
        oil_life_max_run_hours=1.0,
        state_path=str(tmp_path / "oil_life_state.json"),
        now_fn=clock.now,
        warning_interval_s=0.0,
    )

    assert backend.read_metrics_with_context({"pump_on": True})["oil_life_pct"] == 100.0

    clock.advance(1800)
    assert backend.read_metrics_with_context({"pump_on": True})["oil_life_pct"] == pytest.approx(
        50.0, abs=0.2
    )

    clock.advance(1800)
    assert backend.read_metrics_with_context({"pump_on": False})["oil_life_pct"] == pytest.approx(
        0.0, abs=0.1
    )

    clock.advance(1800)
    # Stopped interval should not decrease further.
    assert backend.read_metrics_with_context({"pump_on": False})["oil_life_pct"] == pytest.approx(
        0.0, abs=0.1
    )


def test_derived_oil_life_hysteresis_when_pump_flag_missing(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 2, 21, 12, 0, 0, tzinfo=timezone.utc))
    backend = DerivedOilLifeBackend(
        oil_life_max_run_hours=10.0,
        state_path=str(tmp_path / "oil_life_state.json"),
        run_on_threshold=25.0,
        run_off_threshold=20.0,
        now_fn=clock.now,
        warning_interval_s=0.0,
    )

    backend.read_metrics_with_context({"oil_pressure_psi": 30.0})  # starts running
    clock.advance(600)
    backend.read_metrics_with_context({"oil_pressure_psi": 22.0})  # still running (hysteresis)
    clock.advance(600)
    backend.read_metrics_with_context({"oil_pressure_psi": 19.0})  # transitions to stopped
    clock.advance(600)
    backend.read_metrics_with_context({"oil_pressure_psi": 21.0})  # remains stopped

    store = OilLifeStateStore(tmp_path / "oil_life_state.json")
    state = store.load()
    assert state.oil_life_runtime_s == pytest.approx(1200.0, abs=0.1)
    assert state.is_running is False


def test_derived_state_survives_restart(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 2, 21, 12, 0, 0, tzinfo=timezone.utc))
    state_path = tmp_path / "oil_life_state.json"

    backend_a = DerivedOilLifeBackend(
        oil_life_max_run_hours=2.0,
        state_path=str(state_path),
        now_fn=clock.now,
        warning_interval_s=0.0,
    )
    backend_a.read_metrics_with_context({"pump_on": True})
    clock.advance(600)
    first = _metric_float(backend_a.read_metrics_with_context({"pump_on": True})["oil_life_pct"])

    backend_b = DerivedOilLifeBackend(
        oil_life_max_run_hours=2.0,
        state_path=str(state_path),
        now_fn=clock.now,
        warning_interval_s=0.0,
    )
    clock.advance(600)
    second = _metric_float(backend_b.read_metrics_with_context({"pump_on": True})["oil_life_pct"])

    assert second < first


class _StaticSource:
    metric_keys = frozenset({"pump_on", "water_pressure_psi"})

    def __init__(self, values: list[bool]) -> None:
        self._values = values

    def read_metrics(self) -> Metrics:
        next_value = self._values.pop(0) if self._values else False
        return {"pump_on": next_value, "water_pressure_psi": 42.0}


def test_composite_passes_upstream_metrics_to_derived_backend(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 2, 21, 12, 0, 0, tzinfo=timezone.utc))
    source = _StaticSource([True, True, False])
    derived = DerivedOilLifeBackend(
        oil_life_max_run_hours=1.0,
        state_path=str(tmp_path / "oil_life_state.json"),
        now_fn=clock.now,
        warning_interval_s=0.0,
    )
    composite = CompositeSensorBackend(backends=[source, derived])

    composite.read_metrics()
    clock.advance(900)
    metrics_mid = composite.read_metrics()
    clock.advance(900)
    metrics_end = composite.read_metrics()

    assert metrics_mid["oil_life_pct"] == pytest.approx(75.0, abs=0.2)
    assert metrics_end["oil_life_pct"] == pytest.approx(50.0, abs=0.2)
