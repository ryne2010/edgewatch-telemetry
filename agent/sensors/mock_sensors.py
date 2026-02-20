from __future__ import annotations

import hashlib
import math
import random
import re
import time
from typing import Any, Dict


_rng_by_device: dict[str, random.Random] = {}


def _device_index(device_id: str) -> int:
    m = re.search(r"(\d+)$", device_id)
    if not m:
        return 1
    try:
        return max(1, int(m.group(1)))
    except ValueError:
        return 1


def _rng_for(device_id: str) -> random.Random:
    rng = _rng_by_device.get(device_id)
    if rng is not None:
        return rng
    seed_bytes = hashlib.sha256(device_id.encode("utf-8")).digest()[:8]
    seed = int.from_bytes(seed_bytes, "big", signed=False)
    rng = random.Random(seed)
    _rng_by_device[device_id] = rng
    return rng


def read_metrics(device_id: str) -> Dict[str, Any]:
    """Mock sensor readings.

    Replace with real sensor integrations:
    - GPIO / I2C ADC readings
    - Modbus sensors
    - reading systemd/service health
    - etc.
    """
    t = time.time()
    idx = _device_index(device_id)
    rng = _rng_for(device_id)

    # Simulate water pressure with slow oscillation + noise
    base = 45.0 + 10.0 * math.sin(t / 60.0) + (idx - 1) * 2.5
    water_pressure = base + rng.uniform(-2.0, 2.0)

    # Occasionally drop pressure low to trigger an alert.
    # Keep the dip window long enough that a 30s heartbeat is likely to catch it.
    if int(t) % 300 < 90:
        water_pressure = 20.0 + (idx - 1) * 1.0 + rng.uniform(-1.0, 1.0)

    pump_on = water_pressure > 30.0
    oil_pressure = 55.0 + (idx - 1) * 1.0 + rng.uniform(-3.0, 3.0) if pump_on else 0.0
    battery_base = 12.5 - (idx - 1) * 0.05

    return {
        "water_pressure_psi": round(water_pressure, 1),
        "oil_pressure_psi": round(oil_pressure, 1),
        "pump_on": bool(pump_on),
        "battery_v": round(battery_base + rng.uniform(-0.2, 0.2), 2),
        "signal_rssi_dbm": int(-65 + (idx - 1) * -2 + rng.uniform(-5, 5)),
    }
