from __future__ import annotations

import pytest

from agent.sensors.backends.rpi_adc import AdcMetricChannel, Ads1115Device, RpiAdcSensorBackend
from agent.sensors.config import SensorConfigError, build_sensor_backend, parse_sensor_config
from agent.sensors.scaling import voltage_from_current_ma


class _FakeAdsBus:
    def __init__(self, raw_by_channel: dict[int, int]) -> None:
        self.raw_by_channel = raw_by_channel
        self.active_channel = 0
        self.config_writes: list[int] = []

    def write_i2c_block_data(self, i2c_addr: int, register: int, data: list[int], /) -> None:
        assert i2c_addr == 0x48
        assert register == 0x01
        config = (data[0] << 8) | data[1]
        self.config_writes.append(config)
        mux_bits = config & 0x7000
        channel_by_mux = {0x4000: 0, 0x5000: 1, 0x6000: 2, 0x7000: 3}
        self.active_channel = channel_by_mux[mux_bits]

    def read_i2c_block_data(self, i2c_addr: int, register: int, length: int, /) -> list[int]:
        assert i2c_addr == 0x48
        assert register == 0x00
        assert length == 2
        raw = self.raw_by_channel[self.active_channel]
        if raw < 0:
            raw += 0x10000
        return [(raw >> 8) & 0xFF, raw & 0xFF]


def test_ads1115_device_reads_single_ended_voltage() -> None:
    # ~1.65V with gain=1 (FSR 4.096V)
    raw = int((1.65 / 4.096) * 32768.0)
    bus = _FakeAdsBus(raw_by_channel={0: raw})
    device = Ads1115Device(bus=bus, address=0x48, gain=1.0, data_rate=128, sleep=lambda _s: None)

    value = device.read_channel_voltage(0)
    assert value == pytest.approx(1.65, abs=0.02)
    assert bus.config_writes


class _DummyBus:
    def write_i2c_block_data(self, i2c_addr: int, register: int, data: list[int], /) -> None:
        raise AssertionError("unused")

    def read_i2c_block_data(self, i2c_addr: int, register: int, length: int, /) -> list[int]:
        raise AssertionError("unused")


class _VoltageSequenceDevice:
    def __init__(self, by_channel: dict[int, list[float]]) -> None:
        self.by_channel = by_channel

    def read_channel_voltage(self, channel: int) -> float:
        values = self.by_channel[channel]
        if not values:
            raise RuntimeError(f"no values for channel {channel}")
        return values.pop(0)


def test_rpi_adc_backend_scales_current_channels() -> None:
    device = _VoltageSequenceDevice(
        by_channel={
            0: [voltage_from_current_ma(current_ma=4.0, shunt_ohms=165.0)],
            1: [voltage_from_current_ma(current_ma=12.0, shunt_ohms=165.0)],
            2: [voltage_from_current_ma(current_ma=20.0, shunt_ohms=165.0)],
        }
    )
    backend = RpiAdcSensorBackend(
        adc_type="ads1115",
        bus_number=1,
        address=0x48,
        gain=1.0,
        data_rate=128,
        channels=(
            AdcMetricChannel("water_pressure_psi", 0, "current_4_20ma", 165.0, (4.0, 20.0), (0.0, 100.0)),
            AdcMetricChannel("oil_pressure_psi", 1, "current_4_20ma", 165.0, (4.0, 20.0), (0.0, 100.0)),
            AdcMetricChannel("oil_level_pct", 2, "current_4_20ma", 165.0, (4.0, 20.0), (0.0, 100.0)),
        ),
        bus_factory=lambda _bus: _DummyBus(),
        device_factory=lambda _bus, _address, _gain, _dr: device,
    )

    metrics = backend.read_metrics()
    assert metrics["water_pressure_psi"] == pytest.approx(0.0, abs=0.1)
    assert metrics["oil_pressure_psi"] == pytest.approx(50.0, abs=0.2)
    assert metrics["oil_level_pct"] == pytest.approx(100.0, abs=0.1)


