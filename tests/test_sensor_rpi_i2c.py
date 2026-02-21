from __future__ import annotations

from typing import Any

import pytest

from agent.sensors.base import SafeSensorBackend
from agent.sensors.backends.rpi_i2c import BME280Reader, RpiI2CSensorBackend
from agent.sensors.config import SensorConfigError, build_sensor_backend, parse_sensor_config


class _FakeBus:
    def __init__(self) -> None:
        self._bytes = {
            0xD0: 0x60,  # chip id
            0xA1: 75,  # dig_H1
        }
        self._blocks = {
            (0x88, 6): bytes.fromhex("706b436718fc"),  # dig_T*
            (0xE1, 7): bytes.fromhex("6a0100142e031e"),  # dig_H*
            (0xF7, 8): bytes.fromhex("0000007eed007530"),  # raw adc_t + adc_h
        }
        self.writes: list[tuple[int, int]] = []

    def read_byte_data(self, i2c_addr: int, register: int, /) -> int:
        assert i2c_addr == 0x76
        return self._bytes[register]

    def write_byte_data(self, i2c_addr: int, register: int, value: int, /) -> None:
        assert i2c_addr == 0x76
        self.writes.append((register, value))

    def read_i2c_block_data(self, i2c_addr: int, register: int, length: int, /) -> list[int]:
        assert i2c_addr == 0x76
        data = self._blocks[(register, length)]
        return list(data)


def test_bme280_reader_decodes_temperature_and_humidity() -> None:
    bus = _FakeBus()
    reader = BME280Reader(bus=bus, address=0x76)

    temperature_c, humidity_pct = reader.read_temperature_humidity()

    assert temperature_c == pytest.approx(25.08, abs=0.05)
    assert humidity_pct == pytest.approx(47.5, abs=0.3)
    assert (0xF2, 0x01) in bus.writes
    assert (0xF4, 0x27) in bus.writes


class _DummyBus:
    def read_byte_data(self, i2c_addr: int, register: int, /) -> int:
        raise AssertionError("unused")

    def write_byte_data(self, i2c_addr: int, register: int, value: int, /) -> None:
        raise AssertionError("unused")

    def read_i2c_block_data(self, i2c_addr: int, register: int, length: int, /) -> list[int]:
        raise AssertionError("unused")


class _DummyReader:
    def read_temperature_humidity(self) -> tuple[float, float]:
        return 21.234, 55.678


def test_rpi_i2c_backend_rounds_reader_values() -> None:
    backend = RpiI2CSensorBackend(
        bus_factory=lambda _bus: _DummyBus(),
        reader_factory=lambda _bus, _address: _DummyReader(),
    )

    metrics = backend.read_metrics()
    assert metrics == {"temperature_c": 21.2, "humidity_pct": 55.7}


def test_rpi_i2c_backend_rate_limits_warning_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    times = iter([0.0, 1.0, 301.0])

    def _raise_open(_bus: int) -> Any:
        raise RuntimeError("bus missing")

    monkeypatch.setattr("builtins.print", lambda message: calls.append(str(message)))

    backend = RpiI2CSensorBackend(
        bus_factory=_raise_open,
        warning_interval_s=300.0,
        monotonic=lambda: next(times),
    )

    assert backend.read_metrics() == {"temperature_c": None, "humidity_pct": None}
    assert backend.read_metrics() == {"temperature_c": None, "humidity_pct": None}
    assert backend.read_metrics() == {"temperature_c": None, "humidity_pct": None}
    assert len(calls) == 2
    assert "rpi_i2c warning" in calls[0]


def test_build_sensor_backend_rpi_i2c_uses_config_values() -> None:
    cfg = parse_sensor_config(
        {
            "backend": "rpi_i2c",
            "rpi_i2c": {"sensor": "bme280", "bus": 3, "address": "0x77", "warning_interval_s": 10.0},
        },
        origin="test",
    )
    wrapped = build_sensor_backend(device_id="demo-well-001", config=cfg)

    assert isinstance(wrapped, SafeSensorBackend)
    assert isinstance(wrapped.backend, RpiI2CSensorBackend)
    assert wrapped.backend.bus_number == 3
    assert wrapped.backend.address == 0x77
    assert wrapped.backend.warning_interval_s == 10.0


def test_invalid_rpi_i2c_address_fails_config_validation() -> None:
    cfg = parse_sensor_config(
        {"backend": "rpi_i2c", "rpi_i2c": {"address": "not-a-number"}},
        origin="test",
    )
    with pytest.raises(SensorConfigError):
        build_sensor_backend(device_id="demo-well-001", config=cfg)
