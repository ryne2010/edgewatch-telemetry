from __future__ import annotations

from dataclasses import dataclass, field

from ..base import Metrics
from ..mock_sensors import read_metrics as read_mock_metrics


@dataclass
class MockSensorBackend:
    """Default local/backend-agnostic sensor implementation."""

    device_id: str
    metric_keys: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "water_pressure_psi",
                "microphone_level_db",
                "oil_pressure_psi",
                "temperature_c",
                "humidity_pct",
                "oil_level_pct",
                "oil_life_pct",
                "drip_oil_level_pct",
                "pump_on",
                "flow_rate_gpm",
                "device_state",
                "battery_v",
                "signal_rssi_dbm",
            }
        )
    )

    def read_metrics(self) -> Metrics:
        return read_mock_metrics(device_id=self.device_id)
