from __future__ import annotations

import hashlib
import math
import random
import re
import time
from typing import Any, Dict


_rng_by_device: dict[str, random.Random] = {}
_location_by_device: dict[str, tuple[float, float]] = {}

SPRINGFIELD_CO_CENTER_LAT = 37.4083
SPRINGFIELD_CO_CENTER_LON = -102.6144
SPRINGFIELD_CO_RADIUS_MI = 50.0
EARTH_RADIUS_MI = 3958.7613


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


def _normalize_lon(lon_deg: float) -> float:
    return ((lon_deg + 180.0) % 360.0) - 180.0


def _location_for(device_id: str) -> tuple[float, float]:
    location = _location_by_device.get(device_id)
    if location is not None:
        return location
    seed_bytes = hashlib.sha256(f"{device_id}:geo".encode("utf-8")).digest()
    # Deterministically place demo devices within a 50-mile radius of Springfield, CO.
    u = int.from_bytes(seed_bytes[:8], "big") / float((1 << 64) - 1)
    v = int.from_bytes(seed_bytes[8:16], "big") / float((1 << 64) - 1)
    distance_mi = SPRINGFIELD_CO_RADIUS_MI * math.sqrt(u)
    bearing_rad = 2.0 * math.pi * v

    lat1_rad = math.radians(SPRINGFIELD_CO_CENTER_LAT)
    lon1_rad = math.radians(SPRINGFIELD_CO_CENTER_LON)
    angular_distance = distance_mi / EARTH_RADIUS_MI

    lat2_rad = math.asin(
        math.sin(lat1_rad) * math.cos(angular_distance)
        + math.cos(lat1_rad) * math.sin(angular_distance) * math.cos(bearing_rad)
    )
    lon2_rad = lon1_rad + math.atan2(
        math.sin(bearing_rad) * math.sin(angular_distance) * math.cos(lat1_rad),
        math.cos(angular_distance) - math.sin(lat1_rad) * math.sin(lat2_rad),
    )

    lat = math.degrees(lat2_rad)
    lon = _normalize_lon(math.degrees(lon2_rad))
    location = (round(lat, 6), round(lon, 6))
    _location_by_device[device_id] = location
    return location


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

    # Ambient conditions
    temperature_c = 10.0 + 12.0 * math.sin(t / 300.0) + rng.uniform(-0.4, 0.4)
    humidity_pct = 45.0 + 20.0 * math.sin(t / 420.0 + idx) + rng.uniform(-1.5, 1.5)
    humidity_pct = max(0.0, min(100.0, humidity_pct))

    # Levels (percent). In real deployments, these come from level sensors.
    # - oil_level_pct: main reservoir
    # - drip_oil_level_pct: small drip oiler reservoir
    oil_level_pct = 70.0 + 20.0 * math.sin(t / 900.0 + idx) + rng.uniform(-1.0, 1.0)
    drip_oil_level_pct = 60.0 + 25.0 * math.sin(t / 780.0 + idx * 0.7) + rng.uniform(-1.0, 1.0)
    oil_level_pct = max(0.0, min(100.0, oil_level_pct))
    drip_oil_level_pct = max(0.0, min(100.0, drip_oil_level_pct))

    # Oil life is typically a *derived* metric (hours, temp, pressure cycles).
    # For the simulator, treat it as a slow sawtooth from 100 -> 0.
    cycle_s = 6 * 60 * 60
    oil_life_pct = 100.0 - (t % cycle_s) / cycle_s * 100.0

    battery_v = round(battery_base + rng.uniform(-0.2, 0.2), 2)
    signal_rssi_dbm = int(-65 + (idx - 1) * -2 + rng.uniform(-5, 5))
    latitude, longitude = _location_for(device_id)

    # Simple flow model so dashboards can render a plausible gpm trace.
    flow_rate_gpm = 0.0
    if pump_on:
        flow_rate_gpm = 22.0 + 6.0 * math.sin(t / 120.0 + idx) + rng.uniform(-0.8, 0.8)
        flow_rate_gpm = max(0.0, flow_rate_gpm)

    device_state = "OK"
    if water_pressure < 25.0 or battery_v < 11.8 or signal_rssi_dbm < -95:
        device_state = "WARN"

    return {
        "water_pressure_psi": round(water_pressure, 1),
        "oil_pressure_psi": round(oil_pressure, 1),
        "temperature_c": round(temperature_c, 1),
        "humidity_pct": round(humidity_pct, 1),
        "oil_level_pct": round(oil_level_pct, 1),
        "oil_life_pct": round(oil_life_pct, 1),
        "drip_oil_level_pct": round(drip_oil_level_pct, 1),
        "pump_on": bool(pump_on),
        "flow_rate_gpm": round(flow_rate_gpm, 1),
        "device_state": device_state,
        "battery_v": battery_v,
        "signal_rssi_dbm": signal_rssi_dbm,
        "latitude": latitude,
        "longitude": longitude,
    }
