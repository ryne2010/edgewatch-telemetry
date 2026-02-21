from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class OilLifeState:
    oil_life_runtime_s: float
    oil_life_reset_at: str
    oil_life_last_seen_running_at: str | None
    is_running: bool


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso_utc(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def default_state(*, now: datetime) -> OilLifeState:
    return OilLifeState(
        oil_life_runtime_s=0.0,
        oil_life_reset_at=to_iso_utc(now),
        oil_life_last_seen_running_at=None,
        is_running=False,
    )


def compute_oil_life_pct(*, oil_life_runtime_s: float, oil_life_max_run_hours: float) -> float:
    if oil_life_max_run_hours <= 0:
        return 0.0
    runtime_hours = max(0.0, float(oil_life_runtime_s)) / 3600.0
    pct = 100.0 * (1.0 - (runtime_hours / oil_life_max_run_hours))
    if pct < 0.0:
        return 0.0
    if pct > 100.0:
        return 100.0
    return pct


def derive_running_state(
    *,
    metrics: Mapping[str, Any],
    previous_running: bool,
    run_on_threshold: float,
    run_off_threshold: float,
) -> bool:
    pump_on = metrics.get("pump_on")
    if isinstance(pump_on, bool):
        return pump_on

    pressure = _as_float(metrics.get("oil_pressure_psi"))
    if pressure is None:
        return previous_running

    if previous_running:
        return pressure > run_off_threshold
    return pressure >= run_on_threshold


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (float, int)):
        return float(value)
    return None


class OilLifeStateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> OilLifeState:
        if not self.path.exists():
            raise FileNotFoundError(str(self.path))

        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("oil life state must be a JSON object")

        runtime_raw = data.get("oil_life_runtime_s")
        if isinstance(runtime_raw, bool) or not isinstance(runtime_raw, (int, float)):
            raise ValueError("oil_life_runtime_s must be numeric")
        runtime = max(0.0, float(runtime_raw))

        reset_at_raw = data.get("oil_life_reset_at")
        if not isinstance(reset_at_raw, str) or not reset_at_raw.strip():
            raise ValueError("oil_life_reset_at must be a non-empty ISO timestamp")
        reset_at = to_iso_utc(parse_iso_utc(reset_at_raw))

        last_seen_raw = data.get("oil_life_last_seen_running_at")
        if last_seen_raw is None:
            last_seen = None
        elif isinstance(last_seen_raw, str) and last_seen_raw.strip():
            last_seen = to_iso_utc(parse_iso_utc(last_seen_raw))
        else:
            raise ValueError("oil_life_last_seen_running_at must be null or ISO timestamp")

        is_running_raw = data.get("is_running", False)
        if not isinstance(is_running_raw, bool):
            raise ValueError("is_running must be boolean")

        return OilLifeState(
            oil_life_runtime_s=runtime,
            oil_life_reset_at=reset_at,
            oil_life_last_seen_running_at=last_seen,
            is_running=is_running_raw,
        )

    def save(self, state: OilLifeState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(state)

        temp_path = self.path.with_name(self.path.name + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_path, self.path)

        try:
            parent_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        except OSError:
            # Best effort across filesystems/platforms.
            pass

    def reset(self, *, now: datetime | None = None) -> OilLifeState:
        current = now_utc() if now is None else now.astimezone(timezone.utc)
        state = default_state(now=current)
        self.save(state)
        return state