def test_rpi_adc_backend_uses_median_samples() -> None:
    device = _VoltageSequenceDevice(
        by_channel={
            0: [
                voltage_from_current_ma(current_ma=4.0, shunt_ohms=165.0),
                voltage_from_current_ma(current_ma=20.0, shunt_ohms=165.0),
                voltage_from_current_ma(current_ma=12.0, shunt_ohms=165.0),
            ]
        }
    )
    backend = RpiAdcSensorBackend(
        adc_type="ads1115",
        bus_number=1,
        address=0x48,
        gain=1.0,
        data_rate=128,
        channels=(
            AdcMetricChannel(
                "water_pressure_psi",
                0,
                "current_4_20ma",
                165.0,
                (4.0, 20.0),
                (0.0, 100.0),
                median_samples=3,
            ),
        ),
        bus_factory=lambda _bus: _DummyBus(),
        device_factory=lambda _bus, _address, _gain, _dr: device,
    )

    metrics = backend.read_metrics()
    assert metrics["water_pressure_psi"] == pytest.approx(50.0, abs=0.2)


def test_rpi_adc_backend_returns_none_for_failed_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    device = _VoltageSequenceDevice(
        by_channel={
            0: [voltage_from_current_ma(current_ma=10.0, shunt_ohms=165.0)],
            1: [],
        }
    )
    calls: list[str] = []
    monkeypatch.setattr("builtins.print", lambda message: calls.append(str(message)))

    backend = RpiAdcSensorBackend(
        adc_type="ads1115",
        bus_number=1,
        address=0x48,
        gain=1.0,
        data_rate=128,
        channels=(
            AdcMetricChannel("water_pressure_psi", 0, "current_4_20ma", 165.0, (4.0, 20.0), (0.0, 100.0)),
            AdcMetricChannel("oil_pressure_psi", 1, "current_4_20ma", 165.0, (4.0, 20.0), (0.0, 100.0)),
        ),
        bus_factory=lambda _bus: _DummyBus(),
        device_factory=lambda _bus, _address, _gain, _dr: device,
    )

    metrics = backend.read_metrics()
    assert metrics["water_pressure_psi"] == pytest.approx(37.5, abs=0.2)
    assert metrics["oil_pressure_psi"] is None
    assert calls


def test_rpi_adc_config_defaults_produce_canonical_channels() -> None:
    cfg = parse_sensor_config({"backend": "rpi_adc"}, origin="test")
    wrapped = build_sensor_backend(device_id="demo-well-001", config=cfg)

    backend = wrapped.backend
    assert isinstance(backend, RpiAdcSensorBackend)
    assert backend.metric_keys == frozenset(
        {"water_pressure_psi", "oil_pressure_psi", "oil_level_pct", "drip_oil_level_pct"}
    )


def test_invalid_rpi_adc_channel_kind_raises() -> None:
    cfg = parse_sensor_config(
        {"backend": "rpi_adc", "channels": {"water_pressure_psi": {"channel": 0, "kind": "bad-kind"}}},
        origin="test",
    )

    with pytest.raises(SensorConfigError):
        build_sensor_backend(device_id="demo-well-001", config=cfg)


def test_invalid_rpi_adc_address_raises() -> None:
    cfg = parse_sensor_config(
        {"backend": "rpi_adc", "adc": {"address": "invalid"}},
        origin="test",
    )
    with pytest.raises(SensorConfigError):
        build_sensor_backend(device_id="demo-well-001", config=cfg)


def test_rpi_adc_unsupported_type_returns_none_metrics() -> None:
    backend = RpiAdcSensorBackend(
        adc_type="unsupported",
        bus_number=1,
        address=0x48,
        gain=1.0,
        data_rate=128,
        channels=(AdcMetricChannel("water_pressure_psi", 0, "voltage", None, (0.0, 3.3), (0.0, 100.0)),),
        bus_factory=lambda _bus: _DummyBus(),
        device_factory=lambda _bus, _address, _gain, _dr: _VoltageSequenceDevice({0: [1.1]}),
    )

    assert backend.read_metrics() == {"water_pressure_psi": None}
