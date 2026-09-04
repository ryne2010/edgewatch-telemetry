from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol


class CostCapError(ValueError):
    """Raised when cost-cap configuration or state is invalid."""


NowFn = Callable[[], datetime]
DEFAULT_URGENT_RESERVE_BYTES = 256 * 1024
URGENT_TELEMETRY_REASONS = frozenset(
    {"startup", "heartbeat", "state_change", "alert_change", "alert_snapshot"}
)


@dataclass(frozen=True)
class CostCapsPolicy:
    max_bytes_per_day: int
    max_snapshots_per_day: int
    max_media_uploads_per_day: int


class CostCapsLike(Protocol):
    @property
    def max_bytes_per_day(self) -> int: ...

    @property
    def max_snapshots_per_day(self) -> int: ...

    @property
    def max_media_uploads_per_day(self) -> int: ...


@dataclass(frozen=True)
class CostCapCounters:
    utc_day: str
    bytes_sent_today: int
    snapshots_today: int
    media_uploads_today: int


class CostCapState:
    """Durable daily counters used for edge cost-cap enforcement."""

    def __init__(
        self,
        *,
        path: Path,
        now_fn: NowFn | None = None,
        urgent_reserve_bytes: int = DEFAULT_URGENT_RESERVE_BYTES,
    ) -> None:
        if isinstance(urgent_reserve_bytes, bool) or int(urgent_reserve_bytes) < 0:
            raise CostCapError("urgent reserve bytes must be a non-negative integer")
        self.path = path
        self._now_fn = now_fn or _utcnow
        self.urgent_reserve_bytes = int(urgent_reserve_bytes)
        self._counters = self._load_or_default()
        self._ensure_today()

    @classmethod
    def from_env(cls, *, device_id: str, now_fn: NowFn | None = None) -> CostCapState:
        default_path = f"./edgewatch_cost_caps_{device_id}.json"
        raw = os.getenv("EDGEWATCH_COST_CAP_STATE_PATH", default_path).strip()
        if not raw:
            raise CostCapError("EDGEWATCH_COST_CAP_STATE_PATH must be non-empty")
        reserve_raw = os.getenv(
            "EDGEWATCH_COST_CAP_URGENT_RESERVE_BYTES",
            str(DEFAULT_URGENT_RESERVE_BYTES),
        ).strip()
        try:
            urgent_reserve_bytes = int(reserve_raw)
        except ValueError as exc:
            raise CostCapError(
                "EDGEWATCH_COST_CAP_URGENT_RESERVE_BYTES must be a non-negative integer"
            ) from exc
        if urgent_reserve_bytes < 0:
            raise CostCapError("EDGEWATCH_COST_CAP_URGENT_RESERVE_BYTES must be a non-negative integer")
        return cls(
            path=Path(raw),
            now_fn=now_fn,
            urgent_reserve_bytes=urgent_reserve_bytes,
        )

    def counters(self) -> CostCapCounters:
        self._ensure_today()
        return CostCapCounters(
            utc_day=self._counters["utc_day"],
            bytes_sent_today=int(self._counters["bytes_sent_today"]),
            snapshots_today=int(self._counters["snapshots_today"]),
            media_uploads_today=int(self._counters["media_uploads_today"]),
        )

    def cost_cap_active(self, policy: CostCapsLike) -> bool:
        c = self.counters()
        return (
            c.bytes_sent_today >= policy.max_bytes_per_day
            or c.snapshots_today >= policy.max_snapshots_per_day
            or c.media_uploads_today >= policy.max_media_uploads_per_day
        )

    def telemetry_heartbeat_only(self, policy: CostCapsLike) -> bool:
        """Return whether routine telemetry must stop at the daily byte cap."""

        return self.counters().bytes_sent_today >= policy.max_bytes_per_day

    def allow_telemetry_reason(self, reason: str, policy: CostCapsLike) -> bool:
        if not self.telemetry_heartbeat_only(policy):
            return True
        return reason in URGENT_TELEMETRY_REASONS and self.remaining_telemetry_bytes(reason, policy) > 0

    def remaining_telemetry_bytes(self, reason: str, policy: CostCapsLike) -> int:
        """Return the conservative request budget remaining for ``reason``.

        Routine traffic is bounded by ``max_bytes_per_day``. Operationally
        urgent traffic may use the separately bounded local reserve so a device
        can still report health and alert transitions after routine traffic is
        stopped.
        """

        limit = max(0, int(policy.max_bytes_per_day))
        if reason in URGENT_TELEMETRY_REASONS:
            limit += self.urgent_reserve_bytes
        return max(0, limit - self.counters().bytes_sent_today)

    def routine_bytes_remaining(self, policy: CostCapsLike) -> int:
        return self.remaining_telemetry_bytes("delta", policy)

    def urgent_bytes_remaining(self, policy: CostCapsLike) -> int:
        return self.remaining_telemetry_bytes("heartbeat", policy)

    def allow_snapshot_capture(self, policy: CostCapsLike) -> bool:
        c = self.counters()
        if c.snapshots_today >= policy.max_snapshots_per_day:
            return False
        if c.media_uploads_today >= policy.max_media_uploads_per_day:
            return False
        return True

    def record_bytes_sent(self, payload_bytes: int) -> None:
        self._ensure_today()
        n = max(0, int(payload_bytes))
        self._counters["bytes_sent_today"] = int(self._counters["bytes_sent_today"]) + n
        self._save()

    def observe_bytes_sent_today(self, absolute_bytes: int) -> None:
        """Reconcile the logical counter with a measured interface total.

        Transport callbacks provide immediate payload accounting, while the
        cellular monitor periodically reports the more complete kernel TX-byte
        total (including protocol overhead). Keeping the larger value avoids
        under-enforcing the daily cap without making interface polling a hard
        dependency for non-cellular deployments.
        """

        self._ensure_today()
        observed = max(0, int(absolute_bytes))
        if observed <= int(self._counters["bytes_sent_today"]):
            return
        self._counters["bytes_sent_today"] = observed
        self._save()

    def record_snapshot_capture(self) -> None:
        self._ensure_today()
        # Conservative accounting: treat each scheduled capture as a future upload unit.
        self._counters["snapshots_today"] = int(self._counters["snapshots_today"]) + 1
        self._counters["media_uploads_today"] = int(self._counters["media_uploads_today"]) + 1
        self._save()

    def audit_metrics(self, policy: CostCapsLike) -> dict[str, Any]:
        c = self.counters()
        return {
            "cost_cap_active": self.cost_cap_active(policy),
            "bytes_sent_today": c.bytes_sent_today,
            "media_uploads_today": c.media_uploads_today,
            "snapshots_today": c.snapshots_today,
            "urgent_reserve_bytes": self.urgent_reserve_bytes,
            "urgent_bytes_remaining": self.urgent_bytes_remaining(policy),
        }

    def _load_or_default(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return self._new_day_counters()
        except (OSError, UnicodeError) as exc:
            raise CostCapError(f"could not read cost-cap state at {self.path}") from exc

        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise CostCapError(f"invalid cost-cap state at {self.path}") from exc
        if not isinstance(parsed, Mapping):
            raise CostCapError(f"invalid cost-cap state at {self.path}")

        day = str(parsed.get("utc_day") or "").strip()
        try:
            parsed_day = datetime.strptime(day, "%Y-%m-%d").date().isoformat()
        except ValueError as exc:
            raise CostCapError(f"invalid cost-cap state at {self.path}") from exc
        if parsed_day != day:
            raise CostCapError(f"invalid cost-cap state at {self.path}")

        counters = {
            "utc_day": day,
            "bytes_sent_today": _require_non_negative_int(parsed, "bytes_sent_today", self.path),
            "snapshots_today": _require_non_negative_int(parsed, "snapshots_today", self.path),
            "media_uploads_today": _require_non_negative_int(
                parsed,
                "media_uploads_today",
                self.path,
            ),
        }
        return counters

    def _new_day_counters(self) -> dict[str, Any]:
        return {
            "utc_day": _current_utc_day(self._now_fn()),
            "bytes_sent_today": 0,
            "snapshots_today": 0,
            "media_uploads_today": 0,
        }

    def _ensure_today(self) -> None:
        today = _current_utc_day(self._now_fn())
        if self._counters["utc_day"] == today:
            return
        self._counters = {
            "utc_day": today,
            "bytes_sent_today": 0,
            "snapshots_today": 0,
            "media_uploads_today": 0,
        }
        self._save()

    def _save(self) -> None:
        temp_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                dir=str(self.path.parent),
                prefix=f".{self.path.name}.",
                suffix=".tmp",
            )
            temp_path = Path(temp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                json.dump(self._counters, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            temp_path = None
            _fsync_directory(self.path.parent)
        except Exception as exc:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise CostCapError(f"could not persist cost-cap state at {self.path}") from exc


def _require_non_negative_int(parsed: Mapping[str, Any], key: str, path: Path) -> int:
    value = parsed.get(key)
    if isinstance(value, bool):
        raise CostCapError(f"invalid cost-cap state at {path}")
    if isinstance(value, int):
        if value >= 0:
            return value
        raise CostCapError(f"invalid cost-cap state at {path}")
    if isinstance(value, float) and value.is_integer():
        if value >= 0:
            return int(value)
    raise CostCapError(f"invalid cost-cap state at {path}")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd = os.open(path, flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _current_utc_day(now: datetime) -> str:
    return now.astimezone(timezone.utc).date().isoformat()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
