from __future__ import annotations

from typing import Any

import pytest

from agent.sensors.base import SafeSensorBackend
from agent.sensors.backends.rpi_power_i2c import RpiPowerI2CSensorBackend
from agent.sensors.config import SensorConfigError, build_sensor_backend, parse_sensor_config


def _raw_word_for_read(value: int) -> int:
    word = int(value) & 0xFFFF
    return ((word & 0xFF) << 8) | ((word >> 8) & 0xFF)


class _WordBus:
    def __init__(self, words: dict[int, int]) -> None:
        self._words = words

    def read_word_data(self, i2c_addr: int, register: int, /) -> int:
        assert i2c_addr == 0x40
        return self._words[register]


def test_rpi_power_i2c_ina260_converts_metrics() -> None:
    words = {
        0x01: _raw_word_for_read(1000),  # 1.25 A
        0x02: _raw_word_for_read(10_000),  # 12.5 V
        0x03: _raw_word_for_read(1_500),  # 15.0 W
    }

    backend = RpiPowerI2CSensorBackend(
        sensor="ina260",
        bus_factory=lambda _bus: _WordBus(words),
    )
    metrics = backend.read_metrics()
    assert metrics == {
        "power_input_v": 12.5,
        "power_input_a": 1.25,
        "power_input_w": 15.0,
        "power_source": "battery",
    }


def test_rpi_power_i2c_ina219_converts_metrics_and_source() -> None:
    bus_reg = 3400 << 3  # 13.6 V
    shunt_reg = 15_000  # 0.15 V across 0.1 ohm => 1.5 A
    words = {
        0x02: _raw_word_for_read(bus_reg),
        0x01: _raw_word_for_read(shunt_reg),
    }

    backend = RpiPowerI2CSensorBackend(
        sensor="ina219",
        shunt_ohms=0.1,
        bus_factory=lambda _bus: _WordBus(words),
    )
    metrics = backend.read_metrics()
    assert metrics["power_input_v"] == pytest.approx(13.6, abs=0.01)
    assert metrics["power_input_a"] == pytest.approx(1.5, abs=0.01)
    assert metrics["power_input_w"] == pytest.approx(20.4, abs=0.05)
    assert metrics["power_source"] == "solar"


def test_rpi_power_i2c_rate_limits_warning_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    times = iter([0.0, 1.0, 301.0])

    def _raise_open(_bus: int) -> Any:
        raise RuntimeError("i2c bus missing")

    monkeypatch.setattr("builtins.print", lambda message: calls.append(str(message)))

    backend = RpiPowerI2CSensorBackend(
        bus_factory=_raise_open,
        warning_interval_s=300.0,
        monotonic=lambda: next(times),
    )

    expected = {
        "power_input_v": None,
        "power_input_a": None,
        "power_input_w": None,
        "power_source": "unknown",
    }
    assert backend.read_metrics() == expected
    assert backend.read_metrics() == expected
    assert backend.read_metrics() == expected
    assert len(calls) == 2
    assert "rpi_power_i2c warning" in calls[0]


def test_build_sensor_backend_rpi_power_i2c_uses_config_values() -> None:
    cfg = parse_sensor_config(
        {
            "backend": "rpi_power_i2c",
            "rpi_power_i2c": {
                "sensor": "ina219",
                "bus": 3,
                "address": "0x45",
                "shunt_ohms": 0.02,
                "source_solar_min_v": 13.4,
                "warning_interval_s": 10.0,
            },
        },
        origin="test",
    )
    wrapped = build_sensor_backend(device_id="demo-well-001", config=cfg)

    assert isinstance(wrapped, SafeSensorBackend)
    assert isinstance(wrapped.backend, RpiPowerI2CSensorBackend)
    assert wrapped.backend.sensor == "ina219"
    assert wrapped.backend.bus_number == 3
    assert wrapped.backend.address == 0x45
    assert wrapped.backend.shunt_ohms == 0.02
    assert wrapped.backend.source_solar_min_v == 13.4
    assert wrapped.backend.warning_interval_s == 10.0


def test_invalid_rpi_power_i2c_shunt_fails_config_validation() -> None:
    cfg = parse_sensor_config(
        {
            "backend": "rpi_power_i2c",
            "rpi_power_i2c": {"sensor": "ina219", "shunt_ohms": 0.0},
        },
        origin="test",
    )
    with pytest.raises(SensorConfigError):
        build_sensor_backend(device_id="demo-well-001", config=cfg)
