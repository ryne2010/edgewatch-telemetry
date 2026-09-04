from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Mapping

from .models import Role


class CommandParseError(ValueError):
    pass


@dataclass(frozen=True)
class Command:
    scope: str
    target: str
    operation: str
    arguments: Mapping[str, Any]
    required_role: Role
    mutating: bool
    confirmation_id: str | None = None


_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DEVICE_OPS: dict[tuple[str, ...], tuple[str, Role, bool, tuple[str, ...]]] = {
    ("status",): ("status", Role.VIEWER, False, ()),
    ("health",): ("health", Role.VIEWER, False, ()),
    ("network",): ("network", Role.VIEWER, False, ()),
    ("power",): ("power", Role.VIEWER, False, ()),
    ("queue",): ("queue", Role.VIEWER, False, ()),
    ("version",): ("version", Role.VIEWER, False, ()),
    ("ota", "status"): ("ota_status", Role.VIEWER, False, ()),
    ("sample", "now"): ("sample_now", Role.OPERATOR, True, ()),
    ("sample-now",): ("sample_now", Role.OPERATOR, True, ()),
    ("sync", "now"): ("sync_now", Role.OPERATOR, True, ()),
    ("sync-now",): ("sync_now", Role.OPERATOR, True, ()),
    ("alert", "unmute"): ("alerts_unmute", Role.OPERATOR, True, ()),
    ("alerts", "unmute"): ("alerts_unmute", Role.OPERATOR, True, ()),
    ("agent", "restart"): ("agent_restart", Role.OPERATOR, True, ()),
    ("restart",): ("agent_restart", Role.OPERATOR, True, ()),
    ("reboot",): ("reboot", Role.ADMIN, True, ()),
    ("shutdown",): ("shutdown", Role.ADMIN, True, ()),
}


def parse_command(text: str) -> Command:
    if not isinstance(text, str) or len(text) > 512 or "\n" in text or "\x00" in text:
        raise CommandParseError("command must be one short line")
    try:
        words = shlex.split(text)
    except ValueError as exc:
        raise CommandParseError("invalid quoting") from exc
    if not words:
        raise CommandParseError("empty command")
    words[0] = words[0].split("@", 1)[0].lower()
    if words[0] not in {"/device", "/fleet", "/ota"}:
        raise CommandParseError("unsupported command family")
    if words[0] == "/ota":
        return _parse_ota(words)
    if len(words) < 3:
        raise CommandParseError("target and operation are required")
    scope = words[0][1:]
    target = _safe(words[1], "target")
    tail = tuple(word.lower() for word in words[2:])
    if scope == "fleet" and tail[:1] == ("confirm",):
        if len(words) != 4:
            raise CommandParseError("confirmation requires exactly one ID")
        return Command(
            scope,
            target,
            "confirm",
            MappingProxyType({}),
            Role.OPERATOR,
            True,
            _safe(words[3], "confirmation ID"),
        )
    special = _parse_special(scope, target, words[2:])
    if special is not None:
        return special
    match = _match_operation(tail)
    if match is None:
        raise CommandParseError("unsupported or malformed operation")
    key, (operation, role, mutating, argument_names) = match
    values = words[2 + len(key) :]
    if len(values) != len(argument_names):
        raise CommandParseError("wrong number of arguments")
    arguments = MappingProxyType(
        {name: _safe(value, name) for name, value in zip(argument_names, values, strict=True)}
    )
    return Command(scope, target, operation, arguments, role, mutating)


def _match_operation(tail: tuple[str, ...]):
    for key in sorted(_DEVICE_OPS, key=len, reverse=True):
        if tail[: len(key)] == key:
            return key, _DEVICE_OPS[key]
    return None


def _parse_ota(words: list[str]) -> Command:
    if len(words) < 3:
        raise CommandParseError("OTA target and operation are required")
    target = _safe(words[1], "fleet")
    operation = words[2].lower()
    if operation == "status" and len(words) == 3:
        return Command("fleet", target, "ota_status", MappingProxyType({}), Role.VIEWER, False)
    if operation == "stage" and len(words) == 4:
        return Command(
            "fleet",
            target,
            "ota_stage",
            MappingProxyType({"release_alias": _safe(words[3], "release alias")}),
            Role.ADMIN,
            True,
        )
    if operation in {"canary", "promote", "abort"} and len(words) == 4:
        return Command(
            "fleet",
            target,
            f"ota_{operation}",
            MappingProxyType({"deployment_id": _safe(words[3], "deployment ID")}),
            Role.ADMIN,
            True,
        )
    if operation == "confirm" and len(words) == 4:
        return Command(
            "fleet",
            target,
            "confirm",
            MappingProxyType({}),
            Role.ADMIN,
            True,
            _safe(words[3], "confirmation ID"),
        )
    raise CommandParseError("unsupported or malformed OTA operation")


def _safe(value: str, where: str) -> str:
    if not _SAFE.fullmatch(value):
        raise CommandParseError(f"invalid {where}")
    return value


def _parse_special(scope: str, target: str, words: list[str]) -> Command | None:
    lowered = [word.lower() for word in words]
    if lowered[:1] == ["mode"] and len(words) in {2, 3} and lowered[1] in {"active", "sleep"}:
        args: dict[str, Any] = {"mode": lowered[1]}
        if len(words) == 3:
            if lowered[1] != "sleep" or not words[2].isdigit() or not 60 <= int(words[2]) <= 31_536_000:
                raise CommandParseError("sleep interval must be between 60 and 31536000 seconds")
            args["sleep_poll_interval_s"] = int(words[2])
        return Command(scope, target, "set_operation_mode", MappingProxyType(args), Role.OPERATOR, True)
    if lowered[:1] == ["power"] and len(words) == 2 and lowered[1] in {"continuous", "eco"}:
        return Command(
            scope,
            target,
            "set_power_mode",
            MappingProxyType({"mode": lowered[1]}),
            Role.OPERATOR,
            True,
        )
    if lowered[:2] in (["power", "deep_sleep"], ["power", "deep-sleep"]):
        if len(words) != 3:
            raise CommandParseError("deep sleep requires exactly one duration")
        return Command(
            scope,
            target,
            "deep_sleep",
            MappingProxyType({"duration": _duration(words[2])}),
            Role.ADMIN,
            True,
        )
    if lowered[:2] in (["alert", "mute"], ["alerts", "mute"]) and len(words) in {3, 4}:
        args = {"until": _utc_timestamp(words[2], "mute expiry")}
        if len(words) == 4:
            args["reason"] = _safe(words[3], "mute reason")
        return Command(scope, target, "alerts_mute", MappingProxyType(args), Role.OPERATOR, True)
    return None


def _duration(value: str) -> str:
    match = re.fullmatch(r"([1-9][0-9]{0,7})([smhd])", value)
    if match is None:
        raise CommandParseError("duration must use s, m, h, or d")
    multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
    seconds = int(match.group(1)) * multiplier
    if not 60 <= seconds <= 31_536_000:
        raise CommandParseError("duration must be between 60 seconds and 365 days")
    return value


def _utc_timestamp(value: str, where: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value):
        raise CommandParseError(f"invalid {where}; expected RFC3339 UTC ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CommandParseError(f"invalid {where}; expected RFC3339 UTC ending in Z") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise CommandParseError(f"invalid {where}; expected RFC3339 UTC ending in Z")
    return value
