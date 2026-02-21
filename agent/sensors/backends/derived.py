from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from ..base import Metrics
from ..derived.oil_life import (
    OilLifeState,
    OilLifeStateStore,
    compute_oil_life_pct,
    default_state,
    derive_running_state,
    now_utc,
    parse_iso_utc,
    to_iso_utc,
)


@dataclass
class DerivedOilLifeBackend:
    oil_life_max_run_hours: float
    state_path: str
    run_on_threshold: float = 25.0
    run_off_threshold: float = 20.0
    warning_interval_s: float = 300.0
    now_fn: Callable[[], datetime] = now_utc
    monotonic: Callable[[], float] = time.monotonic
    state_store_factory: Callable[[str | Path], OilLifeStateStore] = OilLifeStateStore
    metric_keys: frozenset[str] = field(default_factory=lambda: frozenset({"oil_life_pct"}))
    _state_store: OilLifeStateStore | None = field(default=None, init=False, repr=False)
    _state: OilLifeState | None = field(default=None, init=False, repr=False)
    _last_warning_at: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.oil_life_max_run_hours <= 0:
            raise ValueError("oil_life_max_run_hours must be > 0")
        if self.run_off_threshold > self.run_on_threshold:
            raise ValueError("run_off_threshold must be <= run_on_threshold")
        if self.warning_interval_s < 0:
            raise ValueError("warning_interval_s must be >= 0")

    def _warn(self, message: str) -> None:
        now = self.monotonic()
        if self._last_warning_at is None or (now - self._last_warning_at) >= self.warning_interval_s:
            print(f"[edgewatch-agent] derived warning: {message}")
            self._last_warning_at = now

    def _get_state_store(self) -> OilLifeStateStore:
        if self._state_store is None:
            self._state_store = self.state_store_factory(self.state_path)
        return self._state_store

    def _ensure_state(self) -> OilLifeState:
        if self._state is not None:
            return self._state

        store = self._get_state_store()
        now = self.now_fn().astimezone(timezone.utc)
        try:
            state = store.load()
        except FileNotFoundError:
            state = default_state(now=now)
            store.save(state)
        except Exception as exc:
            self._warn(f"failed to load oil-life state {self.state_path}: {exc}")
            state = default_state(now=now)
            store.save(state)

        self._state = state
        return state

    def _persist_state(self, state: OilLifeState) -> None:
        try:
            self._get_state_store().save(state)
        except Exception as exc:
            self._warn(f"failed to persist oil-life state {self.state_path}: {exc}")

    def _advance(self, *, metrics: Mapping[str, Any]) -> OilLifeState:
        state = self._ensure_state()
        now = self.now_fn().astimezone(timezone.utc)

        runtime_s = state.oil_life_runtime_s
        if state.oil_life_last_seen_running_at:
            previous_seen = parse_iso_utc(state.oil_life_last_seen_running_at)
            delta_s = max(0.0, (now - previous_seen).total_seconds())
            runtime_s += delta_s

        running = derive_running_state(
            metrics=metrics,
            previous_running=state.is_running,
            run_on_threshold=self.run_on_threshold,
            run_off_threshold=self.run_off_threshold,
        )
        last_seen = to_iso_utc(now) if running else None

        next_state = replace(
            state,
            oil_life_runtime_s=runtime_s,
            oil_life_last_seen_running_at=last_seen,
            is_running=running,
        )

        if next_state != state:
            self._persist_state(next_state)
        self._state = next_state
        return next_state

    def _oil_life_pct(self, state: OilLifeState) -> float:
        return compute_oil_life_pct(
            oil_life_runtime_s=state.oil_life_runtime_s,
            oil_life_max_run_hours=self.oil_life_max_run_hours,
        )

    def read_metrics_with_context(self, context: Mapping[str, Any]) -> Metrics:
        state = self._advance(metrics=context)
        return {"oil_life_pct": round(float(self._oil_life_pct(state)), 1)}

    def read_metrics(self) -> Metrics:
        return self.read_metrics_with_context({})
