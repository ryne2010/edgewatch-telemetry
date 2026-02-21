from __future__ import annotations

from dataclasses import dataclass, field

from ..base import Metrics


@dataclass
class PlaceholderSensorBackend:
    """Used for planned backends that are not implemented yet."""

    backend_name: str
    metric_keys: frozenset[str]
    _warned: bool = field(default=False, init=False, repr=False)

    def read_metrics(self) -> Metrics:
        if not self._warned:
            print(
                f"[edgewatch-agent] sensor backend '{self.backend_name}' "
                "is not implemented yet; emitting None metrics"
            )
            self._warned = True
        return {key: None for key in self.metric_keys}
