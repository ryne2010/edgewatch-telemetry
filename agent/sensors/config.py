from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from .base import SafeSensorBackend, SensorBackend
from .backends import (
    CompositeSensorBackend,
    MockSensorBackend,
    PlaceholderSensorBackend,
    RpiI2CSensorBackend,
)

_VALID_BACKENDS = {"mock", "rpi_i2c", "rpi_adc", "derived", "composite"}
_METRIC_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ALLOWED_UNITS = {"pct", "psi", "c", "v", "dbm", "gpm", "bool"}

_PLACEHOLDER_KEYS: dict[str, frozenset[str]] = {
    "rpi_adc": frozenset(
        {
            "water_pressure_psi",
            "oil_pressure_psi",
            "oil_level_pct",
            "drip_oil_level_pct",
        }
    ),
    "derived": frozenset({"oil_life_pct"}),
}


class SensorConfigError(ValueError):
    """Invalid sensor configuration."""


@dataclass(frozen=True)
class ChannelConfig:
    metric_key: str
    channel: int | None = None
    kind: str | None = None
    unit: str | None = None
    shunt_ohms: float | None = None
    scale_from: tuple[float, float] | None = None
    scale_to: tuple[float, float] | None = None


@dataclass(frozen=True)
class SensorConfig:
    backend: str
    backends: tuple["SensorConfig", ...] = ()
    channels: Mapping[str, ChannelConfig] = field(default_factory=dict)
    scaling: Mapping[str, float] = field(default_factory=dict)
    backend_settings: Mapping[str, Any] = field(default_factory=dict)


def load_sensor_config_from_env() -> SensorConfig:
    config_path = os.getenv("SENSOR_CONFIG_PATH")
    override_backend = os.getenv("SENSOR_BACKEND")

    raw: dict[str, Any]
    origin = "env defaults"
    if config_path:
        path = Path(config_path).expanduser()
        if not path.exists():
            raise SensorConfigError(f"SENSOR_CONFIG_PATH does not exist: {path}")
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise SensorConfigError(f"failed to parse sensor config at {path}: {exc}") from exc
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            raise SensorConfigError(f"sensor config at {path} must be a YAML object")
        raw = dict(loaded)
        origin = str(path)
    else:
        raw = {"backend": "mock"}

    if override_backend:
        raw["backend"] = override_backend
        if override_backend != "composite":
            raw.pop("backends", None)

    return parse_sensor_config(raw, origin=origin)


def parse_sensor_config(raw: Mapping[str, Any], *, origin: str) -> SensorConfig:
    backend = _require_backend(raw, origin=origin)

    if backend == "composite":
        children_raw = raw.get("backends")
        if not isinstance(children_raw, list) or not children_raw:
            raise SensorConfigError(f"{origin}: backend 'composite' requires non-empty 'backends' list")
        children: list[SensorConfig] = []
        for idx, item in enumerate(children_raw):
            if not isinstance(item, dict):
                raise SensorConfigError(f"{origin}: backends[{idx}] must be an object")
            children.append(parse_sensor_config(item, origin=f"{origin}:backends[{idx}]"))
        parsed_children: tuple[SensorConfig, ...] = tuple(children)
    else:
        if "backends" in raw and raw.get("backends"):
            raise SensorConfigError(f"{origin}: backend '{backend}' cannot declare 'backends'")
        parsed_children = ()

    channels = _parse_channels(raw.get("channels"), origin=origin)
    scaling = _parse_scaling(raw.get("scaling"), origin=origin)
    backend_settings = _extract_backend_settings(raw)

    return SensorConfig(
        backend=backend,
        backends=parsed_children,
        channels=channels,
        scaling=scaling,
        backend_settings=backend_settings,
    )


def build_sensor_backend(*, device_id: str, config: SensorConfig) -> SensorBackend:
    backend = _build_backend(device_id=device_id, config=config)
    return SafeSensorBackend(backend_name=config.backend, backend=backend)


def _build_backend(*, device_id: str, config: SensorConfig) -> SensorBackend:
    if config.backend == "mock":
        return MockSensorBackend(device_id=device_id)

    if config.backend == "rpi_i2c":
        return _build_rpi_i2c_backend(config=config)

    if config.backend == "composite":
        children = [_build_backend(device_id=device_id, config=child) for child in config.backends]
        return CompositeSensorBackend(backends=children)

    default_keys = _PLACEHOLDER_KEYS.get(config.backend, frozenset())
    configured_keys = frozenset(config.channels.keys())
    return PlaceholderSensorBackend(
        backend_name=config.backend,
        metric_keys=default_keys | configured_keys,
    )


