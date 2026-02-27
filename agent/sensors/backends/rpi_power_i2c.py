from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable

from ..base import Metrics

_INA219_REG_SHUNT_VOLTAGE = 0x01
_INA219_REG_BUS_VOLTAGE = 0x02
_INA260_REG_CURRENT = 0x01
_INA260_REG_BUS_VOLTAGE = 0x02
_INA260_REG_POWER = 0x03


@runtime_checkable
class I2CBus(Protocol):
    def read_word_data(self, i2c_addr: int, register: int, /) -> int: ...


def open_smbus(bus_number: int) -> I2CBus:
    try:
        import smbus2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "SENSOR_BACKEND=rpi_power_i2c requires smbus2 (install on Pi: pip install smbus2)"
        ) from exc
    return smbus2.SMBus(bus_number)


def _swap_u16(raw: int) -> int:
    value = int(raw) & 0xFFFF
    return ((value & 0xFF) << 8) | ((value >> 8) & 0xFF)


def _signed16(raw: int) -> int:
    value = int(raw) & 0xFFFF
    return value - 0x10000 if value >= 0x8000 else value


def _infer_power_source(*, input_v: float | None, solar_min_v: float) -> str:
    if input_v is None:
        return "unknown"
    if input_v >= solar_min_v:
        return "solar"
    return "battery"


@dataclass
class RpiPowerI2CSensorBackend:
    sensor: str = "ina260"
    bus_number: int = 1
    address: int = 0x40
    shunt_ohms: float = 0.1
    source_solar_min_v: float = 13.2
    warning_interval_s: float = 300.0
    bus_factory: Callable[[int], I2CBus] = open_smbus
    monotonic: Callable[[], float] = time.monotonic
    metric_keys: frozenset[str] = field(
        default_factory=lambda: frozenset({"power_input_v", "power_input_a", "power_input_w", "power_source"})
    )
    _bus: I2CBus | None = field(default=None, init=False, repr=False)
    _last_warning_at: float | None = field(default=None, init=False, repr=False)

    def _warn(self, message: str) -> None:
        now = self.monotonic()
        if self._last_warning_at is None or (now - self._last_warning_at) >= self.warning_interval_s:
            print(f"[edgewatch-agent] rpi_power_i2c warning: {message}")
            self._last_warning_at = now

    def _none_metrics(self) -> Metrics:
        return {
            "power_input_v": None,
            "power_input_a": None,
            "power_input_w": None,
            "power_source": "unknown",
        }

    def _i2c_bus(self) -> I2CBus:
        if self._bus is not None:
            return self._bus
        self._bus = self.bus_factory(self.bus_number)
        return self._bus

    def _read_u16(self, register: int) -> int:
        return _swap_u16(self._i2c_bus().read_word_data(self.address, register))

    def _read_s16(self, register: int) -> int:
        return _signed16(self._read_u16(register))

    def _read_ina219(self) -> tuple[float, float, float]:
        if self.shunt_ohms <= 0:
            raise ValueError("ina219 requires shunt_ohms > 0")
        bus_reg = self._read_u16(_INA219_REG_BUS_VOLTAGE)
        shunt_reg = self._read_s16(_INA219_REG_SHUNT_VOLTAGE)

        input_v = float(bus_reg >> 3) * 0.004
        shunt_v = float(shunt_reg) * 0.00001
        input_a = shunt_v / self.shunt_ohms
        input_w = input_v * input_a
        return input_v, input_a, input_w

    def _read_ina260(self) -> tuple[float, float, float]:
        current_reg = self._read_s16(_INA260_REG_CURRENT)
        bus_reg = self._read_u16(_INA260_REG_BUS_VOLTAGE)
        power_reg = self._read_u16(_INA260_REG_POWER)

        input_a = float(current_reg) * 0.00125
        input_v = float(bus_reg) * 0.00125
        input_w = float(power_reg) * 0.01
        return input_v, input_a, input_w

    def read_metrics(self) -> Metrics:
        sensor = self.sensor.strip().lower()
        if sensor not in {"ina219", "ina260"}:
            self._warn(f"unsupported sensor '{self.sensor}'")
            return self._none_metrics()

        try:
            if sensor == "ina219":
                input_v, input_a, input_w = self._read_ina219()
            else:
                input_v, input_a, input_w = self._read_ina260()
        except Exception as exc:
            self._bus = None
            self._warn(f"{sensor} read failed on bus={self.bus_number} addr=0x{self.address:02x}: {exc}")
            return self._none_metrics()

        return {
            "power_input_v": round(float(input_v), 3),
            "power_input_a": round(float(input_a), 3),
            "power_input_w": round(float(input_w), 3),
            "power_source": _infer_power_source(input_v=input_v, solar_min_v=self.source_solar_min_v),
        }
