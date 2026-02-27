from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol


class PowerManagementError(ValueError):
    """Raised when power-management configuration/state is invalid."""


NowFn = Callable[[], datetime]


class PowerManagementPolicyLike(Protocol):
    @property
    def enabled(self) -> bool: ...

    @property
    def mode(self) -> str: ...

    @property
    def input_warn_min_v(self) -> float: ...

    @property
    def input_warn_max_v(self) -> float: ...

    @property
    def input_critical_min_v(self) -> float: ...

    @property
    def input_critical_max_v(self) -> float: ...

    @property
    def sustainable_input_w(self) -> float: ...

    @property
    def unsustainable_window_s(self) -> int: ...

    @property
    def battery_trend_window_s(self) -> int: ...

    @property
    def battery_drop_warn_v(self) -> float: ...

    @property
    def saver_sample_interval_s(self) -> int: ...

    @property
    def saver_heartbeat_interval_s(self) -> int: ...

    @property
    def media_disabled_in_saver(self) -> bool: ...


@dataclass(frozen=True)
class PowerEvaluation:
    power_source: str
    power_input_out_of_range: bool
    power_unsustainable: bool
    power_saver_active: bool

    def telemetry_flags(self) -> dict[str, Any]:
        return {
            "power_source": self.power_source,
            "power_input_out_of_range": self.power_input_out_of_range,
            "power_unsustainable": self.power_unsustainable,
            "power_saver_active": self.power_saver_active,
        }


