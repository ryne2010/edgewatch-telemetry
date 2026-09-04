from __future__ import annotations

import math
import os
import stat
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import requests


class HeartbeatConfigError(ValueError):
    pass


@dataclass(frozen=True)
class HeartbeatConfig:
    checkin_url: str = field(repr=False)
    interval_s: float = 3600.0
    request_timeout_s: float = 10.0
    max_attempts: int = 3
    backoff_base_s: float = 1.0


@dataclass(frozen=True)
class HeartbeatResult:
    success: bool
    attempts: int
    reason: str
    retryable: bool = False


class _Response(Protocol):
    @property
    def status_code(self) -> int: ...


class _Session(Protocol):
    def get(self, url: str, **kwargs: Any) -> _Response: ...


def load_heartbeat_config(env: Mapping[str, str] | None = None) -> HeartbeatConfig | None:
    """Load an optional dead-man check without accepting a plaintext URL variable."""

    values = os.environ if env is None else env
    if values.get("EDGEWATCH_DEADMAN_HEARTBEAT_URL", "").strip():
        raise HeartbeatConfigError(
            "plaintext dead-man URLs are forbidden; use EDGEWATCH_DEADMAN_HEARTBEAT_URL_FILE"
        )
    raw_path = values.get("EDGEWATCH_DEADMAN_HEARTBEAT_URL_FILE", "").strip()
    if not raw_path:
        option_names = {
            "EDGEWATCH_DEADMAN_INTERVAL_S",
            "EDGEWATCH_DEADMAN_REQUEST_TIMEOUT_S",
            "EDGEWATCH_DEADMAN_MAX_ATTEMPTS",
            "EDGEWATCH_DEADMAN_BACKOFF_BASE_S",
        }
        if any(name in values for name in option_names):
            raise HeartbeatConfigError(
                "dead-man heartbeat options require EDGEWATCH_DEADMAN_HEARTBEAT_URL_FILE"
            )
        return None
    checkin_url = _read_secret_url(Path(raw_path))
    return HeartbeatConfig(
        checkin_url=checkin_url,
        interval_s=_positive_float(values, "EDGEWATCH_DEADMAN_INTERVAL_S", 3600.0),
        request_timeout_s=_positive_float(values, "EDGEWATCH_DEADMAN_REQUEST_TIMEOUT_S", 10.0),
        max_attempts=_bounded_positive_int(values, "EDGEWATCH_DEADMAN_MAX_ATTEMPTS", 3, maximum=10),
        backoff_base_s=_positive_float(values, "EDGEWATCH_DEADMAN_BACKOFF_BASE_S", 1.0),
    )


class DeadManHeartbeat:
    """Schedule bounded check-ins on a daemon thread so controller work never waits."""

    def __init__(
        self,
        config: HeartbeatConfig,
        *,
        session: _Session | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._session = session or requests.Session()
        self._sleeper = sleeper
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._in_flight = False
        self._next_due_at = 0.0
        self._last_result: HeartbeatResult | None = None

    @property
    def last_result(self) -> HeartbeatResult | None:
        with self._lock:
            return self._last_result

    @property
    def in_flight(self) -> bool:
        """Report whether a bounded check-in is using the current network window."""

        with self._lock:
            return self._in_flight

    def poll(self, now: float | None = None) -> bool:
        """Start a due check-in and return immediately; coalesce concurrent polls."""

        current = self._monotonic() if now is None else now
        with self._lock:
            if self._in_flight or current < self._next_due_at:
                return False
            self._in_flight = True
            self._next_due_at = current + self.config.interval_s
        thread = threading.Thread(
            target=self._run_background,
            name="edgewatch-deadman-heartbeat",
            daemon=True,
        )
        thread.start()
        return True

    def check_in(self) -> HeartbeatResult:
        """Run one bounded check-in attempt set; callers should normally use ``poll``."""

        for attempt in range(1, self.config.max_attempts + 1):
            result = self._attempt(attempt)
            if result.success or not result.retryable or attempt == self.config.max_attempts:
                return result
            self._sleeper(self.config.backoff_base_s * (2 ** (attempt - 1)))
        return HeartbeatResult(False, self.config.max_attempts, "heartbeat retry budget exhausted")

    def _attempt(self, attempt: int) -> HeartbeatResult:
        try:
            response = self._session.get(
                self.config.checkin_url,
                timeout=self.config.request_timeout_s,
                allow_redirects=False,
            )
        except requests.RequestException:
            return HeartbeatResult(False, attempt, "heartbeat network request failed", retryable=True)
        except Exception:
            return HeartbeatResult(False, attempt, "heartbeat client failed", retryable=False)
        status = response.status_code
        if 200 <= status < 300:
            return HeartbeatResult(True, attempt, "heartbeat delivered")
        if status == 429 or 500 <= status < 600:
            return HeartbeatResult(False, attempt, "heartbeat endpoint unavailable", retryable=True)
        return HeartbeatResult(False, attempt, "heartbeat endpoint rejected check-in")

    def _run_background(self) -> None:
        try:
            result = self.check_in()
        except Exception:
            result = HeartbeatResult(False, 0, "heartbeat worker failed")
        with self._lock:
            self._last_result = result
            self._in_flight = False


def _read_secret_url(path: Path) -> str:
    descriptor: int | None = None
    try:
        path_stat = path.lstat()
        if not stat.S_ISREG(path_stat.st_mode):
            raise HeartbeatConfigError("dead-man URL file must be a regular file")
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode) or (file_stat.st_dev, file_stat.st_ino) != (
            path_stat.st_dev,
            path_stat.st_ino,
        ):
            raise HeartbeatConfigError("dead-man URL file must be a regular file")
        if stat.S_IMODE(file_stat.st_mode) != 0o600:
            raise HeartbeatConfigError("dead-man URL file permissions must be 0600")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            raw = handle.read(8193)
        if len(raw) > 8192:
            raise HeartbeatConfigError("dead-man URL file must contain one valid HTTPS check-in URL")
        value = raw.decode("utf-8", errors="strict").strip()
    except HeartbeatConfigError:
        raise
    except (OSError, UnicodeError) as exc:
        raise HeartbeatConfigError("dead-man URL file must be readable UTF-8") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise HeartbeatConfigError("dead-man URL file must contain one valid HTTPS check-in URL") from exc
    if (
        not value
        or any(character.isspace() for character in value)
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise HeartbeatConfigError("dead-man URL file must contain one valid HTTPS check-in URL")
    return value


def _positive_float(values: Mapping[str, str], name: str, default: float) -> float:
    raw = values.get(name)
    if raw is None:
        return default
    try:
        result = float(raw.strip())
    except ValueError as exc:
        raise HeartbeatConfigError(f"{name} must be a positive number") from exc
    if not math.isfinite(result) or result <= 0:
        raise HeartbeatConfigError(f"{name} must be a positive number")
    return result


def _bounded_positive_int(values: Mapping[str, str], name: str, default: int, *, maximum: int) -> int:
    raw = values.get(name)
    if raw is None:
        return default
    try:
        result = int(raw.strip())
    except ValueError as exc:
        raise HeartbeatConfigError(f"{name} must be a positive integer") from exc
    if result <= 0 or result > maximum:
        raise HeartbeatConfigError(f"{name} must be from 1 through {maximum}")
    return result
