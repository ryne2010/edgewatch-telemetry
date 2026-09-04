from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping


_DEVICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_APPLICATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$")
_HEX = re.compile(r"^[0-9a-fA-F]+$")


class IdentityConfigError(ValueError):
    """Raised when the closed LoRaWAN identity inventory is invalid."""


def _closed_mapping(value: object, *, where: str, allowed: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise IdentityConfigError(f"{where} must be a mapping")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise IdentityConfigError(f"unknown key(s) in {where}: {', '.join(unknown)}")
    return value


def _required_string(value: object, *, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IdentityConfigError(f"{where} must be a non-empty string")
    return value.strip()


def _hex_string(value: object, *, where: str, length: int) -> str:
    candidate = _required_string(value, where=where).lower()
    if len(candidate) != length or _HEX.fullmatch(candidate) is None:
        raise IdentityConfigError(f"{where} must contain exactly {length} hexadecimal characters")
    return candidate


def _port(value: object, *, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 223:
        raise IdentityConfigError(f"{where} must be an integer from 1 through 223")
    return value


@dataclass(frozen=True)
class DeviceIdentity:
    device_id: str
    application_id: str
    dev_eui: str
    join_eui: str
    app_key: str = field(repr=False)
    wake_key: str = field(repr=False)
    uplink_f_port: int = 10
    wake_f_port: int = 11

    def __post_init__(self) -> None:
        device_id = _required_string(self.device_id, where="device_id")
        if _DEVICE_ID.fullmatch(device_id) is None:
            raise IdentityConfigError("device_id contains unsupported characters")
        application_id = _required_string(self.application_id, where="application_id")
        if _APPLICATION_ID.fullmatch(application_id) is None:
            raise IdentityConfigError("application_id contains unsupported characters")
        object.__setattr__(self, "device_id", device_id)
        object.__setattr__(self, "application_id", application_id)
        object.__setattr__(self, "dev_eui", _hex_string(self.dev_eui, where="dev_eui", length=16))
        object.__setattr__(self, "join_eui", _hex_string(self.join_eui, where="join_eui", length=16))
        object.__setattr__(self, "app_key", _hex_string(self.app_key, where="app_key", length=32))
        object.__setattr__(self, "wake_key", _hex_string(self.wake_key, where="wake_key", length=64))
        object.__setattr__(
            self,
            "uplink_f_port",
            _port(self.uplink_f_port, where="uplink_f_port"),
        )
        object.__setattr__(self, "wake_f_port", _port(self.wake_f_port, where="wake_f_port"))
        if self.uplink_f_port == self.wake_f_port:
            raise IdentityConfigError("uplink_f_port and wake_f_port must be distinct")

    @property
    def wake_key_bytes(self) -> bytes:
        return bytes.fromhex(self.wake_key)


class DeviceRegistry:
    """Immutable one-to-one mapping between OTAA identity and EdgeWatch identity."""

    def __init__(self, devices: Iterable[DeviceIdentity]):
        by_eui: dict[str, DeviceIdentity] = {}
        by_id: dict[str, DeviceIdentity] = {}
        app_keys: set[str] = set()
        wake_keys: set[str] = set()
        for device in devices:
            if not isinstance(device, DeviceIdentity):
                raise IdentityConfigError("registry entries must be DeviceIdentity values")
            if device.dev_eui in by_eui:
                raise IdentityConfigError("DevEUI values must be unique")
            if device.device_id in by_id:
                raise IdentityConfigError("device_id values must be unique")
            if device.app_key in app_keys:
                raise IdentityConfigError("OTAA AppKey values must be unique")
            if device.wake_key in wake_keys:
                raise IdentityConfigError("wake authentication keys must be unique")
            by_eui[device.dev_eui] = device
            by_id[device.device_id] = device
            app_keys.add(device.app_key)
            wake_keys.add(device.wake_key)
        if not by_eui:
            raise IdentityConfigError("at least one LoRaWAN device identity is required")
        self._by_eui = MappingProxyType(by_eui)
        self._by_id = MappingProxyType(by_id)

    @classmethod
    def from_mapping(cls, raw: object) -> "DeviceRegistry":
        root = _closed_mapping(raw, where="lorawan", allowed={"devices"})
        devices_raw = root.get("devices")
        if not isinstance(devices_raw, Mapping) or not devices_raw:
            raise IdentityConfigError("lorawan.devices must be a non-empty mapping")
        devices: list[DeviceIdentity] = []
        for device_id, value in devices_raw.items():
            if not isinstance(device_id, str):
                raise IdentityConfigError("lorawan.devices keys must be strings")
            item = _closed_mapping(
                value,
                where=f"lorawan.devices.{device_id}",
                allowed={
                    "application_id",
                    "dev_eui",
                    "join_eui",
                    "app_key",
                    "wake_key",
                    "uplink_f_port",
                    "wake_f_port",
                },
            )
            devices.append(
                DeviceIdentity(
                    device_id=device_id,
                    application_id=_required_string(
                        item.get("application_id"),
                        where=f"lorawan.devices.{device_id}.application_id",
                    ),
                    dev_eui=_required_string(
                        item.get("dev_eui"), where=f"lorawan.devices.{device_id}.dev_eui"
                    ),
                    join_eui=_required_string(
                        item.get("join_eui"), where=f"lorawan.devices.{device_id}.join_eui"
                    ),
                    app_key=_required_string(
                        item.get("app_key"), where=f"lorawan.devices.{device_id}.app_key"
                    ),
                    wake_key=_required_string(
                        item.get("wake_key"), where=f"lorawan.devices.{device_id}.wake_key"
                    ),
                    uplink_f_port=_port(
                        item.get("uplink_f_port", 10),
                        where=f"lorawan.devices.{device_id}.uplink_f_port",
                    ),
                    wake_f_port=_port(
                        item.get("wake_f_port", 11),
                        where=f"lorawan.devices.{device_id}.wake_f_port",
                    ),
                )
            )
        return cls(devices)

    def by_dev_eui(self, dev_eui: str) -> DeviceIdentity:
        normalized = dev_eui.strip().lower()
        try:
            return self._by_eui[normalized]
        except KeyError as exc:
            raise IdentityConfigError("DevEUI is not present in the closed device inventory") from exc

    def by_device_id(self, device_id: str) -> DeviceIdentity:
        try:
            return self._by_id[device_id]
        except KeyError as exc:
            raise IdentityConfigError("device_id is not present in the closed device inventory") from exc

    @property
    def devices(self) -> tuple[DeviceIdentity, ...]:
        return tuple(self._by_id.values())

    @property
    def application_ids(self) -> frozenset[str]:
        return frozenset(device.application_id for device in self._by_id.values())
