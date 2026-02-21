from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol


class CostCapError(ValueError):
    """Raised when cost-cap configuration or state is invalid."""


NowFn = Callable[[], datetime]


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

    def __init__(self, *, path: Path, now_fn: NowFn | None = None) -> None:
        self.path = path
        self._now_fn = now_fn or _utcnow
        self._counters = self._load_or_default()
        self._ensure_today()

    @classmethod
    def from_env(cls, *, device_id: str, now_fn: NowFn | None = None) -> CostCapState:
        default_path = f"./edgewatch_cost_caps_{device_id}.json"
        raw = os.getenv("EDGEWATCH_COST_CAP_STATE_PATH", default_path).strip()
        if not raw:
            raise CostCapError("EDGEWATCH_COST_CAP_STATE_PATH must be non-empty")
        return cls(path=Path(raw), now_fn=now_fn)

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
        return self.counters().bytes_sent_today >= policy.max_bytes_per_day

    def allow_telemetry_reason(self, reason: str, policy: CostCapsLike) -> bool:
        if not self.telemetry_heartbeat_only(policy):
            return True
        return reason in {"heartbeat", "startup"}

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
        }

    def _load_or_default(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return self._new_day_counters()
        except OSError:
            return self._new_day_counters()

        try:
            parsed = json.loads(raw)
        except Exception:
            return self._new_day_counters()
        if not isinstance(parsed, Mapping):
            return self._new_day_counters()

        day = str(parsed.get("utc_day") or "").strip()
        if not day:
            day = _current_utc_day(self._now_fn())

        counters = {
            "utc_day": day,
            "bytes_sent_today": _coerce_non_negative_int(parsed.get("bytes_sent_today")),
            "snapshots_today": _coerce_non_negative_int(parsed.get("snapshots_today")),
            "media_uploads_today": _coerce_non_negative_int(parsed.get("media_uploads_today")),
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._counters, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)


def _coerce_non_negative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value.is_integer():
        return max(0, int(value))
    return 0


def _current_utc_day(now: datetime) -> str:
    return now.astimezone(timezone.utc).date().isoformat()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