def _extract_backend_settings(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    ignored = {"backend", "backends", "channels", "scaling"}
    return {k: v for k, v in raw.items() if k not in ignored}


def _require_backend(raw: Mapping[str, Any], *, origin: str) -> str:
    value = raw.get("backend")
    if not isinstance(value, str) or not value.strip():
        raise SensorConfigError(f"{origin}: missing required 'backend' string")
    backend = value.strip()
    if backend not in _VALID_BACKENDS:
        allowed = ", ".join(sorted(_VALID_BACKENDS))
        raise SensorConfigError(f"{origin}: unsupported backend '{backend}' (allowed: {allowed})")
    return backend


def _parse_channels(raw_channels: Any, *, origin: str) -> Mapping[str, ChannelConfig]:
    if raw_channels is None:
        return {}
    if not isinstance(raw_channels, dict):
        raise SensorConfigError(f"{origin}: 'channels' must be an object")

    channels: dict[str, ChannelConfig] = {}
    for raw_key, raw_value in raw_channels.items():
        if not isinstance(raw_key, str) or not _METRIC_KEY_RE.fullmatch(raw_key):
            raise SensorConfigError(f"{origin}: invalid metric key '{raw_key}' in channels")
        if not isinstance(raw_value, dict):
            raise SensorConfigError(f"{origin}: channels.{raw_key} must be an object")

        unit_raw = raw_value.get("unit")
        if unit_raw is not None:
            if not isinstance(unit_raw, str) or unit_raw not in _ALLOWED_UNITS:
                allowed = ", ".join(sorted(_ALLOWED_UNITS))
                raise SensorConfigError(f"{origin}: channels.{raw_key}.unit must be one of: {allowed}")

        channel_raw = raw_value.get("channel")
        channel: int | None
        if channel_raw is None:
            channel = None
        elif isinstance(channel_raw, int):
            channel = channel_raw
        else:
            raise SensorConfigError(f"{origin}: channels.{raw_key}.channel must be an integer")

        scale_from, scale_to = _parse_scale(raw_value.get("scale"), path=f"{origin}:channels.{raw_key}.scale")

        shunt_ohms_raw = raw_value.get("shunt_ohms")
        if shunt_ohms_raw is None:
            shunt_ohms = None
        else:
            shunt_ohms = _as_float(
                shunt_ohms_raw,
                message=f"{origin}: channels.{raw_key}.shunt_ohms must be numeric",
            )

        kind_raw = raw_value.get("kind")
        if kind_raw is not None and not isinstance(kind_raw, str):
            raise SensorConfigError(f"{origin}: channels.{raw_key}.kind must be a string")

        channels[raw_key] = ChannelConfig(
            metric_key=raw_key,
            channel=channel,
            kind=kind_raw,
            unit=unit_raw,
            shunt_ohms=shunt_ohms,
            scale_from=scale_from,
            scale_to=scale_to,
        )
    return channels


def _parse_scaling(raw_scaling: Any, *, origin: str) -> Mapping[str, float]:
    if raw_scaling is None:
        return {}
    if not isinstance(raw_scaling, dict):
        raise SensorConfigError(f"{origin}: 'scaling' must be an object")

    scaling: dict[str, float] = {}
    for key, value in raw_scaling.items():
        if not isinstance(key, str) or not _METRIC_KEY_RE.fullmatch(key):
            raise SensorConfigError(f"{origin}: invalid scaling key '{key}'")
        scaling[key] = _as_float(value, message=f"{origin}: scaling.{key} must be numeric")
    return scaling


def _parse_scale(value: Any, *, path: str) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    if value is None:
        return None, None
    if not isinstance(value, dict):
        raise SensorConfigError(f"{path} must be an object")

    raw_from = value.get("from")
    raw_to = value.get("to")
    if raw_from is None and raw_to is None:
        return None, None
    if raw_from is None or raw_to is None:
        raise SensorConfigError(f"{path} requires both 'from' and 'to'")
    return _parse_range(raw_from, path=f"{path}.from"), _parse_range(raw_to, path=f"{path}.to")


def _parse_range(value: Any, *, path: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise SensorConfigError(f"{path} must be a 2-element list")
    left = _as_float(value[0], message=f"{path}[0] must be numeric")
    right = _as_float(value[1], message=f"{path}[1] must be numeric")
    return left, right


def _as_float(value: Any, *, message: str) -> float:
    if isinstance(value, bool):
        raise SensorConfigError(message)
    if isinstance(value, (int, float)):
        return float(value)
    raise SensorConfigError(message)


def _build_rpi_i2c_backend(*, config: SensorConfig) -> RpiI2CSensorBackend:
    i2c_config = _mapping_value(config.backend_settings.get("rpi_i2c"))

    sensor = _as_string(
        config.backend_settings.get("sensor", i2c_config.get("sensor", "bme280")),
        message="rpi_i2c sensor must be a string",
    ).strip()

    bus_number = _as_int(
        config.backend_settings.get("bus", i2c_config.get("bus", 1)),
        message="rpi_i2c bus must be an integer",
    )
    if bus_number < 0:
        raise SensorConfigError("rpi_i2c bus must be >= 0")

    address = _parse_i2c_address(config.backend_settings.get("address", i2c_config.get("address", 0x76)))

    warning_interval_s = _as_float(
        config.backend_settings.get(
            "warning_interval_s",
            i2c_config.get("warning_interval_s", 300.0),
        ),
        message="rpi_i2c warning_interval_s must be numeric",
    )
    if warning_interval_s < 0:
        raise SensorConfigError("rpi_i2c warning_interval_s must be >= 0")

    return RpiI2CSensorBackend(
        sensor=sensor,
        bus_number=bus_number,
        address=address,
        warning_interval_s=warning_interval_s,
    )


def _parse_i2c_address(value: Any) -> int:
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip().lower()
        try:
            if raw.startswith("0x"):
                parsed = int(raw, 16)
            else:
                parsed = int(raw, 10)
        except ValueError as exc:
            raise SensorConfigError("rpi_i2c address must be an integer or hex string") from exc
    else:
        raise SensorConfigError("rpi_i2c address must be an integer or hex string")

    if parsed < 0 or parsed > 0x7F:
        raise SensorConfigError("rpi_i2c address must be between 0x00 and 0x7f")
    return parsed


def _as_int(value: Any, *, message: str) -> int:
    if isinstance(value, bool):
        raise SensorConfigError(message)
    if isinstance(value, int):
        return value
    raise SensorConfigError(message)


def _as_string(value: Any, *, message: str) -> str:
    if isinstance(value, str):
        return value
    raise SensorConfigError(message)


def _mapping_value(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}
