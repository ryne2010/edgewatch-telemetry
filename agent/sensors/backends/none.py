from __future__ import annotations

from dataclasses import dataclass, field

from ..base import Metrics


@dataclass
class NoneSensorBackend:
    """Hardware-free backend that intentionally emits no sensor metrics."""

    metric_keys: frozenset[str] = field(default_factory=frozenset, init=False)

    def read_metrics(self) -> Metrics:
        return {}