class PowerManager:
    """Durable rolling-window power evaluation with hardware+fallback modes."""

    def __init__(self, *, path: Path, now_fn: NowFn | None = None) -> None:
        self.path = path
        self._now_fn = now_fn or _utcnow
        self._state = self._load_or_default()

    @classmethod
    def from_env(cls, *, device_id: str, now_fn: NowFn | None = None) -> PowerManager:
        default_path = f"./edgewatch_power_state_{device_id}.json"
        raw = os.getenv("EDGEWATCH_POWER_STATE_PATH", default_path).strip()
        if not raw:
            raise PowerManagementError("EDGEWATCH_POWER_STATE_PATH must be non-empty")
        return cls(path=Path(raw), now_fn=now_fn)

    def evaluate(self, *, metrics: Mapping[str, Any], policy: PowerManagementPolicyLike) -> PowerEvaluation:
        now_ts = self._now_ts()

        input_v = _as_float(metrics.get("power_input_v"))
        input_w = _as_float(metrics.get("power_input_w"))
        battery_v = _as_float(metrics.get("battery_v"))

        if input_w is not None:
            self._state["power_w_samples"].append({"ts": now_ts, "value": float(input_w)})
        if battery_v is not None:
            self._state["battery_v_samples"].append({"ts": now_ts, "value": float(battery_v)})

        max_window = max(int(policy.unsustainable_window_s), int(policy.battery_trend_window_s), 1)
        self._state["power_w_samples"] = _prune_samples(
            self._state["power_w_samples"], now_ts, max_window * 2
        )
        self._state["battery_v_samples"] = _prune_samples(
            self._state["battery_v_samples"], now_ts, max_window * 2
        )

        power_source = _normalize_power_source(metrics.get("power_source"), input_v=input_v)

        if not policy.enabled:
            self._save()
            return PowerEvaluation(
                power_source=power_source,
                power_input_out_of_range=False,
                power_unsustainable=False,
                power_saver_active=False,
            )

        out_of_range = False
        critical_out_of_range = False
        if input_v is not None:
            out_of_range = input_v < policy.input_warn_min_v or input_v > policy.input_warn_max_v
            critical_out_of_range = (
                input_v < policy.input_critical_min_v or input_v > policy.input_critical_max_v
            )

        hardware_available = input_w is not None
        fallback_available = battery_v is not None

        unsustainable_hardware = False
        if policy.mode in {"dual", "hardware"} and hardware_available:
            unsustainable_hardware = _window_average_exceeds(
                self._state["power_w_samples"],
                now_ts=now_ts,
                window_s=int(policy.unsustainable_window_s),
                threshold=float(policy.sustainable_input_w),
            )

        unsustainable_fallback = False
        if policy.mode in {"dual", "fallback"} and fallback_available:
            unsustainable_fallback = _battery_drop_exceeds(
                self._state["battery_v_samples"],
                now_ts=now_ts,
                window_s=int(policy.battery_trend_window_s),
                drop_v=float(policy.battery_drop_warn_v),
            )

        if policy.mode == "hardware":
            unsustainable = unsustainable_hardware
        elif policy.mode == "fallback":
            unsustainable = unsustainable_fallback
        else:
            # Dual-mode: prefer hardware signal when available; otherwise fallback.
            unsustainable = unsustainable_hardware if hardware_available else unsustainable_fallback

        if critical_out_of_range:
            unsustainable = True

        saver_active = bool(out_of_range or unsustainable)

        self._state["last_power_source"] = power_source
        self._save()
        return PowerEvaluation(
            power_source=power_source,
            power_input_out_of_range=bool(out_of_range),
            power_unsustainable=bool(unsustainable),
            power_saver_active=bool(saver_active),
        )

    def _load_or_default(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return _default_state()
        except OSError:
            return _default_state()

        try:
            parsed = json.loads(raw)
        except Exception:
            return _default_state()
        if not isinstance(parsed, Mapping):
            return _default_state()

        power_samples = _coerce_samples(parsed.get("power_w_samples"))
        battery_samples = _coerce_samples(parsed.get("battery_v_samples"))
        last_source = str(parsed.get("last_power_source") or "unknown").strip().lower()
        if last_source not in {"solar", "battery", "unknown"}:
            last_source = "unknown"

        return {
            "power_w_samples": power_samples,
            "battery_v_samples": battery_samples,
            "last_power_source": last_source,
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._state, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def _now_ts(self) -> float:
        return self._now_fn().astimezone(timezone.utc).timestamp()


def _coerce_samples(raw: Any) -> list[dict[str, float]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, float]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        ts = _as_float(item.get("ts"))
        value = _as_float(item.get("value"))
        if ts is None or value is None:
            continue
        out.append({"ts": float(ts), "value": float(value)})
    return out


def _default_state() -> dict[str, Any]:
    return {
        "power_w_samples": [],
        "battery_v_samples": [],
        "last_power_source": "unknown",
    }


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _prune_samples(samples: list[dict[str, float]], now_ts: float, window_s: int) -> list[dict[str, float]]:
    if window_s <= 0:
        return []
    floor = float(now_ts) - float(window_s)
    return [row for row in samples if float(row.get("ts", 0.0)) >= floor]


def _window_average_exceeds(
    samples: list[dict[str, float]], *, now_ts: float, window_s: int, threshold: float
) -> bool:
    if threshold <= 0 or window_s <= 0:
        return False
    floor = float(now_ts) - float(window_s)
    window = [row for row in samples if float(row["ts"]) >= floor]
    if len(window) < 2:
        return False
    span = float(window[-1]["ts"]) - float(window[0]["ts"])
    if span < float(window_s):
        return False
    avg = sum(float(row["value"]) for row in window) / float(len(window))
    return avg > threshold


def _battery_drop_exceeds(
    samples: list[dict[str, float]], *, now_ts: float, window_s: int, drop_v: float
) -> bool:
    if drop_v <= 0 or window_s <= 0:
        return False
    floor = float(now_ts) - float(window_s)
    window = [row for row in samples if float(row["ts"]) >= floor]
    if len(window) < 2:
        return False
    span = float(window[-1]["ts"]) - float(window[0]["ts"])
    if span < float(window_s):
        return False
    start_v = float(window[0]["value"])
    end_v = float(window[-1]["value"])
    return (start_v - end_v) >= drop_v


def _normalize_power_source(raw: Any, *, input_v: float | None) -> str:
    if isinstance(raw, str):
        value = raw.strip().lower()
        if value in {"solar", "battery", "unknown"}:
            return value
    if input_v is None:
        return "unknown"
    return "solar" if input_v >= 13.2 else "battery"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
