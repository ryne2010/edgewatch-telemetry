from __future__ import annotations

import errno
import fcntl
import importlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


PROTOCOL_VERSION = 1
MAX_ENVELOPE_BYTES = 16 * 1024
_ENVELOPE_KEYS = {"version", "command_id", "device_id", "issued_at", "expires_at", "type", "args"}
_SAFE_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SAFE_REASON = re.compile(r"\A[\x20-\x7e]{1,240}\Z")
_OPERATION_MODES = {"active", "sleep"}
_POWER_MODES = {"continuous", "eco", "deep_sleep"}
_VIEW_COMMANDS = {"status", "health", "network", "power", "queue", "version", "ota_status"}
_REQUEST_COMMANDS = {"sample_now", "sync_now"}
_SYSTEM_COMMANDS = {"agent_restart", "reboot", "shutdown"}
_OTA_COMMANDS = {"ota_stage", "ota_canary", "ota_promote", "ota_abort"}
_DIRECT_MODE_COMMANDS = {
    "mode_active",
    "mode_sleep",
    "power_continuous",
    "power_eco",
    "deep_sleep",
    "alert_mute",
    "alert_unmute",
}


class LocalControlError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CommandEnvelope:
    command_id: str
    device_id: str
    issued_at: datetime
    expires_at: datetime
    command_type: str
    args: dict[str, Any]


