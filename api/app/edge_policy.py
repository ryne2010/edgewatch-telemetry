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
    microphone_offline_db: float
    microphone_offline_open_consecutive_samples: int
    microphone_offline_resolve_consecutive_samples: int

    water_pressure_low_psi: float
    water_pressure_recover_psi: float

    oil_pressure_low_psi: float
    oil_pressure_recover_psi: float

    oil_level_low_pct: float
    oil_level_recover_pct: float

    drip_oil_level_low_pct: float
    drip_oil_level_recover_pct: float

    # Runtime-derived metric; typically reset manually after service.
    oil_life_low_pct: float
    oil_life_recover_pct: float

    battery_low_v: float
    battery_recover_v: float

    signal_low_rssi_dbm: float
    signal_recover_rssi_dbm: float


@dataclass(frozen=True)
class CostCapsPolicy:
    max_bytes_per_day: int
    max_snapshots_per_day: int
    max_media_uploads_per_day: int


@dataclass(frozen=True)
class PowerManagementPolicy:
    enabled: bool
    mode: str
    input_warn_min_v: float
    input_warn_max_v: float
    input_critical_min_v: float
    input_critical_max_v: float
    sustainable_input_w: float
    unsustainable_window_s: int
    battery_trend_window_s: int
    battery_drop_warn_v: float
    saver_sample_interval_s: int
    saver_heartbeat_interval_s: int
    media_disabled_in_saver: bool


@dataclass(frozen=True)
class OperationDefaultsPolicy:
    default_sleep_poll_interval_s: int
    disable_requires_manual_restart: bool
    admin_remote_shutdown_enabled: bool
    shutdown_grace_s_default: int
    control_command_ttl_s: int


@dataclass(frozen=True)
class EdgePolicy:
    version: str
    sha256: str
    cache_max_age_s: int

    reporting: ReportingPolicy
    delta_thresholds: dict[str, float]
    alert_thresholds: AlertThresholds
    cost_caps: CostCapsPolicy
    power_management: PowerManagementPolicy
    operation_defaults: OperationDefaultsPolicy


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


def _validate_recover_gt_low(name: str, low: float, recover: float) -> None:
    if recover <= low:
        raise ValueError(f"Invalid alert thresholds for {name}: recover ({recover}) must be > low ({low})")


def _validate_alert_thresholds(t: AlertThresholds) -> None:
    if t.microphone_offline_db <= 0:
        raise ValueError("Invalid alert threshold for microphone_offline_db: must be > 0")
    if t.microphone_offline_open_consecutive_samples <= 0:
        raise ValueError(
            "Invalid alert threshold for microphone_offline_open_consecutive_samples: must be > 0"
        )
    if t.microphone_offline_resolve_consecutive_samples <= 0:
        raise ValueError(
            "Invalid alert threshold for microphone_offline_resolve_consecutive_samples: must be > 0"
        )
    _validate_recover_gt_low("water_pressure", t.water_pressure_low_psi, t.water_pressure_recover_psi)
    _validate_recover_gt_low("oil_pressure", t.oil_pressure_low_psi, t.oil_pressure_recover_psi)
    _validate_recover_gt_low("oil_level", t.oil_level_low_pct, t.oil_level_recover_pct)
    _validate_recover_gt_low("drip_oil_level", t.drip_oil_level_low_pct, t.drip_oil_level_recover_pct)
    _validate_recover_gt_low("oil_life", t.oil_life_low_pct, t.oil_life_recover_pct)
    _validate_recover_gt_low("battery", t.battery_low_v, t.battery_recover_v)
    _validate_recover_gt_low("signal", t.signal_low_rssi_dbm, t.signal_recover_rssi_dbm)


def _validate_delta_thresholds(delta_thresholds: dict[str, float]) -> None:
    for k, v in delta_thresholds.items():
        if v <= 0:
            raise ValueError(f"Invalid delta threshold for {k}: {v} (must be > 0)")


def _validate_cost_caps(caps: CostCapsPolicy) -> None:
    if caps.max_bytes_per_day <= 0:
        raise ValueError("cost_caps.max_bytes_per_day must be > 0")
    if caps.max_snapshots_per_day <= 0:
        raise ValueError("cost_caps.max_snapshots_per_day must be > 0")
    if caps.max_media_uploads_per_day <= 0:
        raise ValueError("cost_caps.max_media_uploads_per_day must be > 0")


