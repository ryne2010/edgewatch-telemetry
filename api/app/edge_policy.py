from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml


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

    battery_low_v: float
    battery_recover_v: float

    signal_low_rssi_dbm: float
    signal_recover_rssi_dbm: float


@dataclass(frozen=True)
class EdgePolicy:
    version: str
    sha256: str
    cache_max_age_s: int

    reporting: ReportingPolicy
    delta_thresholds: dict[str, float]
    alert_thresholds: AlertThresholds


def _repo_root() -> Path:
    # api/app/edge_policy.py -> api/app -> api -> repo root
    return Path(__file__).resolve().parents[2]


def _policy_path(version: str) -> Path:
    v = (version or "").strip()
    if not v:
        raise ValueError("policy version is empty")
    if "/" in v or ".." in v:
        raise ValueError("invalid policy version")
    return _repo_root() / "contracts" / "edge_policy" / f"{v}.yaml"


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


@lru_cache(maxsize=8)
def load_edge_policy(version: str) -> EdgePolicy:
    path = _policy_path(version)
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()

    data = yaml.safe_load(raw) or {}
    if not isinstance(data, Mapping):
        raise ValueError("edge policy must be a mapping")

    version_from_file = str(data.get("version") or version)
    cache_max_age_s = _require_int(data, "cache_max_age_s")

    reporting_raw = _require_mapping(data, "reporting")
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

    delta_raw = _require_mapping(data, "delta_thresholds")
    delta_thresholds: dict[str, float] = {}
    for k, v in delta_raw.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, bool):
            raise ValueError(f"delta_thresholds['{k}'] must be a number")
        if isinstance(v, (int, float)):
            delta_thresholds[k] = float(v)
        else:
            raise ValueError(f"delta_thresholds['{k}'] must be a number")

    alerts_raw = _require_mapping(data, "alert_thresholds")
    alert_thresholds = AlertThresholds(
        water_pressure_low_psi=_require_float(alerts_raw, "water_pressure_low_psi"),
        water_pressure_recover_psi=_require_float(alerts_raw, "water_pressure_recover_psi"),
        battery_low_v=_require_float(alerts_raw, "battery_low_v"),
        battery_recover_v=_require_float(alerts_raw, "battery_recover_v"),
        signal_low_rssi_dbm=_require_float(alerts_raw, "signal_low_rssi_dbm"),
        signal_recover_rssi_dbm=_require_float(alerts_raw, "signal_recover_rssi_dbm"),
    )

    return EdgePolicy(
        version=version_from_file,
        sha256=sha256,
        cache_max_age_s=cache_max_age_s,
        reporting=reporting,
        delta_thresholds=delta_thresholds,
        alert_thresholds=alert_thresholds,
    )
