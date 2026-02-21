from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from ..base import Metrics, SensorBackend, normalize_metrics


@runtime_checkable
class ContextAwareBackend(Protocol):
    def read_metrics_with_context(self, context: Mapping[str, Any]) -> Metrics: ...


@dataclass
class CompositeSensorBackend:
    """Combines multiple backends into one merged metrics payload."""

    backends: list[SensorBackend]
    metric_keys: frozenset[str] = field(init=False)

    def __post_init__(self) -> None:
        keys: set[str] = set()
        for backend in self.backends:
            keys.update(getattr(backend, "metric_keys", frozenset()))
        self.metric_keys = frozenset(keys)

    def read_metrics(self) -> Metrics:
        merged: Metrics = {}
        for backend in self.backends:
            backend_keys = frozenset(getattr(backend, "metric_keys", frozenset()))
            try:
                if isinstance(backend, ContextAwareBackend):
                    raw_metrics = backend.read_metrics_with_context(dict(merged))
                else:
                    raw_metrics = backend.read_metrics()
                current = normalize_metrics(
                    metrics=raw_metrics,
                    expected_keys=backend_keys,
                )
                merged.update(current)
            except Exception as exc:
                print(
                    "[edgewatch-agent] composite sensor backend child read failed: "
                    f"{type(exc).__name__}: {exc}"
                )
                for key in backend_keys:
                    merged.setdefault(key, None)

        for key in self.metric_keys:
            merged.setdefault(key, None)
        return merged
