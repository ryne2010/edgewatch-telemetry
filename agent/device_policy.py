from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

import requests


@dataclass(frozen=True)
class ReportingPolicy:
    sample_interval_s: int
    alert_sample_interval_s: int
    heartbeat_interval_s: int
    alert_report_interval_s: int

    max_points_per_batch: int
    buffer_max_points: int
    buffer_max_age_s: int

    backoff_initial_s: int
    backoff_max_s: int


@dataclass(frozen=True)
class AlertThresholds:
    water_pressure_low_psi: float
    water_pressure_recover_psi: float

    oil_pressure_low_psi: float
    oil_pressure_recover_psi: float

    oil_level_low_pct: float
    oil_level_recover_pct: float

    drip_oil_level_low_pct: float
    drip_oil_level_recover_pct: float

    oil_life_low_pct: float
    oil_life_recover_pct: float

    battery_low_v: float
    battery_recover_v: float

    signal_low_rssi_dbm: float
    signal_recover_rssi_dbm: float


@dataclass(frozen=True)
class DevicePolicy:
    device_id: str
    policy_version: str
    policy_sha256: str
    cache_max_age_s: int

    heartbeat_interval_s: int
    offline_after_s: int

    reporting: ReportingPolicy
    delta_thresholds: Dict[str, float]
    alert_thresholds: AlertThresholds


@dataclass(frozen=True)
class CachedPolicy:
    policy: DevicePolicy
    etag: str
    fetched_at: float


def _require_int(obj: Mapping[str, Any], key: str) -> int:
    v = obj.get(key)
    if isinstance(v, bool):
        raise ValueError(f"'{key}' must be an int")
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    raise ValueError(f"'{key}' must be an int")


def _require_float(obj: Mapping[str, Any], key: str) -> float:
    v = obj.get(key)
    if isinstance(v, bool):
        raise ValueError(f"'{key}' must be a number")
    if isinstance(v, (int, float)):
        return float(v)
    raise ValueError(f"'{key}' must be a number")


def _require_mapping(obj: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    v = obj.get(key)
    if not isinstance(v, Mapping):
        raise ValueError(f"'{key}' must be a mapping")
    return v


def parse_device_policy(payload: Mapping[str, Any]) -> DevicePolicy:
    reporting_raw = _require_mapping(payload, "reporting")
    alerts_raw = _require_mapping(payload, "alert_thresholds")

    delta_raw = payload.get("delta_thresholds")
    if not isinstance(delta_raw, Mapping):
        raise ValueError("'delta_thresholds' must be a mapping")

    delta: Dict[str, float] = {}
    for k, v in delta_raw.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, bool):
            raise ValueError(f"delta_thresholds['{k}'] must be a number")
        if isinstance(v, (int, float)):
            delta[k] = float(v)
        else:
            raise ValueError(f"delta_thresholds['{k}'] must be a number")

    reporting = ReportingPolicy(
        sample_interval_s=_require_int(reporting_raw, "sample_interval_s"),
        alert_sample_interval_s=_require_int(reporting_raw, "alert_sample_interval_s"),
        heartbeat_interval_s=_require_int(reporting_raw, "heartbeat_interval_s"),
        alert_report_interval_s=_require_int(reporting_raw, "alert_report_interval_s"),
        max_points_per_batch=_require_int(reporting_raw, "max_points_per_batch"),
        buffer_max_points=_require_int(reporting_raw, "buffer_max_points"),
        buffer_max_age_s=_require_int(reporting_raw, "buffer_max_age_s"),
        backoff_initial_s=_require_int(reporting_raw, "backoff_initial_s"),
        backoff_max_s=_require_int(reporting_raw, "backoff_max_s"),
    )

    alerts = AlertThresholds(
        water_pressure_low_psi=_require_float(alerts_raw, "water_pressure_low_psi"),
        water_pressure_recover_psi=_require_float(alerts_raw, "water_pressure_recover_psi"),
        oil_pressure_low_psi=_require_float(alerts_raw, "oil_pressure_low_psi"),
        oil_pressure_recover_psi=_require_float(alerts_raw, "oil_pressure_recover_psi"),
        oil_level_low_pct=_require_float(alerts_raw, "oil_level_low_pct"),
        oil_level_recover_pct=_require_float(alerts_raw, "oil_level_recover_pct"),
        drip_oil_level_low_pct=_require_float(alerts_raw, "drip_oil_level_low_pct"),
        drip_oil_level_recover_pct=_require_float(alerts_raw, "drip_oil_level_recover_pct"),
        oil_life_low_pct=_require_float(alerts_raw, "oil_life_low_pct"),
        oil_life_recover_pct=_require_float(alerts_raw, "oil_life_recover_pct"),
        battery_low_v=_require_float(alerts_raw, "battery_low_v"),
        battery_recover_v=_require_float(alerts_raw, "battery_recover_v"),
        signal_low_rssi_dbm=_require_float(alerts_raw, "signal_low_rssi_dbm"),
        signal_recover_rssi_dbm=_require_float(alerts_raw, "signal_recover_rssi_dbm"),
    )

    return DevicePolicy(
        device_id=str(payload.get("device_id") or ""),
        policy_version=str(payload.get("policy_version") or ""),
        policy_sha256=str(payload.get("policy_sha256") or ""),
        cache_max_age_s=_require_int(payload, "cache_max_age_s"),
        heartbeat_interval_s=_require_int(payload, "heartbeat_interval_s"),
        offline_after_s=_require_int(payload, "offline_after_s"),
        reporting=reporting,
        delta_thresholds=delta,
        alert_thresholds=alerts,
    )