def _validate_power_management(power: PowerManagementPolicy) -> None:
    if power.mode not in {"dual", "hardware", "fallback"}:
        raise ValueError("power_management.mode must be one of: dual, hardware, fallback")
    if power.input_critical_min_v >= power.input_warn_min_v:
        raise ValueError("power_management.input_critical_min_v must be < input_warn_min_v")
    if power.input_warn_min_v >= power.input_warn_max_v:
        raise ValueError("power_management.input_warn_min_v must be < input_warn_max_v")
    if power.input_warn_max_v >= power.input_critical_max_v:
        raise ValueError("power_management.input_warn_max_v must be < input_critical_max_v")
    if power.sustainable_input_w <= 0:
        raise ValueError("power_management.sustainable_input_w must be > 0")
    if power.unsustainable_window_s <= 0:
        raise ValueError("power_management.unsustainable_window_s must be > 0")
    if power.battery_trend_window_s <= 0:
        raise ValueError("power_management.battery_trend_window_s must be > 0")
    if power.battery_drop_warn_v <= 0:
        raise ValueError("power_management.battery_drop_warn_v must be > 0")
    if power.saver_sample_interval_s <= 0:
        raise ValueError("power_management.saver_sample_interval_s must be > 0")
    if power.saver_heartbeat_interval_s <= 0:
        raise ValueError("power_management.saver_heartbeat_interval_s must be > 0")


def _validate_operation_defaults(operation_defaults: OperationDefaultsPolicy) -> None:
    if operation_defaults.default_sleep_poll_interval_s <= 0:
        raise ValueError("operation_defaults.default_sleep_poll_interval_s must be > 0")
    if operation_defaults.shutdown_grace_s_default <= 0:
        raise ValueError("operation_defaults.shutdown_grace_s_default must be > 0")
    if operation_defaults.shutdown_grace_s_default > 3600:
        raise ValueError("operation_defaults.shutdown_grace_s_default must be <= 3600")
    if operation_defaults.control_command_ttl_s <= 0:
        raise ValueError("operation_defaults.control_command_ttl_s must be > 0")


def _bool_with_default(obj: Mapping[str, Any], key: str, default: bool) -> bool:
    raw = obj.get(key)
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    raise ValueError(f"'{key}' must be a bool")


def _string_with_default(obj: Mapping[str, Any], key: str, default: str) -> str:
    raw = obj.get(key)
    if raw is None:
        return default
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    raise ValueError(f"'{key}' must be a non-empty string")


def _int_with_default(obj: Mapping[str, Any], key: str, default: int) -> int:
    raw = obj.get(key)
    if raw is None:
        return default
    if isinstance(raw, bool):
        raise ValueError(f"'{key}' must be an int")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float) and raw.is_integer():
        return int(raw)
    raise ValueError(f"'{key}' must be an int")


def _float_with_default(obj: Mapping[str, Any], key: str, default: float) -> float:
    raw = obj.get(key)
    if raw is None:
        return default
    if isinstance(raw, bool):
        raise ValueError(f"'{key}' must be a number")
    if isinstance(raw, (int, float)):
        return float(raw)
    raise ValueError(f"'{key}' must be a number")


