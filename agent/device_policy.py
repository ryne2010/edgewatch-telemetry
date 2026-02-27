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

    oil_life_low_pct: float
    oil_life_recover_pct: float

    battery_low_v: float
    battery_recover_v: float

    signal_low_rssi_dbm: float
    signal_recover_rssi_dbm: float


@dataclass(frozen=True)
class CostCaps:
    max_bytes_per_day: int
    max_snapshots_per_day: int
    max_media_uploads_per_day: int


@dataclass(frozen=True)
class PowerManagement:
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
class PendingControlCommand:
    id: str
    issued_at: str
    expires_at: str
    operation_mode: str
    sleep_poll_interval_s: int
    shutdown_requested: bool
    shutdown_grace_s: int
    alerts_muted_until: str | None
    alerts_muted_reason: str | None


@dataclass(frozen=True)
class DevicePolicy:
    device_id: str
    policy_version: str
    policy_sha256: str
    cache_max_age_s: int

    heartbeat_interval_s: int
    offline_after_s: int
    operation_mode: str
    sleep_poll_interval_s: int
    disable_requires_manual_restart: bool

    reporting: ReportingPolicy
    delta_thresholds: Dict[str, float]
    alert_thresholds: AlertThresholds
    cost_caps: CostCaps
    power_management: PowerManagement
    pending_control_command: PendingControlCommand | None


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


def _float_with_default(obj: Mapping[str, Any], key: str, default: float) -> float:
    if key not in obj:
        return default
    return _require_float(obj, key)


def _int_with_default(obj: Mapping[str, Any], key: str, default: int) -> int:
    if key not in obj:
        return default
    return _require_int(obj, key)


def _bool_with_default(obj: Mapping[str, Any], key: str, default: bool) -> bool:
    if key not in obj:
        return default
    value = obj.get(key)
    if isinstance(value, bool):
        return value
    raise ValueError(f"'{key}' must be a bool")


def _string_with_default(obj: Mapping[str, Any], key: str, default: str) -> str:
    if key not in obj:
        return default
    value = obj.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError(f"'{key}' must be a non-empty string")


