from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable

from ..base import Metrics

_BME280_CHIP_ID = 0x60
_REG_CHIP_ID = 0xD0
_REG_CTRL_HUM = 0xF2
_REG_CTRL_MEAS = 0xF4
_REG_CONFIG = 0xF5
_REG_CALIB_TP = 0x88
_REG_CALIB_H1 = 0xA1
_REG_CALIB_H = 0xE1
_REG_RAW = 0xF7


@runtime_checkable
class I2CBus(Protocol):
    def read_byte_data(self, i2c_addr: int, register: int, /) -> int: ...

    def write_byte_data(self, i2c_addr: int, register: int, value: int, /) -> None: ...

    def read_i2c_block_data(self, i2c_addr: int, register: int, length: int, /) -> list[int]: ...


@runtime_checkable
class TemperatureHumidityReader(Protocol):
    def read_temperature_humidity(self) -> tuple[float, float]: ...


def open_smbus(bus_number: int) -> I2CBus:
    try:
        import smbus2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "SENSOR_BACKEND=rpi_i2c requires smbus2 (install on Pi: pip install smbus2)"
        ) from exc
    return smbus2.SMBus(bus_number)


@dataclass(frozen=True)
class BME280Calibration:
    dig_t1: int
    dig_t2: int
    dig_t3: int
    dig_h1: int
    dig_h2: int
    dig_h3: int
    dig_h4: int
    dig_h5: int
    dig_h6: int


def compensate_temperature_c(*, adc_t: int, calib: BME280Calibration) -> tuple[float, float]:
    var1 = (adc_t / 16384.0 - calib.dig_t1 / 1024.0) * calib.dig_t2
    var2 = ((adc_t / 131072.0 - calib.dig_t1 / 8192.0) ** 2) * calib.dig_t3
    t_fine = var1 + var2
    return t_fine / 5120.0, t_fine


def compensate_humidity_pct(*, adc_h: int, t_fine: float, calib: BME280Calibration) -> float:
    var_h = t_fine - 76800.0
    var_h = (adc_h - (calib.dig_h4 * 64.0 + calib.dig_h5 / 16384.0 * var_h)) * (
        calib.dig_h2
        / 65536.0
        * (1.0 + calib.dig_h6 / 67108864.0 * var_h * (1.0 + calib.dig_h3 / 67108864.0 * var_h))
    )
    var_h = var_h * (1.0 - calib.dig_h1 * var_h / 524288.0)
    if var_h < 0.0:
        return 0.0
    if var_h > 100.0:
        return 100.0
    return var_h


def _u16_le(low: int, high: int) -> int:
    return (high << 8) | low


def _s16_le(low: int, high: int) -> int:
    value = _u16_le(low, high)
    if value >= 0x8000:
        value -= 0x10000
    return value


def _s8(value: int) -> int:
    return value - 256 if value >= 128 else value


def _s12(value: int) -> int:
    return value - 4096 if value & 0x800 else value