def _require_mapping(obj: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    v = obj.get(key)
    if not isinstance(v, Mapping):
        raise ValueError(f"'{key}' must be a mapping")
    return v


def _parse_edge_policy(version: str, raw: bytes) -> EdgePolicy:
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
        microphone_offline_db=_require_float(alerts_raw, "microphone_offline_db"),
        microphone_offline_open_consecutive_samples=_int_with_default(
            alerts_raw, "microphone_offline_open_consecutive_samples", 2
        ),
        microphone_offline_resolve_consecutive_samples=_int_with_default(
            alerts_raw, "microphone_offline_resolve_consecutive_samples", 1
        ),
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

    cost_caps_raw = _require_mapping(data, "cost_caps")
    cost_caps = CostCapsPolicy(
        max_bytes_per_day=_require_int(cost_caps_raw, "max_bytes_per_day"),
        max_snapshots_per_day=_require_int(cost_caps_raw, "max_snapshots_per_day"),
        max_media_uploads_per_day=_require_int(cost_caps_raw, "max_media_uploads_per_day"),
    )

    power_raw = data.get("power_management")
    if power_raw is None:
        power_raw = {}
    if not isinstance(power_raw, Mapping):
        raise ValueError("'power_management' must be a mapping")
    power_management = PowerManagementPolicy(
        enabled=_bool_with_default(power_raw, "enabled", True),
        mode=_string_with_default(power_raw, "mode", "dual"),
        input_warn_min_v=_float_with_default(power_raw, "input_warn_min_v", 11.8),
        input_warn_max_v=_float_with_default(power_raw, "input_warn_max_v", 14.8),
        input_critical_min_v=_float_with_default(power_raw, "input_critical_min_v", 11.4),
        input_critical_max_v=_float_with_default(power_raw, "input_critical_max_v", 15.2),
        sustainable_input_w=_float_with_default(power_raw, "sustainable_input_w", 15.0),
        unsustainable_window_s=_int_with_default(power_raw, "unsustainable_window_s", 900),
        battery_trend_window_s=_int_with_default(power_raw, "battery_trend_window_s", 1800),
        battery_drop_warn_v=_float_with_default(power_raw, "battery_drop_warn_v", 0.25),
        saver_sample_interval_s=_int_with_default(power_raw, "saver_sample_interval_s", 1200),
        saver_heartbeat_interval_s=_int_with_default(power_raw, "saver_heartbeat_interval_s", 1800),
        media_disabled_in_saver=_bool_with_default(power_raw, "media_disabled_in_saver", True),
    )
    operation_raw = data.get("operation_defaults")
    if operation_raw is None:
        operation_raw = {}
    if not isinstance(operation_raw, Mapping):
        raise ValueError("'operation_defaults' must be a mapping")
    operation_defaults = OperationDefaultsPolicy(
        default_sleep_poll_interval_s=_int_with_default(
            operation_raw, "default_sleep_poll_interval_s", 7 * 24 * 3600
        ),
        disable_requires_manual_restart=_bool_with_default(
            operation_raw, "disable_requires_manual_restart", True
        ),
        admin_remote_shutdown_enabled=_bool_with_default(
            operation_raw, "admin_remote_shutdown_enabled", True
        ),
        shutdown_grace_s_default=_int_with_default(operation_raw, "shutdown_grace_s_default", 30),
        control_command_ttl_s=_int_with_default(operation_raw, "control_command_ttl_s", 180 * 24 * 3600),
    )

    _validate_alert_thresholds(alert_thresholds)
    _validate_delta_thresholds(delta_thresholds)
    _validate_cost_caps(cost_caps)
    _validate_power_management(power_management)
    _validate_operation_defaults(operation_defaults)

    return EdgePolicy(
        version=version_from_file,
        sha256=sha256,
        cache_max_age_s=cache_max_age_s,
        reporting=reporting,
        delta_thresholds=delta_thresholds,
        alert_thresholds=alert_thresholds,
        cost_caps=cost_caps,
        power_management=power_management,
        operation_defaults=operation_defaults,
    )


@lru_cache(maxsize=8)
def load_edge_policy(version: str) -> EdgePolicy:
    path = _policy_path(version)
    raw = path.read_bytes()
    return _parse_edge_policy(version, raw)


def load_edge_policy_source(version: str) -> str:
    path = _policy_path(version)
    return path.read_text(encoding="utf-8")


def save_edge_policy_source(version: str, yaml_text: str) -> EdgePolicy:
    path = _policy_path(version)
    if not path.exists():
        raise ValueError(f"edge policy contract file not found for version '{version}'")

    normalized = (yaml_text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        raise ValueError("edge policy content is empty")
    if not normalized.endswith("\n"):
        normalized += "\n"

    raw = normalized.encode("utf-8")
    parsed = _parse_edge_policy(version, raw)
    if parsed.version != version:
        raise ValueError(f"edge policy version mismatch: expected '{version}' but found '{parsed.version}'")

    path.write_bytes(raw)
    load_edge_policy.cache_clear()
    return parsed
