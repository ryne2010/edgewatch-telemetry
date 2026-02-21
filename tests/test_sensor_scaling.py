from __future__ import annotations

import pytest

from agent.sensors.scaling import (
    ScalingConfig,
    clamp,
    current_4_20ma_to_percent,
    current_ma_from_voltage,
    linear_map,
    voltage_from_current_ma,
)


def test_current_voltage_round_trip() -> None:
    voltage = voltage_from_current_ma(current_ma=12.0, shunt_ohms=165.0)
    assert current_ma_from_voltage(voltage_v=voltage, shunt_ohms=165.0) == pytest.approx(12.0, abs=1e-6)


def test_linear_map_4ma_to_0_and_20ma_to_100() -> None:
    assert linear_map(value=4.0, from_range=(4.0, 20.0), to_range=(0.0, 100.0)) == pytest.approx(0.0)
    assert linear_map(value=20.0, from_range=(4.0, 20.0), to_range=(0.0, 100.0)) == pytest.approx(100.0)


def test_linear_map_clamps_out_of_range() -> None:
    assert linear_map(value=2.0, from_range=(4.0, 20.0), to_range=(0.0, 100.0)) == 0.0
    assert linear_map(value=25.0, from_range=(4.0, 20.0), to_range=(0.0, 100.0)) == 100.0


def test_current_4_20ma_to_percent() -> None:
    assert current_4_20ma_to_percent(current_ma=12.0) == pytest.approx(50.0)


def test_scaling_config_apply() -> None:
    cfg = ScalingConfig(from_range=(0.0, 5.0), to_range=(0.0, 100.0))
    assert cfg.apply(2.5) == pytest.approx(50.0)


def test_clamp_invalid_range_raises() -> None:
    with pytest.raises(ValueError):
        clamp(1.0, 2.0, 1.0)
