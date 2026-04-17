from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import cast

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import Response as StarletteResponse
from sqlalchemy.orm import joinedload

from ..config import settings
from ..edge_policy import load_edge_policy
from ..db import db_session
from ..models import Device, DeviceProcedureInvocation
from ..schemas import (
    ArtifactSignatureScheme,
    DeepSleepBackend,
    DevicePolicyOut,
    EdgePolicyAlertThresholdsOut,
    EdgePolicyCostCapsOut,
    OperationMode,
    EdgePolicyPowerManagementOut,
    PendingProcedureInvocationOut,
    PendingUpdateCommandOut,
    PendingControlCommandOut,
    EdgePolicyReportingOut,
    RuntimePowerMode,
    UpdateType,
)
from ..security import require_device_auth
from ..services.device_commands import control_command_etag_fragment, get_pending_device_command
from ..services.device_procedures import get_pending_invocation, pending_invocation_etag_fragment
from ..services.device_updates import get_pending_update_command, update_command_etag_fragment


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


def _normalized_runtime_power_mode(value: object) -> RuntimePowerMode:
    mode = str(value or "continuous").strip().lower()
    if mode == "eco":
        return "eco"
    if mode == "deep_sleep":
        return "deep_sleep"
    return "continuous"


def _normalized_deep_sleep_backend(value: object) -> DeepSleepBackend:
    backend = str(value or "auto").strip().lower()
    if backend == "pi5_rtc":
        return "pi5_rtc"
    if backend == "external_supervisor":
        return "external_supervisor"
    if backend == "none":
        return "none"
    return "auto"


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


def _safe_health_timeout_s(value: object) -> int:
    if isinstance(value, bool):
        parsed = int(value)
    elif isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        parsed = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return 300
        try:
            parsed = int(text)
        except ValueError:
            return 300
    else:
        return 300
    if parsed < 10:
        return 10
    if parsed > 24 * 3600:
        return 24 * 3600
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
        runtime_power_mode=_normalized_runtime_power_mode(payload.get("runtime_power_mode")),
        deep_sleep_backend=_normalized_deep_sleep_backend(payload.get("deep_sleep_backend")),
        shutdown_requested=_safe_shutdown_requested(payload.get("shutdown_requested")),
        shutdown_grace_s=_safe_shutdown_grace_s(payload.get("shutdown_grace_s", 30)),
        alerts_muted_until=_parse_opt_utc(payload.get("alerts_muted_until")),
        alerts_muted_reason=(
            str(payload.get("alerts_muted_reason")).strip() if payload.get("alerts_muted_reason") else None
        ),
    )


def _pending_update_command_out(command: dict[str, object] | None) -> PendingUpdateCommandOut | None:
    if not isinstance(command, dict):
        return None
    issued_at = command.get("issued_at")
    expires_at = command.get("expires_at")
    if not isinstance(issued_at, datetime) or not isinstance(expires_at, datetime):
        return None
    rollback_raw = command.get("rollback_to_tag")
    rollback_to_tag = rollback_raw.strip() if isinstance(rollback_raw, str) and rollback_raw.strip() else None
    artifact_size_raw = command.get("artifact_size")
    artifact_size = int(artifact_size_raw) if isinstance(artifact_size_raw, (int, float, str)) else 1
    return PendingUpdateCommandOut(
        deployment_id=str(command.get("deployment_id") or ""),
        manifest_id=str(command.get("manifest_id") or ""),
        git_tag=str(command.get("git_tag") or ""),
        commit_sha=str(command.get("commit_sha") or ""),
        update_type=cast(UpdateType, str(command.get("update_type") or "application_bundle")),
        artifact_uri=str(command.get("artifact_uri") or ""),
        artifact_size=max(1, artifact_size),
        artifact_sha256=str(command.get("artifact_sha256") or ""),
        artifact_signature=str(command.get("artifact_signature") or ""),
        artifact_signature_scheme=cast(
            ArtifactSignatureScheme, str(command.get("artifact_signature_scheme") or "none")
        ),
        compatibility=(
            dict(cast(dict[str, object], command.get("compatibility")))
            if isinstance(command.get("compatibility"), dict)
            else {}
        ),
        issued_at=issued_at,
        expires_at=expires_at,
        signature=str(command.get("signature") or ""),
        signature_key_id=str(command.get("signature_key_id") or ""),
        rollback_to_tag=rollback_to_tag,
        health_timeout_s=_safe_health_timeout_s(command.get("health_timeout_s")),
        power_guard_required=bool(command.get("power_guard_required", True)),
    )


def _pending_procedure_invocation_out(command) -> PendingProcedureInvocationOut | None:
    if command is None:
        return None
    definition = getattr(command, "definition", None)
    if definition is None:
        return None
    return PendingProcedureInvocationOut(
        id=command.id,
        definition_id=command.definition_id,
        definition_name=definition.name,
        request_payload=dict(command.request_payload or {}),
        issued_at=command.issued_at,
        expires_at=command.expires_at,
        timeout_s=int(definition.timeout_s),
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
    runtime_power_mode = _normalized_runtime_power_mode(
        getattr(device, "runtime_power_mode", policy.operation_defaults.default_runtime_power_mode)
    )
    deep_sleep_backend = _normalized_deep_sleep_backend(
        getattr(device, "deep_sleep_backend", policy.operation_defaults.default_deep_sleep_backend)
    )
    if sleep_poll_interval_s <= 0:
        sleep_poll_interval_s = policy.operation_defaults.default_sleep_poll_interval_s

    try:
        with db_session() as session:
            command_fragment = control_command_etag_fragment(session, device_id=device.device_id)
            procedure_fragment = pending_invocation_etag_fragment(session, device_id=device.device_id)
            update_fragment = update_command_etag_fragment(session, device_id=device.device_id)
            pending_command = get_pending_device_command(session, device_id=device.device_id)
            pending_procedure = get_pending_invocation(session, device_id=device.device_id)
            if pending_procedure is not None:
                pending_procedure = (
                    session.query(DeviceProcedureInvocation)
                    .options(joinedload(DeviceProcedureInvocation.definition))
                    .filter(DeviceProcedureInvocation.id == pending_procedure.id)
                    .one_or_none()
                )
            pending_update_command = get_pending_update_command(session, device_id=device.device_id)
    except Exception:
        command_fragment = "none"
        procedure_fragment = "none"
        update_fragment = "none"
        pending_command = None
        pending_procedure = None
        pending_update_command = None

    etag = _make_etag(
        policy.sha256,
        str(device.heartbeat_interval_s),
        str(device.offline_after_s),
        f"operation_mode={operation_mode}",
        f"sleep_poll_interval_s={sleep_poll_interval_s}",
        f"runtime_power_mode={runtime_power_mode}",
        f"deep_sleep_backend={deep_sleep_backend}",
        f"wp_low={wp_low}",
        f"batt_low={batt_low}",
        f"sig_low={sig_low}",
        f"control_command={command_fragment}",
        f"procedure={procedure_fragment}",
        f"update_command={update_fragment}",
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
        runtime_power_mode=runtime_power_mode,
        deep_sleep_backend=deep_sleep_backend,
        disable_requires_manual_restart=policy.operation_defaults.disable_requires_manual_restart,
        updates_enabled=bool(getattr(device, "ota_updates_enabled", True)),
        updates_pending=pending_update_command is not None,
        busy_reason=getattr(device, "ota_busy_reason", None),
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
        pending_procedure_invocation=_pending_procedure_invocation_out(pending_procedure),
        pending_update_command=_pending_update_command_out(pending_update_command),
    )