@dataclass(frozen=True)
class LocalAgentControl:
    operation_mode: str | None
    sleep_poll_interval_s: int | None
    runtime_power_mode: str | None
    alerts_muted_until: str | None
    sample_request_ids: tuple[str, ...] = ()
    sync_request_ids: tuple[str, ...] = ()

    @property
    def sample_now(self) -> bool:
        return bool(self.sample_request_ids)

    @property
    def sync_now(self) -> bool:
        return bool(self.sync_request_ids)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value or not value.isascii():
        raise LocalControlError("invalid_envelope", f"{field} must be an ASCII RFC3339 timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise LocalControlError("invalid_envelope", f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise LocalControlError("invalid_envelope", f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if not isinstance(key, str) or not key.isascii():
            raise LocalControlError("invalid_json", "JSON object keys must be ASCII")
        if key in result:
            raise LocalControlError("invalid_json", f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise LocalControlError("invalid_json", f"non-finite JSON number is forbidden: {value}")


def _strict_keys(value: Mapping[str, Any], allowed: set[str], *, context: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise LocalControlError("invalid_args", f"unknown {context} keys: {', '.join(sorted(unknown))}")


def _safe_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise LocalControlError("invalid_envelope", f"{field} contains invalid characters")
    return value


def _typed_args(command_type: str, args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise LocalControlError("invalid_args", "args must be an object")

    no_args = (
        _VIEW_COMMANDS
        | _REQUEST_COMMANDS
        | {
            "agent_restart",
            "reboot",
            "alerts_unmute",
            "mode_active",
            "mode_sleep",
            "power_continuous",
            "power_eco",
            "alert_unmute",
        }
    )
    if command_type in no_args:
        _strict_keys(args, set(), context="args")
    elif command_type == "set_operation_mode":
        _strict_keys(args, {"mode", "sleep_poll_interval_s"}, context="args")
        if args.get("mode") not in _OPERATION_MODES:
            raise LocalControlError("invalid_args", "mode must be active or sleep")
        if "sleep_poll_interval_s" in args:
            value = args["sleep_poll_interval_s"]
            if not isinstance(value, int) or isinstance(value, bool) or not 60 <= value <= 31_536_000:
                raise LocalControlError("invalid_args", "sleep_poll_interval_s must be 60..31536000")
    elif command_type == "set_power_mode":
        _strict_keys(args, {"mode"}, context="args")
        if args.get("mode") not in _POWER_MODES:
            raise LocalControlError("invalid_args", "mode must be continuous, eco, or deep_sleep")
    elif command_type == "alerts_mute":
        _strict_keys(args, {"until", "reason"}, context="args")
        _parse_timestamp(args.get("until"), "args.until")
        reason = args.get("reason")
        if reason is not None and (not isinstance(reason, str) or _SAFE_REASON.fullmatch(reason) is None):
            raise LocalControlError("invalid_args", "reason must be printable ASCII and at most 240 chars")
    elif command_type in {"alert_mute", "deep_sleep"}:
        _strict_keys(args, {"duration"}, context="args")
        _duration_seconds(args.get("duration"))
    elif command_type == "shutdown":
        _strict_keys(args, set(), context="args")
    elif command_type in _OTA_COMMANDS:
        allowed = {"release_alias", "manifest"} if command_type in {"ota_stage", "ota_canary"} else set()
        _strict_keys(args, allowed, context="args")
        if "release_alias" in allowed:
            _safe_identifier(args.get("release_alias"), "args.release_alias")
            if "manifest" in args and not isinstance(args["manifest"], dict):
                raise LocalControlError("invalid_args", "manifest must be an object")
    else:
        raise LocalControlError("unknown_command", "command type is not allowed")
    return dict(args)


def _duration_seconds(value: Any) -> int:
    if not isinstance(value, str) or not value.isascii():
        raise LocalControlError("invalid_args", "duration must be an ASCII duration such as 30m or 7d")
    match = re.fullmatch(r"([1-9][0-9]{0,7})([smhd])", value)
    if match is None:
        raise LocalControlError("invalid_args", "duration must use s, m, h, or d")
    multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
    seconds = int(match.group(1)) * multiplier
    if not 60 <= seconds <= 31_536_000:
        raise LocalControlError("invalid_args", "duration must be between 60 seconds and 365 days")
    return seconds


def parse_envelope(raw: bytes, *, expected_device_id: str, now: datetime | None = None) -> CommandEnvelope:
    if not raw:
        raise LocalControlError("invalid_json", "empty command envelope")
    if len(raw) > MAX_ENVELOPE_BYTES:
        raise LocalControlError("oversize", f"command envelope exceeds {MAX_ENVELOPE_BYTES} bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LocalControlError("invalid_json", "command envelope must be UTF-8") from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except LocalControlError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise LocalControlError("invalid_json", "command envelope is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise LocalControlError("invalid_envelope", "command envelope must be an object")
    unknown = set(payload) - _ENVELOPE_KEYS
    missing = _ENVELOPE_KEYS - set(payload)
    if unknown or missing:
        detail = []
        if missing:
            detail.append(f"missing={','.join(sorted(missing))}")
        if unknown:
            detail.append(f"unknown={','.join(sorted(unknown))}")
        raise LocalControlError("invalid_envelope", "invalid envelope keys: " + " ".join(detail))
    if payload["version"] != PROTOCOL_VERSION or isinstance(payload["version"], bool):
        raise LocalControlError("unsupported_version", f"version must be {PROTOCOL_VERSION}")
    command_id = _safe_identifier(payload["command_id"], "command_id")
    device_id = _safe_identifier(payload["device_id"], "device_id")
    if device_id != expected_device_id:
        raise LocalControlError("wrong_device", "command is addressed to a different device")
    command_type = _safe_identifier(payload["type"], "type")
    issued_at = _parse_timestamp(payload["issued_at"], "issued_at")
    expires_at = _parse_timestamp(payload["expires_at"], "expires_at")
    current = (now or _utcnow()).astimezone(timezone.utc)
    if expires_at <= issued_at:
        raise LocalControlError("invalid_envelope", "expires_at must be after issued_at")
    if expires_at <= current:
        raise LocalControlError("expired", "command has expired")
    if (
        issued_at > current.replace(microsecond=current.microsecond)
        and (issued_at - current).total_seconds() > 300
    ):
        raise LocalControlError("not_yet_valid", "issued_at is too far in the future")
    return CommandEnvelope(
        command_id=command_id,
        device_id=device_id,
        issued_at=issued_at,
        expires_at=expires_at,
        command_type=command_type,
        args=_typed_args(command_type, payload["args"]),
    )


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _private_file_owner(path: Path) -> tuple[int, int]:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        metadata = path.parent.stat()
    else:
        if not stat.S_ISREG(metadata.st_mode):
            raise LocalControlError(
                "unsafe_state_file",
                f"local control path must be a regular file, not a symlink or special file: {path}",
            )
    return metadata.st_uid, metadata.st_gid


def _set_private_file_owner(fd: int, owner: tuple[int, int], *, path: Path) -> None:
    metadata = os.fstat(fd)
    if not stat.S_ISREG(metadata.st_mode):
        raise LocalControlError(
            "unsafe_state_file",
            f"local control path must be a regular file, not a symlink or special file: {path}",
        )
    os.fchmod(fd, 0o600)
    if (metadata.st_uid, metadata.st_gid) != owner:
        os.fchown(fd, *owner)


def _read_private_file(path: Path) -> bytes | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode):
        raise LocalControlError(
            "unsafe_state_file",
            f"local control path must be a regular file, not a symlink or special file: {path}",
        )
    try:
        fd = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW,
        )
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise LocalControlError(
                "unsafe_state_file",
                f"local control path must not be a symlink: {path}",
            ) from exc
        raise
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise LocalControlError(
                "unsafe_state_file",
                f"local control path must be a regular file: {path}",
            )
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            return handle.read()
    finally:
        if fd >= 0:
            os.close(fd)


def _durable_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    owner = _private_file_owner(path)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temp = Path(name)
    try:
        _set_private_file_owner(fd, owner, path=temp)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    data = (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode(
        "utf-8"
    )
    previous = _read_private_file(path)
    if previous is not None:
        # Keep the last known-good transaction available for explicit recovery.
        # Callers only reach this point after successfully parsing the current file.
        _durable_write(path.with_suffix(path.suffix + ".bak"), previous)
    _durable_write(path, data)


def _default_runtime_path(filename: str) -> Path:
    system_root = Path("/var/lib/edgewatch")
    if system_root.is_dir() or os.geteuid() == 0:
        return system_root / filename
    buffer_path = Path(os.getenv("BUFFER_DB_PATH", "./edgewatch_buffer.sqlite"))
    return buffer_path.parent / filename


class LocalControlState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")

    @classmethod
    def from_env(cls, device_id: str) -> "LocalControlState":
        default = str(_default_runtime_path(f"local-control-{device_id}.json"))
        return cls(Path((os.getenv("EDGEWATCH_LOCAL_CONTROL_STATE_PATH") or default).strip() or default))

    def _read_unlocked(self) -> dict[str, Any]:
        try:
            payload = _read_private_file(self.path)
            if payload is None:
                return {}
            value = json.loads(payload.decode("utf-8"))
        except LocalControlError:
            raise
        except OSError as exc:
            raise LocalControlError(
                "state_unreadable", f"local control state is unreadable: {self.path}"
            ) from exc
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise LocalControlError(
                "state_corrupt",
                f"local control state is corrupt; preserve it and recover from {self.path}.bak",
            ) from exc
        if not isinstance(value, dict):
            raise LocalControlError("state_corrupt", "local control state root must be an object")
        return value

    @staticmethod
    def _requests(state: dict[str, Any], *, create: bool = False) -> dict[str, Any]:
        value = state.get("requests")
        if value is None and create:
            value = {}
            state["requests"] = value
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise LocalControlError("state_corrupt", "local control requests must be an object")
        return value

    @staticmethod
    def _validate_request(command_id: str, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise LocalControlError("state_corrupt", f"request {command_id} must be an object")
        if value.get("type") not in _REQUEST_COMMANDS or value.get("status") not in {
            "pending",
            "claimed",
            "completed",
        }:
            raise LocalControlError("state_corrupt", f"request {command_id} has invalid state")
        point = value.get("point")
        if point is not None and (
            not isinstance(point, dict)
            or not isinstance(point.get("message_id"), str)
            or not point.get("message_id")
            or not isinstance(point.get("ts"), str)
            or not point.get("ts")
            or not isinstance(point.get("metrics"), dict)
        ):
            raise LocalControlError("state_corrupt", f"request {command_id} has an invalid telemetry point")
        return value

    def _locked(self) -> Any:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        owner = _private_file_owner(self.lock_path)
        try:
            fd = os.open(
                self.lock_path,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW,
                0o600,
            )
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise LocalControlError(
                    "unsafe_state_file",
                    f"local control lock must not be a symlink: {self.lock_path}",
                ) from exc
            raise
        try:
            _set_private_file_owner(fd, owner, path=self.lock_path)
            handle = os.fdopen(fd, "a+")
        except Exception:
            os.close(fd)
            raise
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle

    def update(self, mutation: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        with self._locked() as lock:
            state = self._read_unlocked()
            mutation(state)
            state["updated_at"] = _utcnow().isoformat()
            _atomic_json(self.path, state)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            return state

    def snapshot(self) -> dict[str, Any]:
        with self._locked() as lock:
            state = self._read_unlocked()
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            return state

    def ensure_request(self, command_id: str, request_type: str) -> tuple[dict[str, Any], bool]:
        if request_type not in _REQUEST_COMMANDS:
            raise ValueError("unsupported local request")
        with self._locked() as lock:
            state = self._read_unlocked()
            requests = self._requests(state, create=True)
            existing = requests.get(command_id)
            replayed = existing is not None
            if existing is None:
                now = _utcnow().isoformat()
                existing = {
                    "type": request_type,
                    "status": "pending",
                    "created_at": now,
                    "updated_at": now,
                    "attempts": 0,
                }
                requests[command_id] = existing
                state["updated_at"] = now
                _atomic_json(self.path, state)
            else:
                existing = self._validate_request(command_id, existing)
                if existing["type"] != request_type:
                    raise LocalControlError(
                        "command_id_conflict", "command_id was previously used differently"
                    )
            result = json.loads(json.dumps(existing))
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            return result, replayed

    def persist_request_point(
        self,
        command_id: str,
        point: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Persist the immutable telemetry point owned by one local request."""

        candidate = json.loads(
            json.dumps(dict(point), sort_keys=True, separators=(",", ":"), allow_nan=False)
        )
        message_id = candidate.get("message_id")
        timestamp = candidate.get("ts")
        metrics = candidate.get("metrics")
        if (
            not isinstance(message_id, str)
            or not message_id
            or not isinstance(timestamp, str)
            or not timestamp
            or not isinstance(metrics, dict)
        ):
            raise ValueError("local request telemetry point must contain message_id, ts, and metrics")

        with self._locked() as lock:
            state = self._read_unlocked()
            requests = self._requests(state)
            request = self._validate_request(command_id, requests.get(command_id))
            existing = request.get("point")
            if existing is None:
                if request["status"] == "completed":
                    raise LocalControlError(
                        "state_corrupt", f"completed request {command_id} has no telemetry point"
                    )
                now = _utcnow().isoformat()
                request["point"] = candidate
                request["updated_at"] = now
                state["updated_at"] = now
                _atomic_json(self.path, state)
                existing = candidate
            elif existing != candidate:
                # The first durable sample is authoritative across retries and restarts.
                existing = request.get("point")
            if not isinstance(existing, dict):
                raise LocalControlError(
                    "state_corrupt", f"request {command_id} has an invalid telemetry point"
                )
            result = json.loads(json.dumps(existing))
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            return result

    def set_override(self, **values: Any) -> None:
        def mutate(state: dict[str, Any]) -> None:
            overrides = state.setdefault("overrides", {})
            if not isinstance(overrides, dict):
                overrides = {}
                state["overrides"] = overrides
            overrides.update(values)

        self.update(mutate)

    def set_alert_mute(self, *, until: str | None, reason: str | None) -> None:
        self.update(lambda state: state.__setitem__("alerts", {"muted_until": until, "reason": reason}))

    def has_pending_request(self) -> bool:
        state = self.snapshot()
        return any(
            self._validate_request(command_id, value)["status"] == "pending"
            for command_id, value in self._requests(state).items()
        )

    def consume_for_agent(
        self,
        *,
        now: datetime | None = None,
        stale_claim_after_s: int = 300,
        claim_owner: str | None = None,
    ) -> LocalAgentControl:
        captured: dict[str, Any] = {}
        with self._locked() as lock:
            state = self._read_unlocked()
            captured.update(state)
            requests = self._requests(state)
            claimed: dict[str, str] = {}
            current = (now or _utcnow()).astimezone(timezone.utc)
            for command_id in sorted(requests):
                request = self._validate_request(command_id, requests[command_id])
                status = request["status"]
                if status == "completed":
                    continue
                stale = status == "pending"
                if status == "claimed":
                    if claim_owner is not None and request.get("claim_owner") != claim_owner:
                        stale = True
                    else:
                        try:
                            claimed_at = _parse_timestamp(request.get("claimed_at"), "claimed_at")
                        except LocalControlError:
                            stale = True
                        else:
                            stale = (current - claimed_at).total_seconds() >= stale_claim_after_s
                if not stale:
                    continue
                request["status"] = "claimed"
                request["claimed_at"] = current.isoformat()
                request["claim_owner"] = claim_owner
                request["updated_at"] = current.isoformat()
                request["attempts"] = int(request.get("attempts", 0)) + 1
                claimed[command_id] = str(request["type"])
            if claimed:
                state["updated_at"] = _utcnow().isoformat()
                _atomic_json(self.path, state)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        overrides_raw = captured.get("overrides")
        overrides: dict[str, Any] = overrides_raw if isinstance(overrides_raw, dict) else {}
        alerts_raw = captured.get("alerts")
        alerts: dict[str, Any] = alerts_raw if isinstance(alerts_raw, dict) else {}
        return LocalAgentControl(
            operation_mode=overrides.get("operation_mode"),
            sleep_poll_interval_s=overrides.get("sleep_poll_interval_s"),
            runtime_power_mode=overrides.get("runtime_power_mode"),
            alerts_muted_until=alerts.get("muted_until"),
            sample_request_ids=tuple(
                command_id for command_id, request_type in claimed.items() if request_type == "sample_now"
            ),
            sync_request_ids=tuple(
                command_id for command_id, request_type in claimed.items() if request_type == "sync_now"
            ),
        )

    def complete_requests(self, command_ids: tuple[str, ...], result: Mapping[str, Any]) -> None:
        if not command_ids:
            return

        def mutate(state: dict[str, Any]) -> None:
            requests = self._requests(state)
            completed_at = _utcnow().isoformat()
            for command_id in command_ids:
                request = self._validate_request(command_id, requests.get(command_id))
                request["status"] = "completed"
                request.pop("claimed_at", None)
                request.pop("claim_owner", None)
                request["completed_at"] = completed_at
                request["updated_at"] = completed_at
                request["result"] = dict(result)

        self.update(mutate)

    def release_requests(self, command_ids: tuple[str, ...], reason: str) -> None:
        if not command_ids:
            return

        def mutate(state: dict[str, Any]) -> None:
            requests = self._requests(state)
            updated_at = _utcnow().isoformat()
            for command_id in command_ids:
                request = self._validate_request(command_id, requests.get(command_id))
                if request["status"] == "completed":
                    continue
                request["status"] = "pending"
                request.pop("claimed_at", None)
                request.pop("claim_owner", None)
                request["updated_at"] = updated_at
                request["last_error"] = reason[:240]

        self.update(mutate)


class AppliedCommandLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def from_env(cls, device_id: str) -> "AppliedCommandLedger":
        default = str(_default_runtime_path(f"applied-commands-{device_id}.sqlite"))
        return cls(Path((os.getenv("EDGEWATCH_LOCAL_CONTROL_LEDGER_PATH") or default).strip() or default))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS applied_commands ("
                "command_id TEXT PRIMARY KEY, request_json TEXT NOT NULL, result_json TEXT NOT NULL, "
                "applied_at TEXT NOT NULL)"
            )
            conn.commit()
        os.chmod(self.path, 0o600)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(self.path) + suffix)
            if sidecar.exists():
                os.chmod(sidecar, 0o600)
        _fsync_directory(self.path.parent)

    def execute_once(
        self,
        envelope: CommandEnvelope,
        action: Callable[[], dict[str, Any]],
    ) -> tuple[dict[str, Any], bool]:
        request_json = json.dumps(
            {"device_id": envelope.device_id, "type": envelope.command_type, "args": envelope.args},
            sort_keys=True,
            separators=(",", ":"),
        )
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT request_json, result_json FROM applied_commands WHERE command_id = ?",
                (envelope.command_id,),
            ).fetchone()
            if existing is not None:
                if existing[0] != request_json:
                    raise LocalControlError(
                        "command_id_conflict", "command_id was previously used differently"
                    )
                result = json.loads(existing[1])
                conn.commit()
                return result, True
            result = action()
            result_json = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            conn.execute(
                "INSERT INTO applied_commands(command_id, request_json, result_json, applied_at) VALUES (?, ?, ?, ?)",
                (envelope.command_id, request_json, result_json, _utcnow().isoformat()),
            )
            conn.commit()
            return result, False
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


class LocalControlExecutor:
    def __init__(
        self,
        *,
        device_id: str,
        state: LocalControlState,
        ledger: AppliedCommandLedger,
        run_command: Callable[..., Any] = subprocess.run,
    ) -> None:
        self.device_id = device_id
        self.state = state
        self.ledger = ledger
        self.run_command = run_command

    def execute(self, envelope: CommandEnvelope) -> dict[str, Any]:
        if envelope.command_type in _REQUEST_COMMANDS:
            request, replayed = self.state.ensure_request(envelope.command_id, envelope.command_type)
            completed = request["status"] == "completed"
            return {
                "version": PROTOCOL_VERSION,
                "command_id": envelope.command_id,
                "device_id": self.device_id,
                "status": "applied" if completed else "accepted",
                "replayed": replayed,
                "result": {
                    "request_id": envelope.command_id,
                    "request_type": envelope.command_type,
                    "request_status": request["status"],
                    "result": request.get("result"),
                },
            }
        result, replayed = self.ledger.execute_once(envelope, lambda: self._apply(envelope))
        return {
            "version": PROTOCOL_VERSION,
            "command_id": envelope.command_id,
            "device_id": self.device_id,
            "status": "failed" if result.get("ok") is False else "applied",
            "replayed": replayed,
            "result": result,
        }

    def _systemctl(self, argv: list[str]) -> dict[str, Any]:
        completed = self.run_command(argv, check=False, capture_output=True, text=True, timeout=15)
        if completed.returncode != 0:
            raise LocalControlError(
                "system_action_failed", f"fixed system action failed ({completed.returncode})"
            )
        return {"scheduled": True}

    def _apply(self, envelope: CommandEnvelope) -> dict[str, Any]:
        command_type = envelope.command_type
        args = envelope.args
        if command_type in _VIEW_COMMANDS:
            return self._inspect(command_type)
        if command_type == "set_operation_mode":
            values: dict[str, Any] = {"operation_mode": args["mode"]}
            if "sleep_poll_interval_s" in args:
                values["sleep_poll_interval_s"] = args["sleep_poll_interval_s"]
            self.state.set_override(**values)
            return values
        if command_type in {"mode_active", "mode_sleep"}:
            operation_mode = command_type.removeprefix("mode_")
            self.state.set_override(operation_mode=operation_mode)
            return {"operation_mode": operation_mode}
        if command_type == "set_power_mode":
            self.state.set_override(runtime_power_mode=args["mode"])
            return {"runtime_power_mode": args["mode"]}
        if command_type in {"power_continuous", "power_eco"}:
            runtime_power_mode = command_type.removeprefix("power_")
            self.state.set_override(runtime_power_mode=runtime_power_mode)
            return {"runtime_power_mode": runtime_power_mode}
        if command_type == "deep_sleep":
            sleep_s = _duration_seconds(args["duration"])
            self.state.set_override(runtime_power_mode="deep_sleep", sleep_poll_interval_s=sleep_s)
            return {"runtime_power_mode": "deep_sleep", "sleep_poll_interval_s": sleep_s}
        if command_type == "alerts_mute":
            self.state.set_alert_mute(until=args["until"], reason=args.get("reason"))
            return {"muted_until": args["until"]}
        if command_type == "alerts_unmute":
            self.state.set_alert_mute(until=None, reason=None)
            return {"muted_until": None}
        if command_type == "alert_mute":
            until = (_utcnow() + timedelta(seconds=_duration_seconds(args["duration"]))).isoformat()
            self.state.set_alert_mute(until=until, reason="telegram local control")
            return {"muted_until": until}
        if command_type == "alert_unmute":
            self.state.set_alert_mute(until=None, reason=None)
            return {"muted_until": None}
        if command_type == "agent_restart":
            service = os.getenv("EDGEWATCH_AGENT_SYSTEMD_SERVICE", "edgewatch-agent.service")
            if _SAFE_ID.fullmatch(service) is None:
                raise LocalControlError("local_configuration", "invalid agent service name")
            return self._systemctl(["systemctl", "--no-block", "restart", service])
        if command_type == "reboot":
            return self._systemctl(["systemctl", "--no-block", "reboot"])
        if command_type == "shutdown":
            if os.getenv("EDGEWATCH_ALLOW_LOCAL_CONTROL_SHUTDOWN", "").strip().lower() not in {
                "1",
                "true",
                "yes",
                "on",
            }:
                raise LocalControlError("shutdown_disabled", "local-control shutdown is disabled")
            return self._systemctl(["systemctl", "--no-block", "poweroff"])
        if command_type in _OTA_COMMANDS:
            return self._ota(command_type, args, envelope.command_id)
        raise LocalControlError("unknown_command", "command type is not allowed")

    def _inspect(self, command_type: str) -> dict[str, Any]:
        snapshot = self.state.snapshot()
        if command_type == "status":
            overrides = snapshot.get("overrides")
            if not isinstance(overrides, dict):
                overrides = {}
            alerts = snapshot.get("alerts")
            if not isinstance(alerts, dict):
                alerts = {}
            requests = snapshot.get("requests")
            pending_requests = 0
            if isinstance(requests, dict):
                pending_requests = sum(
                    isinstance(request, dict) and request.get("status") in {"pending", "claimed"}
                    for request in requests.values()
                )
            ready_path = (os.getenv("EDGEWATCH_READY_PATH") or "").strip()
            return {
                "device_id": self.device_id,
                "ready": bool(ready_path and Path(ready_path).is_file()),
                "transport": (os.getenv("EDGEWATCH_TELEMETRY_TRANSPORT") or "unknown").strip() or "unknown",
                "version": (os.getenv("EDGEWATCH_AGENT_VERSION") or "unknown").strip() or "unknown",
                "operation_mode": overrides.get("operation_mode") or "active",
                "runtime_power_mode": self._effective_power_mode(snapshot),
                "alerts_muted_until": alerts.get("muted_until"),
                "pending_requests": pending_requests,
            }
        if command_type == "health":
            ready_path = (os.getenv("EDGEWATCH_READY_PATH") or "").strip()
            return {"ready": bool(ready_path and Path(ready_path).is_file())}
        if command_type == "network":
            interfaces = []
            net_root = Path("/sys/class/net")
            if net_root.is_dir():
                for entry in sorted(net_root.iterdir(), key=lambda item: item.name):
                    if _SAFE_ID.fullmatch(entry.name) is None:
                        continue
                    try:
                        state = (entry / "operstate").read_text(encoding="ascii").strip()
                    except OSError:
                        state = "unknown"
                    interfaces.append({"name": entry.name, "state": state})
            return {"interfaces": interfaces}
        if command_type == "power":
            details = self._power_state_details()
            details["runtime_power_mode"] = self._effective_power_mode(snapshot)
            details["throttled"] = self._read_throttled_state()
            return details
        if command_type == "queue":
            path = Path(os.getenv("BUFFER_DB_PATH", "./edgewatch_buffer.sqlite"))
            count = None
            if path.is_file():
                try:
                    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
                        count = int(conn.execute("SELECT COUNT(*) FROM queue").fetchone()[0])
                except (sqlite3.Error, OSError):
                    count = None
            return {"queued_points": count, "database_bytes": path.stat().st_size if path.exists() else 0}
        if command_type == "version":
            return {"version": os.getenv("EDGEWATCH_AGENT_VERSION", "unknown")}
        return self._ota("ota_status", {}, "status")

    @staticmethod
    def _effective_power_mode(snapshot: Mapping[str, Any]) -> str:
        overrides = snapshot.get("overrides")
        override = overrides.get("runtime_power_mode") if isinstance(overrides, dict) else None
        if isinstance(override, str) and override in _POWER_MODES:
            return override
        configured = (os.getenv("RUNTIME_POWER_MODE") or "continuous").strip().lower()
        return configured if configured in _POWER_MODES else "continuous"

    @staticmethod
    def _power_state_details() -> dict[str, Any]:
        details: dict[str, Any] = {
            "source": "unknown",
            "input_out_of_range": None,
            "unsustainable": None,
            "saver_active": None,
        }
        raw_path = (os.getenv("EDGEWATCH_POWER_STATE_PATH") or "").strip()
        if not raw_path:
            return details
        path = Path(raw_path)
        try:
            metadata = path.lstat()
            if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 64 * 1024:
                return details
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return details
        if not isinstance(payload, dict):
            return details
        source = payload.get("last_power_source")
        if isinstance(source, str) and source.isascii() and 0 < len(source) <= 32:
            details["source"] = source
        evaluation = payload.get("last_evaluation")
        if not isinstance(evaluation, dict):
            return details
        for source_key, result_key in (
            ("power_input_out_of_range", "input_out_of_range"),
            ("power_unsustainable", "unsustainable"),
            ("power_saver_active", "saver_active"),
        ):
            value = evaluation.get(source_key)
            if isinstance(value, bool):
                details[result_key] = value
        return details

    def _read_throttled_state(self) -> str | None:
        try:
            completed = self.run_command(
                ["vcgencmd", "get_throttled"],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        output = str(getattr(completed, "stdout", "")).strip()
        if (
            getattr(completed, "returncode", 1) != 0
            or re.fullmatch(r"throttled=0x[0-9A-Fa-f]+", output) is None
        ):
            return None
        return output.lower()

    def _ota(self, command_type: str, args: dict[str, Any], command_id: str) -> dict[str, Any]:
        try:
            module = importlib.import_module("agent.local_ota")
            manager_type = getattr(module, "LocalOtaManager")
            retryable_error = getattr(module, "RetryableOtaError", ())
            manager = manager_type.from_env(device_id=self.device_id)
            handler = getattr(manager, "handle_command")
        except (ImportError, AttributeError, TypeError) as exc:
            raise LocalControlError("ota_unavailable", "local OTA manager is unavailable") from exc
        try:
            manifest = args.get("manifest")
            if command_type in {"ota_stage", "ota_canary"} and isinstance(manifest, dict):
                execute = getattr(manager, "execute")
                if command_type == "ota_stage":
                    result = execute("stage", manifest, command_id)
                else:
                    staged = execute("stage", manifest, f"{command_id}:stage")
                    result = staged if staged.get("ok") is False else execute("apply", manifest, command_id)
            else:
                result = handler(command_type=command_type, args=dict(args), command_id=command_id)
        except retryable_error as exc:
            raise LocalControlError("ota_retryable", "local OTA operation can be retried") from exc
        except Exception as exc:
            raise LocalControlError("ota_failure", "local OTA manager rejected the command") from exc
        if not isinstance(result, dict):
            raise LocalControlError("ota_failure", "local OTA manager returned an invalid result")
        return result


def error_response(*, device_id: str, command_id: str | None, error: LocalControlError) -> dict[str, Any]:
    return {
        "version": PROTOCOL_VERSION,
        "command_id": command_id,
        "device_id": device_id,
        "status": "rejected",
        "error": {"code": error.code, "message": str(error)},
    }
