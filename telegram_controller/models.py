from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from types import MappingProxyType
from typing import Any, Mapping


class Role(IntEnum):
    VIEWER = 10
    OPERATOR = 20
    ADMIN = 30

    @classmethod
    def parse(cls, value: str) -> "Role":
        try:
            return cls[value.upper()]
        except KeyError as exc:
            raise ValueError(f"unknown role: {value}") from exc


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: Role
    fleets: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Device:
    device_id: str
    fleet_id: str
    host: str
    transport: str = "direct"
    capabilities: frozenset[str] = frozenset()
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class Fleet:
    fleet_id: str
    device_ids: tuple[str, ...]
    topic_id: str | None = None
    canary_device_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DispatchEnvelope:
    version: int
    command_id: str
    device_id: str
    issued_at: str
    expires_at: str
    type: str
    args: Mapping[str, Any]


@dataclass(frozen=True)
class DispatchResult:
    ok: bool
    summary: str
    retryable: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)
