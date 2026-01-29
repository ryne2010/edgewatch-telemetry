from __future__ import annotations

import math
import random
import time
from typing import Any, Dict


_rng = random.Random(42)


def read_metrics(device_id: str) -> Dict[str, Any]:
    """Mock sensor readings.

    Replace with real sensor integrations:
    - GPIO / I2C ADC readings
    - Modbus sensors
    - reading systemd/service health
    - etc.
    """
    t = time.time()

    # Simulate water pressure with slow oscillation + noise
    base = 45.0 + 10.0 * math.sin(t / 60.0)
    water_pressure = base + _rng.uniform(-2.0, 2.0)

    # Occasionally drop pressure low to trigger an alert
    if int(t) % 300 < 20:
        water_pressure = 20.0 + _rng.uniform(-1.0, 1.0)

    pump_on = water_pressure > 30.0
    oil_pressure = 55.0 + _rng.uniform(-3.0, 3.0) if pump_on else 0.0

    return {
        "water_pressure_psi": round(water_pressure, 1),
        "oil_pressure_psi": round(oil_pressure, 1),
        "pump_on": bool(pump_on),
        "battery_v": round(12.4 + _rng.uniform(-0.2, 0.2), 2),
        "signal_rssi": int(-65 + _rng.uniform(-5, 5)),
    }
