from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import Response as StarletteResponse

from ..config import settings
from ..edge_policy import load_edge_policy
from ..db import db_session
from ..models import Device
from ..schemas import (
    DevicePolicyOut,
    EdgePolicyAlertThresholdsOut,
    EdgePolicyCostCapsOut,
    OperationMode,
    EdgePolicyPowerManagementOut,
    PendingControlCommandOut,
    EdgePolicyReportingOut,
)
from ..security import require_device_auth
from ..services.device_commands import control_command_etag_fragment, get_pending_device_command


router = APIRouter(prefix="/api/v1", tags=["device-policy"])


def _make_etag(*parts: str) -> str:
    joined = ":".join(parts).encode("utf-8")
    digest = hashlib.sha256(joined).hexdigest()
    # Strong ETag; safe because this is a deterministic hash.
    return f'"{digest}"'


def _normalized_operation_mode(value: object) -> OperationMode:
    mode = str(value or "active").strip().lower()
    if mode == "sleep":
        return "sleep"
    if mode == "disabled":
        return "disabled"
    return "active"


def _parse_opt_utc(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _safe_sleep_interval(value: object) -> int:
    if value is None:
        return 7 * 24 * 3600
    if isinstance(value, bool):
        parsed = int(value)
    elif isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        parsed = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return 7 * 24 * 3600
        try:
            parsed = int(text)
        except ValueError:
            return 7 * 24 * 3600
    else:
        return 7 * 24 * 3600
    return max(60, parsed)


def _safe_shutdown_requested(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
    return False


def _safe_shutdown_grace_s(value: object) -> int:
    if isinstance(value, bool):
        parsed = int(value)
    elif isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        parsed = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return 30
        try:
            parsed = int(text)
        except ValueError:
            return 30
    else:
        return 30
    if parsed < 1:
        return 1
    if parsed > 3600:
        return 3600
    return parsed


def _pending_command_out(command) -> PendingControlCommandOut | None:
    if command is None:
        return None
    payload = command.command_payload if isinstance(command.command_payload, dict) else {}
    return PendingControlCommandOut(
        id=command.id,
        issued_at=command.issued_at,
        expires_at=command.expires_at,
        operation_mode=_normalized_operation_mode(payload.get("operation_mode")),
        sleep_poll_interval_s=_safe_sleep_interval(payload.get("sleep_poll_interval_s", 7 * 24 * 3600)),
        shutdown_requested=_safe_shutdown_requested(payload.get("shutdown_requested")),
        shutdown_grace_s=_safe_shutdown_grace_s(payload.get("shutdown_grace_s", 30)),
        alerts_muted_until=_parse_opt_utc(payload.get("alerts_muted_until")),
        alerts_muted_reason=(
            str(payload.get("alerts_muted_reason")).strip() if payload.get("alerts_muted_reason") else None
        ),
    )


@router.get(
    "/device-policy",
    response_model=DevicePolicyOut,
    responses={304: {"description": "Not Modified"}},
)
def get_device_policy(
    request: Request,
    response: Response,
    device: Device = Depends(require_device_auth),
) -> DevicePolicyOut | StarletteResponse:
    """Return the edge policy for the authenticated device.

    Design goals
    - Minimize device data usage via ETag + Cache-Control.
    - Provide a single, auditable place to tune edge behavior.

    Caching semantics
    - Devices should call this endpoint on startup and then periodically.
    - Use If-None-Match to avoid downloading the full payload when unchanged.
    """

    policy = load_edge_policy(settings.edge_policy_version)

    # Optional env override for quick experimentation.
    wp_low = (
        settings.default_water_pressure_low_psi
        if settings.default_water_pressure_low_psi is not None
        else policy.alert_thresholds.water_pressure_low_psi
    )

    batt_low = (
        settings.default_battery_low_v
        if settings.default_battery_low_v is not None
        else policy.alert_thresholds.battery_low_v
    )

    sig_low = (
        settings.default_signal_low_rssi_dbm
        if settings.default_signal_low_rssi_dbm is not None
        else policy.alert_thresholds.signal_low_rssi_dbm
    )
    operation_mode = _normalized_operation_mode(getattr(device, "operation_mode", "active"))
    sleep_poll_interval_s = int(
        getattr(device, "sleep_poll_interval_s", policy.operation_defaults.default_sleep_poll_interval_s)
        or policy.operation_defaults.default_sleep_poll_interval_s
    )
    if sleep_poll_interval_s <= 0:
        sleep_poll_interval_s = policy.operation_defaults.default_sleep_poll_interval_s

    try:
        with db_session() as session:
            command_fragment = control_command_etag_fragment(session, device_id=device.device_id)
            pending_command = get_pending_device_command(session, device_id=device.device_id)
    except Exception:
        command_fragment = "none"
        pending_command = None

    etag = _make_etag(
        policy.sha256,
        str(device.heartbeat_interval_s),
        str(device.offline_after_s),
        f"operation_mode={operation_mode}",
        f"sleep_poll_interval_s={sleep_poll_interval_s}",
        f"wp_low={wp_low}",
        f"batt_low={batt_low}",
        f"sig_low={sig_low}",
        f"control_command={command_fragment}",
    )

    if request.headers.get("if-none-match") == etag:
        return StarletteResponse(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={
                "ETag": etag,
                "Cache-Control": f"max-age={policy.cache_max_age_s}",
                "Vary": "Authorization",
            },
        )

    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = f"max-age={policy.cache_max_age_s}"
    response.headers["Vary"] = "Authorization"

    return DevicePolicyOut(
        device_id=device.device_id,
        policy_version=policy.version,
        policy_sha256=policy.sha256,
        cache_max_age_s=policy.cache_max_age_s,
        heartbeat_interval_s=device.heartbeat_interval_s,
        offline_after_s=device.offline_after_s,
        operation_mode=operation_mode,
        sleep_poll_interval_s=sleep_poll_interval_s,
        disable_requires_manual_restart=policy.operation_defaults.disable_requires_manual_restart,
        reporting=EdgePolicyReportingOut(
            sample_interval_s=policy.reporting.sample_interval_s,
            alert_sample_interval_s=policy.reporting.alert_sample_interval_s,
            heartbeat_interval_s=device.heartbeat_interval_s,
            alert_report_interval_s=policy.reporting.alert_report_interval_s,
            max_points_per_batch=policy.reporting.max_points_per_batch,
            buffer_max_points=policy.reporting.buffer_max_points,
            buffer_max_age_s=policy.reporting.buffer_max_age_s,
            backoff_initial_s=policy.reporting.backoff_initial_s,
            backoff_max_s=policy.reporting.backoff_max_s,
        ),
        delta_thresholds=policy.delta_thresholds,
        alert_thresholds=EdgePolicyAlertThresholdsOut(
            microphone_offline_db=policy.alert_thresholds.microphone_offline_db,
            microphone_offline_open_consecutive_samples=(
                policy.alert_thresholds.microphone_offline_open_consecutive_samples
            ),
            microphone_offline_resolve_consecutive_samples=(
                policy.alert_thresholds.microphone_offline_resolve_consecutive_samples
            ),
            water_pressure_low_psi=wp_low,
            water_pressure_recover_psi=policy.alert_thresholds.water_pressure_recover_psi,
            oil_pressure_low_psi=policy.alert_thresholds.oil_pressure_low_psi,
            oil_pressure_recover_psi=policy.alert_thresholds.oil_pressure_recover_psi,
            oil_level_low_pct=policy.alert_thresholds.oil_level_low_pct,
            oil_level_recover_pct=policy.alert_thresholds.oil_level_recover_pct,
            drip_oil_level_low_pct=policy.alert_thresholds.drip_oil_level_low_pct,
            drip_oil_level_recover_pct=policy.alert_thresholds.drip_oil_level_recover_pct,
            oil_life_low_pct=policy.alert_thresholds.oil_life_low_pct,
            oil_life_recover_pct=policy.alert_thresholds.oil_life_recover_pct,
            battery_low_v=batt_low,
            battery_recover_v=policy.alert_thresholds.battery_recover_v,
            signal_low_rssi_dbm=sig_low,
            signal_recover_rssi_dbm=policy.alert_thresholds.signal_recover_rssi_dbm,
        ),
        cost_caps=EdgePolicyCostCapsOut(
            max_bytes_per_day=policy.cost_caps.max_bytes_per_day,
            max_snapshots_per_day=policy.cost_caps.max_snapshots_per_day,
            max_media_uploads_per_day=policy.cost_caps.max_media_uploads_per_day,
        ),
        power_management=EdgePolicyPowerManagementOut(
            enabled=policy.power_management.enabled,
            mode=policy.power_management.mode,
            input_warn_min_v=policy.power_management.input_warn_min_v,
            input_warn_max_v=policy.power_management.input_warn_max_v,
            input_critical_min_v=policy.power_management.input_critical_min_v,
            input_critical_max_v=policy.power_management.input_critical_max_v,
            sustainable_input_w=policy.power_management.sustainable_input_w,
            unsustainable_window_s=policy.power_management.unsustainable_window_s,
            battery_trend_window_s=policy.power_management.battery_trend_window_s,
            battery_drop_warn_v=policy.power_management.battery_drop_warn_v,
            saver_sample_interval_s=policy.power_management.saver_sample_interval_s,
            saver_heartbeat_interval_s=policy.power_management.saver_heartbeat_interval_s,
            media_disabled_in_saver=policy.power_management.media_disabled_in_saver,
        ),
        pending_control_command=_pending_command_out(pending_command),
    )