def _default_cache_path() -> Path:
    # Default to a small local file next to the agent.
    # Include the device id to avoid collisions when simulating a fleet.
    # Devices can override with EDGEWATCH_POLICY_CACHE_PATH.
    device_id = os.getenv("EDGEWATCH_DEVICE_ID", "device")
    default = f"./edgewatch_policy_cache_{device_id}.json"
    return Path(os.getenv("EDGEWATCH_POLICY_CACHE_PATH", default))


def load_cached_policy(path: Optional[Path] = None) -> Optional[CachedPolicy]:
    p = path or _default_cache_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    etag = data.get("etag")
    fetched_at = data.get("fetched_at")
    payload = data.get("policy")

    if not isinstance(etag, str) or not isinstance(fetched_at, (int, float)) or not isinstance(payload, dict):
        return None

    try:
        policy = parse_device_policy(payload)
    except Exception:
        return None

    return CachedPolicy(policy=policy, etag=etag, fetched_at=float(fetched_at))


def save_cached_policy(policy: DevicePolicy, etag: str, *, path: Optional[Path] = None) -> None:
    p = path or _default_cache_path()
    blob = {
        "etag": etag,
        "fetched_at": time.time(),
        "policy": {
            "device_id": policy.device_id,
            "policy_version": policy.policy_version,
            "policy_sha256": policy.policy_sha256,
            "cache_max_age_s": policy.cache_max_age_s,
            "heartbeat_interval_s": policy.heartbeat_interval_s,
            "offline_after_s": policy.offline_after_s,
            "reporting": {
                "sample_interval_s": policy.reporting.sample_interval_s,
                "alert_sample_interval_s": policy.reporting.alert_sample_interval_s,
                "heartbeat_interval_s": policy.reporting.heartbeat_interval_s,
                "alert_report_interval_s": policy.reporting.alert_report_interval_s,
                "max_points_per_batch": policy.reporting.max_points_per_batch,
                "buffer_max_points": policy.reporting.buffer_max_points,
                "buffer_max_age_s": policy.reporting.buffer_max_age_s,
                "backoff_initial_s": policy.reporting.backoff_initial_s,
                "backoff_max_s": policy.reporting.backoff_max_s,
            },
            "delta_thresholds": policy.delta_thresholds,
            "alert_thresholds": {
                "water_pressure_low_psi": policy.alert_thresholds.water_pressure_low_psi,
                "water_pressure_recover_psi": policy.alert_thresholds.water_pressure_recover_psi,
                "oil_pressure_low_psi": policy.alert_thresholds.oil_pressure_low_psi,
                "oil_pressure_recover_psi": policy.alert_thresholds.oil_pressure_recover_psi,
                "oil_level_low_pct": policy.alert_thresholds.oil_level_low_pct,
                "oil_level_recover_pct": policy.alert_thresholds.oil_level_recover_pct,
                "drip_oil_level_low_pct": policy.alert_thresholds.drip_oil_level_low_pct,
                "drip_oil_level_recover_pct": policy.alert_thresholds.drip_oil_level_recover_pct,
                "oil_life_low_pct": policy.alert_thresholds.oil_life_low_pct,
                "oil_life_recover_pct": policy.alert_thresholds.oil_life_recover_pct,
                "battery_low_v": policy.alert_thresholds.battery_low_v,
                "battery_recover_v": policy.alert_thresholds.battery_recover_v,
                "signal_low_rssi_dbm": policy.alert_thresholds.signal_low_rssi_dbm,
                "signal_recover_rssi_dbm": policy.alert_thresholds.signal_recover_rssi_dbm,
            },
        },
    }
    p.write_text(json.dumps(blob, indent=2, sort_keys=True), encoding="utf-8")


def fetch_device_policy(
    session: requests.Session,
    *,
    api_url: str,
    token: str,
    cached: Optional[CachedPolicy] = None,
    timeout_s: float = 5.0,
) -> Tuple[Optional[DevicePolicy], Optional[str], Optional[int]]:
    """Fetch /api/v1/device-policy with ETag support.

    Returns: (policy, etag, cache_max_age_s)
    """

    headers = {"Authorization": f"Bearer {token}"}
    if cached is not None and cached.etag:
        headers["If-None-Match"] = cached.etag

    resp = session.get(f"{api_url.rstrip('/')}/api/v1/device-policy", headers=headers, timeout=timeout_s)

    if resp.status_code == 304 and cached is not None:
        max_age = _parse_cache_max_age(resp.headers.get("Cache-Control"))
        return cached.policy, cached.etag, max_age

    if 200 <= resp.status_code < 300:
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError("device-policy response was not a JSON object")
        policy = parse_device_policy(data)
        etag = resp.headers.get("ETag")
        if etag is None:
            etag = ""
        max_age = _parse_cache_max_age(resp.headers.get("Cache-Control"))
        return policy, etag, max_age

    raise RuntimeError(f"device-policy fetch failed: {resp.status_code} {resp.text[:200]}")


def _parse_cache_max_age(cache_control: Optional[str]) -> Optional[int]:
    if not cache_control:
        return None
    parts = [p.strip() for p in cache_control.split(",")]
    for p in parts:
        if p.startswith("max-age="):
            try:
                return int(p.split("=", 1)[1])
            except Exception:
                return None
    return None
