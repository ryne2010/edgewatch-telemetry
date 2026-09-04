"""Durable, bounded LTE power windows for an EdgeWatch field gateway.

The controller deliberately knows nothing about GPIO polarity or a modem
carrier's electrical design.  The ``systemd`` backend calls two fixed service
names.  A hardware-specific, reviewed integration owns those services and must
prove that the off service really removes modem power without back-feeding the
Pi USB rail.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


POWER_ON_UNIT = "edgewatch-lte-power-on.service"
POWER_OFF_UNIT = "edgewatch-lte-power-off.service"
ALLOWED_REASONS = frozenset({"alert", "control", "ota", "scheduled", "startup"})
_SAFE_INTERFACE = re.compile(r"[A-Za-z0-9_.:-]{1,32}\Z")
_SAFE_HOLD_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


class GatewayPowerConfigError(ValueError):
    """Raised when gateway LTE power configuration is unsafe or inconsistent."""


class GatewayPowerError(RuntimeError):
    """Raised when a requested modem power transition cannot be completed."""


@dataclass(frozen=True)
class GatewayPowerConfig:
    mode: str = "disabled"
    interval_s: int = 3600
    min_window_s: int = 60
    max_window_s: int = 300
    max_held_window_s: int = 14_400
    trigger_path: Path = Path("/var/lib/edgewatch-gateway/lte-trigger.json")
    state_path: Path = Path("/var/lib/edgewatch-gateway/lte-power-state.json")
    hold_dir: Path = Path("/var/lib/edgewatch-gateway/lte-holds")
    cellular_interface: str = "wwan0"
    transition_timeout_s: int = 120

    @property
    def enabled(self) -> bool:
        return self.mode != "disabled"

    @property
    def electrically_switched(self) -> bool:
        return self.mode == "systemd"


def _integer(raw: Mapping[str, str], key: str, default: int, *, minimum: int, maximum: int) -> int:
    value = raw.get(key, str(default)).strip()
    try:
        parsed = int(value)
    except ValueError as exc:
        raise GatewayPowerConfigError(f"{key} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise GatewayPowerConfigError(f"{key} must be between {minimum} and {maximum}")
    return parsed


def load_gateway_power_config(env: Mapping[str, str] | None = None) -> GatewayPowerConfig:
    raw = os.environ if env is None else env
    mode = raw.get("EDGEWATCH_GATEWAY_LTE_POWER_MODE", "disabled").strip().lower()
    if mode not in {"disabled", "observe", "systemd"}:
        raise GatewayPowerConfigError(
            "EDGEWATCH_GATEWAY_LTE_POWER_MODE must be disabled, observe, or systemd"
        )
    interval_s = _integer(raw, "EDGEWATCH_GATEWAY_LTE_WINDOW_INTERVAL_S", 3600, minimum=300, maximum=86400)
    min_window_s = _integer(raw, "EDGEWATCH_GATEWAY_LTE_MIN_WINDOW_S", 60, minimum=10, maximum=3600)
    max_window_s = _integer(raw, "EDGEWATCH_GATEWAY_LTE_MAX_WINDOW_S", 300, minimum=30, maximum=14400)
    if min_window_s > max_window_s:
        raise GatewayPowerConfigError("EDGEWATCH_GATEWAY_LTE_MIN_WINDOW_S must not exceed the maximum window")
    max_held_window_s = _integer(
        raw,
        "EDGEWATCH_GATEWAY_LTE_MAX_HELD_WINDOW_S",
        14_400,
        minimum=30,
        maximum=14_400,
    )
    if max_window_s > max_held_window_s:
        raise GatewayPowerConfigError(
            "EDGEWATCH_GATEWAY_LTE_MAX_WINDOW_S must not exceed the maximum held window"
        )
    interface = raw.get("CELLULAR_INTERFACE", "wwan0").strip()
    if not _SAFE_INTERFACE.fullmatch(interface):
        raise GatewayPowerConfigError("CELLULAR_INTERFACE is invalid")
    return GatewayPowerConfig(
        mode=mode,
        interval_s=interval_s,
        min_window_s=min_window_s,
        max_window_s=max_window_s,
        max_held_window_s=max_held_window_s,
        trigger_path=Path(
            raw.get(
                "EDGEWATCH_GATEWAY_LTE_TRIGGER_PATH",
                "/var/lib/edgewatch-gateway/lte-trigger.json",
            )
        ),
        state_path=Path(
            raw.get(
                "EDGEWATCH_GATEWAY_LTE_POWER_STATE_PATH",
                "/var/lib/edgewatch-gateway/lte-power-state.json",
            )
        ),
        hold_dir=Path(
            raw.get(
                "EDGEWATCH_GATEWAY_LTE_HOLD_DIR",
                "/var/lib/edgewatch-gateway/lte-holds",
            )
        ),
        cellular_interface=interface,
        transition_timeout_s=_integer(
            raw, "EDGEWATCH_GATEWAY_LTE_TRANSITION_TIMEOUT_S", 120, minimum=10, maximum=600
        ),
    )


class LtePowerBackend(Protocol):
    def power_on(self) -> None: ...

    def power_off(self) -> None: ...


class ObserveOnlyPowerBackend:
    """Exercise scheduling without claiming that the modem is electrically off."""

    def power_on(self) -> None:
        return None

    def power_off(self) -> None:
        return None


class SystemdLtePowerBackend:
    """Run only the two fixed carrier-integration service units."""

    def __init__(self, *, timeout_s: int = 120, run_command=subprocess.run):
        self.timeout_s = timeout_s
        self._run_command = run_command

    def _start(self, unit: str) -> None:
        try:
            completed = self._run_command(
                ["/usr/bin/sudo", "-n", "/usr/bin/systemctl", "start", unit],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GatewayPowerError(f"LTE power transition failed for {unit}") from exc
        if completed.returncode != 0:
            raise GatewayPowerError(f"LTE power transition failed for {unit}")

    def power_on(self) -> None:
        self._start(POWER_ON_UNIT)

    def power_off(self) -> None:
        self._start(POWER_OFF_UNIT)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    finally:
        temp_path.unlink(missing_ok=True)


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        if path.is_symlink() or not path.is_file():
            raise GatewayPowerError("gateway LTE power state must be a regular file")
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise GatewayPowerError("gateway LTE power state must have mode 0600 or stricter")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GatewayPowerError("gateway LTE power state is unreadable") from exc
    if not isinstance(value, dict):
        raise GatewayPowerError("gateway LTE power state is invalid")
    return value


class GatewayLtePowerController:
    """Persist and enforce one bounded LTE network window at a time."""

    def __init__(
        self,
        config: GatewayPowerConfig,
        *,
        backend: LtePowerBackend | None = None,
        clock=time.time,
    ):
        self.config = config
        self.clock = clock
        if backend is None:
            backend = (
                SystemdLtePowerBackend(timeout_s=config.transition_timeout_s)
                if config.mode == "systemd"
                else ObserveOnlyPowerBackend()
            )
        self.backend = backend

    def snapshot(self) -> dict[str, Any]:
        return _read_state(self.config.state_path)

    def request_immediate(self, reason: str, *, requested_at: float | None = None) -> None:
        if reason not in ALLOWED_REASONS - {"scheduled"}:
            raise ValueError("unsupported LTE window reason")
        now = self.clock() if requested_at is None else requested_at
        _write_json(
            self.config.trigger_path,
            {"reason": reason, "requested_at": float(now), "schema_version": 1},
        )

    def acquire_hold(self, name: str, *, ttl_s: int = 120) -> None:
        """Keep an active window open for one bounded cross-process operation."""

        if not self.config.enabled:
            return
        if _SAFE_HOLD_NAME.fullmatch(name) is None:
            raise ValueError("LTE window hold name is invalid")
        if isinstance(ttl_s, bool) or not isinstance(ttl_s, int) or not 5 <= ttl_s <= 14_400:
            raise ValueError("LTE window hold ttl_s must be within 5..14400")
        current = self.clock()
        expires_at = current + ttl_s
        state = self.snapshot()
        started_at = state.get("last_window_started_at")
        if (
            state.get("active") is True
            and isinstance(started_at, (int, float))
            and not isinstance(started_at, bool)
        ):
            expires_at = min(
                expires_at,
                float(started_at) + self.config.max_held_window_s,
            )
        _write_json(
            self.config.hold_dir / f"{name}.json",
            {
                "expires_at": float(expires_at),
                "name": name,
                "schema_version": 1,
            },
        )

    def release_hold(self, name: str) -> None:
        if not self.config.enabled:
            return
        if _SAFE_HOLD_NAME.fullmatch(name) is None:
            raise ValueError("LTE window hold name is invalid")
        path = self.config.hold_dir / f"{name}.json"
        try:
            path.unlink()
        except FileNotFoundError:
            return
        _fsync_directory(path.parent)

    def has_active_holds(self, *, now: float | None = None) -> bool:
        if not self.config.enabled or not self.config.hold_dir.exists():
            return False
        if self.config.hold_dir.is_symlink() or not self.config.hold_dir.is_dir():
            raise GatewayPowerError("gateway LTE hold path must be a real directory")
        current = self.clock() if now is None else now
        active = False
        for path in sorted(self.config.hold_dir.iterdir()):
            if not path.name.endswith(".json") or _SAFE_HOLD_NAME.fullmatch(path.stem) is None:
                raise GatewayPowerError("gateway LTE hold directory contains an invalid entry")
            hold = _read_state(path)
            expires_at = hold.get("expires_at")
            if (
                hold.get("schema_version") != 1
                or hold.get("name") != path.stem
                or not isinstance(expires_at, (int, float))
                or isinstance(expires_at, bool)
            ):
                raise GatewayPowerError("gateway LTE hold is invalid")
            if float(expires_at) > current:
                active = True
                continue
            path.unlink()
            _fsync_directory(path.parent)
        return active

    def next_reason(self, *, now: float | None = None) -> str | None:
        if not self.config.enabled:
            return None
        current = self.clock() if now is None else now
        if self.config.trigger_path.exists():
            trigger = _read_state(self.config.trigger_path)
            reason = trigger.get("reason")
            requested_at = trigger.get("requested_at")
            if reason not in ALLOWED_REASONS - {"scheduled"} or not isinstance(requested_at, (int, float)):
                raise GatewayPowerError("gateway LTE trigger is invalid")
            return str(reason)
        state = self.snapshot()
        if state.get("active") is True:
            return str(state.get("reason", "scheduled"))
        last_started = state.get("last_window_started_at")
        if (
            not isinstance(last_started, (int, float))
            or current - float(last_started) >= self.config.interval_s
        ):
            return "scheduled"
        return None

    def seconds_until_due(self, *, now: float | None = None) -> float:
        if not self.config.enabled or self.config.trigger_path.exists():
            return 0.0
        current = self.clock() if now is None else now
        last_started = self.snapshot().get("last_window_started_at")
        if not isinstance(last_started, (int, float)):
            return 0.0
        return max(0.0, float(last_started) + self.config.interval_s - current)

    def open_window(self, reason: str, *, now: float | None = None) -> dict[str, Any]:
        if reason not in ALLOWED_REASONS:
            raise ValueError("unsupported LTE window reason")
        if not self.config.enabled:
            raise GatewayPowerError("gateway LTE power scheduling is disabled")
        current = self.clock() if now is None else now
        prior = self.snapshot()
        if prior.get("active") is True:
            return prior
        if prior.get("transition") in {"opening", "closing"}:
            raise GatewayPowerError("gateway LTE transition requires restart recovery")
        opening = {
            "active": False,
            "transition": "opening",
            "electrically_switched": self.config.electrically_switched,
            "last_window_started_at": float(current),
            "reason": reason,
            "schema_version": 1,
        }
        _write_json(self.config.state_path, opening)
        try:
            self.backend.power_on()
        except Exception:
            try:
                self.backend.power_off()
            except Exception:
                # The durable opening record intentionally remains. A service
                # restart will retry the fixed power-off action before opening
                # another window.
                raise
            _write_json(
                self.config.state_path,
                {
                    "active": False,
                    "electrically_switched": self.config.electrically_switched,
                    "last_window_closed_at": float(current),
                    "last_window_started_at": float(current),
                    "last_window_reason": reason,
                    "schema_version": 1,
                },
            )
            raise
        state = {
            "active": True,
            "transition": "active",
            "electrically_switched": self.config.electrically_switched,
            "last_window_started_at": float(current),
            "minimum_close_at": float(current + self.config.min_window_s),
            "must_close_at": float(current + self.config.max_window_s),
            "held_must_close_at": float(current + self.config.max_held_window_s),
            "reason": reason,
            "schema_version": 1,
        }
        _write_json(self.config.state_path, state)
        if self.config.trigger_path.exists():
            self.config.trigger_path.unlink()
            _fsync_directory(self.config.trigger_path.parent)
        return state

    def should_close(self, *, busy: bool, now: float | None = None) -> bool:
        state = self.snapshot()
        if state.get("active") is not True:
            return False
        current = self.clock() if now is None else now
        minimum = state.get("minimum_close_at")
        maximum = state.get("must_close_at")
        held_maximum = state.get("held_must_close_at")
        if (
            not isinstance(minimum, (int, float))
            or isinstance(minimum, bool)
            or not isinstance(maximum, (int, float))
            or isinstance(maximum, bool)
            or not isinstance(held_maximum, (int, float))
            or isinstance(held_maximum, bool)
        ):
            raise GatewayPowerError("active gateway LTE power state is incomplete")
        if current >= float(held_maximum):
            return True
        active_hold = self.has_active_holds(now=current)
        if current >= float(maximum):
            return not active_hold
        return not busy and not active_hold and current >= float(minimum)

    def close_window(self, *, now: float | None = None) -> dict[str, Any]:
        prior = self.snapshot()
        if prior.get("active") is not True:
            return prior
        closing = dict(prior)
        closing["transition"] = "closing"
        _write_json(self.config.state_path, closing)
        self.backend.power_off()
        current = self.clock() if now is None else now
        state = {
            "active": False,
            "electrically_switched": self.config.electrically_switched,
            "last_window_closed_at": float(current),
            "last_window_started_at": prior.get("last_window_started_at"),
            "last_window_reason": prior.get("reason"),
            "schema_version": 1,
        }
        _write_json(self.config.state_path, state)
        return state

    def recover_interrupted_window(self, *, now: float | None = None) -> bool:
        """Force a stale persisted window closed before normal scheduling resumes."""

        state = self.snapshot()
        if state.get("active") is not True and state.get("transition") not in {
            "opening",
            "closing",
        }:
            return False
        self.backend.power_off()
        current = self.clock() if now is None else now
        _write_json(
            self.config.state_path,
            {
                "active": False,
                "electrically_switched": self.config.electrically_switched,
                "last_window_closed_at": float(current),
                "last_window_started_at": state.get("last_window_started_at"),
                "last_window_reason": state.get("reason", state.get("last_window_reason")),
                "schema_version": 1,
            },
        )
        self.request_immediate("startup", requested_at=current)
        return True