def _require_mapping(obj: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    v = obj.get(key)
    if not isinstance(v, Mapping):
        raise ValueError(f"'{key}' must be a mapping")
    return v


def parse_device_policy(payload: Mapping[str, Any]) -> DevicePolicy:
    reporting_raw = _require_mapping(payload, "reporting")
    alerts_raw = _require_mapping(payload, "alert_thresholds")
    cost_caps_raw = payload.get("cost_caps")

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
        microphone_offline_db=_float_with_default(alerts_raw, "microphone_offline_db", 60.0),
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

    if cost_caps_raw is None:
        # Backward-compatible fallback for older policy payloads.
        cost_caps = CostCaps(
            max_bytes_per_day=50_000_000,
            max_snapshots_per_day=48,
            max_media_uploads_per_day=48,
        )
    else:
        if not isinstance(cost_caps_raw, Mapping):
            raise ValueError("'cost_caps' must be a mapping")
        cost_caps = CostCaps(
            max_bytes_per_day=_require_int(cost_caps_raw, "max_bytes_per_day"),
            max_snapshots_per_day=_require_int(cost_caps_raw, "max_snapshots_per_day"),
            max_media_uploads_per_day=_require_int(cost_caps_raw, "max_media_uploads_per_day"),
        )
    if cost_caps.max_bytes_per_day <= 0:
        raise ValueError("'cost_caps.max_bytes_per_day' must be > 0")
    if cost_caps.max_snapshots_per_day <= 0:
        raise ValueError("'cost_caps.max_snapshots_per_day' must be > 0")
    if cost_caps.max_media_uploads_per_day <= 0:
        raise ValueError("'cost_caps.max_media_uploads_per_day' must be > 0")
    if alerts.microphone_offline_open_consecutive_samples <= 0:
        raise ValueError("'alert_thresholds.microphone_offline_open_consecutive_samples' must be > 0")
    if alerts.microphone_offline_resolve_consecutive_samples <= 0:
        raise ValueError("'alert_thresholds.microphone_offline_resolve_consecutive_samples' must be > 0")

    power_raw = payload.get("power_management")
    if power_raw is None:
        power_raw = {}
    if not isinstance(power_raw, Mapping):
        raise ValueError("'power_management' must be a mapping")
    power_management = PowerManagement(
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

    if power_management.mode not in {"dual", "hardware", "fallback"}:
        raise ValueError("'power_management.mode' must be one of: dual, hardware, fallback")
    if power_management.input_critical_min_v >= power_management.input_warn_min_v:
        raise ValueError("'power_management.input_critical_min_v' must be < input_warn_min_v")
    if power_management.input_warn_min_v >= power_management.input_warn_max_v:
        raise ValueError("'power_management.input_warn_min_v' must be < input_warn_max_v")
    if power_management.input_warn_max_v >= power_management.input_critical_max_v:
        raise ValueError("'power_management.input_warn_max_v' must be < input_critical_max_v")
    if power_management.sustainable_input_w <= 0:
        raise ValueError("'power_management.sustainable_input_w' must be > 0")
    if power_management.unsustainable_window_s <= 0:
        raise ValueError("'power_management.unsustainable_window_s' must be > 0")
    if power_management.battery_trend_window_s <= 0:
        raise ValueError("'power_management.battery_trend_window_s' must be > 0")
    if power_management.battery_drop_warn_v <= 0:
        raise ValueError("'power_management.battery_drop_warn_v' must be > 0")
    if power_management.saver_sample_interval_s <= 0:
        raise ValueError("'power_management.saver_sample_interval_s' must be > 0")
    if power_management.saver_heartbeat_interval_s <= 0:
        raise ValueError("'power_management.saver_heartbeat_interval_s' must be > 0")
    operation_mode = _string_with_default(payload, "operation_mode", "active").lower()
    if operation_mode not in {"active", "sleep", "disabled"}:
        raise ValueError("'operation_mode' must be one of: active, sleep, disabled")
    sleep_poll_interval_s = _int_with_default(payload, "sleep_poll_interval_s", 7 * 24 * 3600)
    if sleep_poll_interval_s <= 0:
        raise ValueError("'sleep_poll_interval_s' must be > 0")
    disable_requires_manual_restart = _bool_with_default(payload, "disable_requires_manual_restart", True)

    pending_raw = payload.get("pending_control_command")
    pending_control_command: PendingControlCommand | None = None
    if pending_raw is not None:
        if not isinstance(pending_raw, Mapping):
            raise ValueError("'pending_control_command' must be a mapping")
        pending_id = _string_with_default(pending_raw, "id", "")
        if not pending_id:
            raise ValueError("'pending_control_command.id' must be a non-empty string")
        issued_at = _string_with_default(pending_raw, "issued_at", "")
        if not issued_at:
            raise ValueError("'pending_control_command.issued_at' must be a non-empty string")
        expires_at = _string_with_default(pending_raw, "expires_at", "")
        if not expires_at:
            raise ValueError("'pending_control_command.expires_at' must be a non-empty string")
        pending_operation_mode = _string_with_default(pending_raw, "operation_mode", "active").lower()
        if pending_operation_mode not in {"active", "sleep", "disabled"}:
            raise ValueError(
                "'pending_control_command.operation_mode' must be one of: active, sleep, disabled"
            )
        pending_sleep_poll_interval_s = _int_with_default(pending_raw, "sleep_poll_interval_s", 7 * 24 * 3600)
        if pending_sleep_poll_interval_s <= 0:
            raise ValueError("'pending_control_command.sleep_poll_interval_s' must be > 0")
        pending_shutdown_requested = _bool_with_default(pending_raw, "shutdown_requested", False)
        pending_shutdown_grace_s = _int_with_default(pending_raw, "shutdown_grace_s", 30)
        if pending_shutdown_grace_s <= 0:
            raise ValueError("'pending_control_command.shutdown_grace_s' must be > 0")
        if pending_shutdown_grace_s > 3600:
            raise ValueError("'pending_control_command.shutdown_grace_s' must be <= 3600")
        alerts_muted_until_raw = pending_raw.get("alerts_muted_until")
        if alerts_muted_until_raw is None:
            alerts_muted_until = None
        elif isinstance(alerts_muted_until_raw, str):
            alerts_muted_until = alerts_muted_until_raw.strip() or None
        else:
            raise ValueError("'pending_control_command.alerts_muted_until' must be a string or null")
        alerts_muted_reason_raw = pending_raw.get("alerts_muted_reason")
        if alerts_muted_reason_raw is None:
            alerts_muted_reason = None
        elif isinstance(alerts_muted_reason_raw, str):
            alerts_muted_reason = alerts_muted_reason_raw.strip() or None
        else:
            raise ValueError("'pending_control_command.alerts_muted_reason' must be a string or null")

        pending_control_command = PendingControlCommand(
            id=pending_id,
            issued_at=issued_at,
            expires_at=expires_at,
            operation_mode=pending_operation_mode,
            sleep_poll_interval_s=pending_sleep_poll_interval_s,
            shutdown_requested=pending_shutdown_requested,
            shutdown_grace_s=pending_shutdown_grace_s,
            alerts_muted_until=alerts_muted_until,
            alerts_muted_reason=alerts_muted_reason,
        )

    return DevicePolicy(
        device_id=str(payload.get("device_id") or ""),
        policy_version=str(payload.get("policy_version") or ""),
        policy_sha256=str(payload.get("policy_sha256") or ""),
        cache_max_age_s=_require_int(payload, "cache_max_age_s"),
        heartbeat_interval_s=_require_int(payload, "heartbeat_interval_s"),
        offline_after_s=_require_int(payload, "offline_after_s"),
        operation_mode=operation_mode,
        sleep_poll_interval_s=sleep_poll_interval_s,
        disable_requires_manual_restart=disable_requires_manual_restart,
        reporting=reporting,
        delta_thresholds=delta,
        alert_thresholds=alerts,
        cost_caps=cost_caps,
        power_management=power_management,
        pending_control_command=pending_control_command,
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
            "operation_mode": policy.operation_mode,
            "sleep_poll_interval_s": policy.sleep_poll_interval_s,
            "disable_requires_manual_restart": policy.disable_requires_manual_restart,
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
                "microphone_offline_db": policy.alert_thresholds.microphone_offline_db,
                "microphone_offline_open_consecutive_samples": (
                    policy.alert_thresholds.microphone_offline_open_consecutive_samples
                ),
                "microphone_offline_resolve_consecutive_samples": (
                    policy.alert_thresholds.microphone_offline_resolve_consecutive_samples
                ),
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
            "cost_caps": {
                "max_bytes_per_day": policy.cost_caps.max_bytes_per_day,
                "max_snapshots_per_day": policy.cost_caps.max_snapshots_per_day,
                "max_media_uploads_per_day": policy.cost_caps.max_media_uploads_per_day,
            },
            "power_management": {
                "enabled": policy.power_management.enabled,
                "mode": policy.power_management.mode,
                "input_warn_min_v": policy.power_management.input_warn_min_v,
                "input_warn_max_v": policy.power_management.input_warn_max_v,
                "input_critical_min_v": policy.power_management.input_critical_min_v,
                "input_critical_max_v": policy.power_management.input_critical_max_v,
                "sustainable_input_w": policy.power_management.sustainable_input_w,
                "unsustainable_window_s": policy.power_management.unsustainable_window_s,
                "battery_trend_window_s": policy.power_management.battery_trend_window_s,
                "battery_drop_warn_v": policy.power_management.battery_drop_warn_v,
                "saver_sample_interval_s": policy.power_management.saver_sample_interval_s,
                "saver_heartbeat_interval_s": policy.power_management.saver_heartbeat_interval_s,
                "media_disabled_in_saver": policy.power_management.media_disabled_in_saver,
            },
            "pending_control_command": (
                {
                    "id": policy.pending_control_command.id,
                    "issued_at": policy.pending_control_command.issued_at,
                    "expires_at": policy.pending_control_command.expires_at,
                    "operation_mode": policy.pending_control_command.operation_mode,
                    "sleep_poll_interval_s": policy.pending_control_command.sleep_poll_interval_s,
                    "shutdown_requested": policy.pending_control_command.shutdown_requested,
                    "shutdown_grace_s": policy.pending_control_command.shutdown_grace_s,
                    "alerts_muted_until": policy.pending_control_command.alerts_muted_until,
                    "alerts_muted_reason": policy.pending_control_command.alerts_muted_reason,
                }
                if policy.pending_control_command is not None
                else None
            ),
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
