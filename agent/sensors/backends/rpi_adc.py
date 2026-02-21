from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable

from ..base import Metrics
from ..scaling import current_ma_from_voltage, linear_map

_ADS1115_REG_CONVERSION = 0x00
_ADS1115_REG_CONFIG = 0x01
_ADS1115_MUX_BY_CHANNEL: dict[int, int] = {
    0: 0x4000,
    1: 0x5000,
    2: 0x6000,
    3: 0x7000,
}
_ADS1115_DATA_RATE_BITS: dict[int, int] = {
    8: 0x0000,
    16: 0x0020,
    32: 0x0040,
    64: 0x0060,
    128: 0x0080,
    250: 0x00A0,
    475: 0x00C0,
    860: 0x00E0,
}
_ADS1115_GAIN_CONFIG: tuple[tuple[float, int, float], ...] = (
    (2.0 / 3.0, 0x0000, 6.144),
    (1.0, 0x0200, 4.096),
    (2.0, 0x0400, 2.048),
    (4.0, 0x0600, 1.024),
    (8.0, 0x0800, 0.512),
    (16.0, 0x0A00, 0.256),
)


@runtime_checkable
class I2CBus(Protocol):
    def write_i2c_block_data(self, i2c_addr: int, register: int, data: list[int], /) -> None: ...

    def read_i2c_block_data(self, i2c_addr: int, register: int, length: int, /) -> list[int]: ...


@runtime_checkable
class ChannelVoltageDevice(Protocol):
    def read_channel_voltage(self, channel: int) -> float: ...


def open_smbus(bus_number: int) -> I2CBus:
    try:
        import smbus2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "SENSOR_BACKEND=rpi_adc requires smbus2 (install on Pi: pip install smbus2)"
        ) from exc
    return smbus2.SMBus(bus_number)


def _gain_bits_and_fsr(gain: float) -> tuple[int, float]:
    for configured_gain, gain_bits, fsr_v in _ADS1115_GAIN_CONFIG:
        if abs(gain - configured_gain) < 1e-9:
            return gain_bits, fsr_v
    raise ValueError(f"unsupported ADS1115 gain '{gain}'")


@dataclass
class Ads1115Device:
    bus: I2CBus
    address: int
    gain: float = 1.0
    data_rate: int = 128
    sleep: Callable[[float], None] = time.sleep

    def read_channel_voltage(self, channel: int) -> float:
        mux_bits = _ADS1115_MUX_BY_CHANNEL.get(channel)
        if mux_bits is None:
            raise ValueError(f"invalid ADS1115 channel '{channel}'")

        data_rate_bits = _ADS1115_DATA_RATE_BITS.get(self.data_rate)
        if data_rate_bits is None:
            raise ValueError(f"unsupported ADS1115 data_rate '{self.data_rate}'")

        gain_bits, fsr_v = _gain_bits_and_fsr(self.gain)
        config = 0x8000 | mux_bits | gain_bits | 0x0100 | data_rate_bits | 0x0003
        self.bus.write_i2c_block_data(
            self.address,
            _ADS1115_REG_CONFIG,
            [(config >> 8) & 0xFF, config & 0xFF],
        )

        conversion_wait_s = (1.2 / float(self.data_rate)) + 0.001
        self.sleep(conversion_wait_s)

        raw_bytes = self.bus.read_i2c_block_data(self.address, _ADS1115_REG_CONVERSION, 2)
        if len(raw_bytes) != 2:
            raise RuntimeError("failed to read ADS1115 conversion register")

        raw = (raw_bytes[0] << 8) | raw_bytes[1]
        if raw >= 0x8000:
            raw -= 0x10000

        return (raw * fsr_v) / 32768.0


@dataclass(frozen=True)
class AdcMetricChannel:
    metric_key: str
    channel: int
    kind: str
    shunt_ohms: float | None
    scale_from: tuple[float, float]
    scale_to: tuple[float, float]
    median_samples: int = 1


@dataclass
class RpiAdcSensorBackend:
    adc_type: str
    bus_number: int
    address: int
    gain: float
    data_rate: int
    channels: tuple[AdcMetricChannel, ...]
    warning_interval_s: float = 300.0
    bus_factory: Callable[[int], I2CBus] = open_smbus
    device_factory: Callable[[I2CBus, int, float, int], ChannelVoltageDevice] = (
        lambda bus, address, gain, data_rate: Ads1115Device(
            bus=bus,
            address=address,
            gain=gain,
            data_rate=data_rate,
        )
    )
    monotonic: Callable[[], float] = time.monotonic
    metric_keys: frozenset[str] = field(init=False)
    _adc_device: ChannelVoltageDevice | None = field(default=None, init=False, repr=False)
    _last_warning_at: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.metric_keys = frozenset(ch.metric_key for ch in self.channels)

    def _warn(self, message: str) -> None:
        now = self.monotonic()
        if self._last_warning_at is None or (now - self._last_warning_at) >= self.warning_interval_s:
            print(f"[edgewatch-agent] rpi_adc warning: {message}")
            self._last_warning_at = now

    def _get_adc_device(self) -> ChannelVoltageDevice:
        if self._adc_device is not None:
            return self._adc_device
        bus = self.bus_factory(self.bus_number)
        self._adc_device = self.device_factory(bus, self.address, self.gain, self.data_rate)
        return self._adc_device

    def _sample_voltage(self, *, device: ChannelVoltageDevice, channel: AdcMetricChannel) -> float:
        values = [device.read_channel_voltage(channel.channel) for _ in range(max(1, channel.median_samples))]
        return float(statistics.median(values))

    def _convert_scaled_value(self, *, channel: AdcMetricChannel, voltage_v: float) -> float:
        input_value = voltage_v
        if channel.kind == "current_4_20ma":
            if channel.shunt_ohms is None:
                raise ValueError(f"{channel.metric_key} missing shunt_ohms for current_4_20ma")
            input_value = current_ma_from_voltage(voltage_v=voltage_v, shunt_ohms=channel.shunt_ohms)
        elif channel.kind != "voltage":
            raise ValueError(f"{channel.metric_key} has unsupported kind '{channel.kind}'")

        return linear_map(
            value=input_value,
            from_range=channel.scale_from,
            to_range=channel.scale_to,
            clamp_output=True,
        )

    def read_metrics(self) -> Metrics:
        if self.adc_type != "ads1115":
            self._warn(f"unsupported adc type '{self.adc_type}'")
            return {metric: None for metric in self.metric_keys}

        metrics: Metrics = {}
        for channel in self.channels:
            try:
                device = self._get_adc_device()
                voltage_v = self._sample_voltage(device=device, channel=channel)
                scaled = self._convert_scaled_value(channel=channel, voltage_v=voltage_v)
                metrics[channel.metric_key] = round(float(scaled), 1)
            except Exception as exc:
                self._adc_device = None
                metrics[channel.metric_key] = None
                self._warn(
                    f"{channel.metric_key} read failed on bus={self.bus_number} "
                    f"addr=0x{self.address:02x}: {exc}"
                )
        return metrics
