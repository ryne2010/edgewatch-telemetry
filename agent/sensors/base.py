from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, TypeAlias

MetricValue: TypeAlias = float | int | str | bool | None
Metrics: TypeAlias = dict[str, MetricValue]


class SensorBackend(Protocol):
    """Small internal sensor interface used by the agent loop."""

    metric_keys: frozenset[str]

    def read_metrics(self) -> Metrics: ...


def normalize_metrics(
    *,
    metrics: Mapping[str, Any],
    expected_keys: frozenset[str],
) -> Metrics:
    """Return metrics constrained to the supported scalar contract."""

    out: Metrics = {}
    for key, value in metrics.items():
        if value is None or isinstance(value, (bool, int, float, str)):
            out[str(key)] = value
        else:
            out[str(key)] = None

    for key in expected_keys:
        out.setdefault(key, None)
    return out


@dataclass
class SafeSensorBackend:
    """Wraps a backend to guarantee no read exceptions escape the loop."""

    backend_name: str
    backend: SensorBackend
    metric_keys: frozenset[str] = field(init=False)
    _last_error: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.metric_keys = frozenset(getattr(self.backend, "metric_keys", frozenset()))

    def read_metrics(self) -> Metrics:
        try:
            raw = self.backend.read_metrics()
            return normalize_metrics(metrics=raw, expected_keys=self.metric_keys)
        except Exception as exc:
            signature = f"{type(exc).__name__}:{exc}"
            if signature != self._last_error:
                print(
                    f"[edgewatch-agent] sensor backend '{self.backend_name}' read failed: "
                    f"{type(exc).__name__}: {exc}"
                )
                self._last_error = signature
            return {key: None for key in self.metric_keys}