@dataclass
class BME280Reader:
    bus: I2CBus
    address: int
    _configured: bool = field(default=False, init=False, repr=False)
    _calibration: BME280Calibration | None = field(default=None, init=False, repr=False)

    def _configure_sensor(self) -> None:
        if self._configured:
            return
        chip_id = self.bus.read_byte_data(self.address, _REG_CHIP_ID)
        if chip_id != _BME280_CHIP_ID:
            raise RuntimeError(f"unexpected BME280 chip id 0x{chip_id:02x}")
        self.bus.write_byte_data(self.address, _REG_CTRL_HUM, 0x01)  # humidity oversampling x1
        self.bus.write_byte_data(
            self.address, _REG_CTRL_MEAS, 0x27
        )  # temp/pressure oversampling x1, normal mode
        self.bus.write_byte_data(self.address, _REG_CONFIG, 0xA0)  # standby 1000ms, filter off
        self._configured = True

    def _load_calibration(self) -> BME280Calibration:
        if self._calibration is not None:
            return self._calibration

        calib_tp = self.bus.read_i2c_block_data(self.address, _REG_CALIB_TP, 6)
        if len(calib_tp) != 6:
            raise RuntimeError("failed to read BME280 temp calibration bytes")

        dig_t1 = _u16_le(calib_tp[0], calib_tp[1])
        dig_t2 = _s16_le(calib_tp[2], calib_tp[3])
        dig_t3 = _s16_le(calib_tp[4], calib_tp[5])

        dig_h1 = self.bus.read_byte_data(self.address, _REG_CALIB_H1)
        calib_h = self.bus.read_i2c_block_data(self.address, _REG_CALIB_H, 7)
        if len(calib_h) != 7:
            raise RuntimeError("failed to read BME280 humidity calibration bytes")

        dig_h2 = _s16_le(calib_h[0], calib_h[1])
        dig_h3 = calib_h[2]
        dig_h4 = _s12((calib_h[3] << 4) | (calib_h[4] & 0x0F))
        dig_h5 = _s12((calib_h[5] << 4) | (calib_h[4] >> 4))
        dig_h6 = _s8(calib_h[6])

        self._calibration = BME280Calibration(
            dig_t1=dig_t1,
            dig_t2=dig_t2,
            dig_t3=dig_t3,
            dig_h1=dig_h1,
            dig_h2=dig_h2,
            dig_h3=dig_h3,
            dig_h4=dig_h4,
            dig_h5=dig_h5,
            dig_h6=dig_h6,
        )
        return self._calibration

    def read_temperature_humidity(self) -> tuple[float, float]:
        self._configure_sensor()
        calib = self._load_calibration()

        raw = self.bus.read_i2c_block_data(self.address, _REG_RAW, 8)
        if len(raw) != 8:
            raise RuntimeError("failed to read BME280 raw measurement bytes")

        adc_t = (raw[3] << 12) | (raw[4] << 4) | (raw[5] >> 4)
        adc_h = (raw[6] << 8) | raw[7]

        temperature_c, t_fine = compensate_temperature_c(adc_t=adc_t, calib=calib)
        humidity_pct = compensate_humidity_pct(adc_h=adc_h, t_fine=t_fine, calib=calib)
        return temperature_c, humidity_pct


@dataclass
class RpiI2CSensorBackend:
    sensor: str = "bme280"
    bus_number: int = 1
    address: int = 0x76
    warning_interval_s: float = 300.0
    bus_factory: Callable[[int], I2CBus] = open_smbus
    reader_factory: Callable[[I2CBus, int], TemperatureHumidityReader] = BME280Reader
    monotonic: Callable[[], float] = time.monotonic
    metric_keys: frozenset[str] = field(default_factory=lambda: frozenset({"temperature_c", "humidity_pct"}))
    _sensor_handle: TemperatureHumidityReader | None = field(default=None, init=False, repr=False)
    _last_warning_at: float | None = field(default=None, init=False, repr=False)

    def _warn(self, message: str) -> None:
        now = self.monotonic()
        if self._last_warning_at is None or (now - self._last_warning_at) >= self.warning_interval_s:
            print(f"[edgewatch-agent] rpi_i2c warning: {message}")
            self._last_warning_at = now

    def _none_metrics(self) -> Metrics:
        return {"temperature_c": None, "humidity_pct": None}

    def _get_reader(self) -> TemperatureHumidityReader:
        if self._sensor_handle is not None:
            return self._sensor_handle
        bus = self.bus_factory(self.bus_number)
        self._sensor_handle = self.reader_factory(bus, self.address)
        return self._sensor_handle

    def read_metrics(self) -> Metrics:
        if self.sensor != "bme280":
            self._warn(f"unsupported sensor '{self.sensor}'")
            return self._none_metrics()

        try:
            reader = self._get_reader()
            temperature_c, humidity_pct = reader.read_temperature_humidity()
        except Exception as exc:
            self._sensor_handle = None
            self._warn(f"BME280 read failed on bus={self.bus_number} addr=0x{self.address:02x}: {exc}")
            return self._none_metrics()

        if humidity_pct < 0.0:
            humidity_pct = 0.0
        if humidity_pct > 100.0:
            humidity_pct = 100.0
        return {
            "temperature_c": round(float(temperature_c), 1),
            "humidity_pct": round(float(humidity_pct), 1),
        }
