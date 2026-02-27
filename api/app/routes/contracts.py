from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import Response as StarletteResponse

from ..config import settings
from ..contracts import load_telemetry_contract
from ..edge_policy import load_edge_policy
from ..schemas import (
    EdgePolicyAlertThresholdsOut,
    EdgePolicyCostCapsOut,
    EdgePolicyContractOut,
    EdgePolicyOperationDefaultsOut,
    EdgePolicyPowerManagementOut,
    EdgePolicyReportingOut,
    TelemetryContractOut,
    TelemetryContractMetricOut,
)

router = APIRouter(prefix="/api/v1", tags=["contracts"])


@router.get(
    "/contracts/telemetry",
    response_model=TelemetryContractOut,
    responses={304: {"description": "Not Modified"}},
)
def get_telemetry_contract(request: Request, response: Response) -> TelemetryContractOut | StarletteResponse:
    """Return the active telemetry contract.

    This is intentionally public (no secrets):
    - helps edge devices validate payloads
    - helps the UI know which metrics exist
    - makes contract changes auditable
    """

    try:
        c = load_telemetry_contract(settings.telemetry_contract_version)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="telemetry contract is not available",
        )

    etag = f'"{c.sha256}"'
    if request.headers.get("if-none-match") == etag:
        return StarletteResponse(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={
                "ETag": etag,
                # Telemetry contracts change rarely; cache aggressively.
                "Cache-Control": "max-age=3600",
            },
        )

    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "max-age=3600"

    return TelemetryContractOut(
        version=c.version,
        sha256=c.sha256,
        metrics={
            k: TelemetryContractMetricOut(type=v.type, unit=v.unit, description=v.description)
            for k, v in sorted(c.metrics.items())
        },
        profiles={k: c.profiles[k] for k in sorted(c.profiles)},
    )


@router.get(
    "/contracts/edge_policy",
    response_model=EdgePolicyContractOut,
    responses={304: {"description": "Not Modified"}},
)
def get_edge_policy_contract(
    request: Request, response: Response
) -> EdgePolicyContractOut | StarletteResponse:
    """Return the active edge policy contract.

    This is intentionally public (no secrets):
    - helps edge devices tune reporting without hardcoding
    - helps the UI display thresholds + data cadence
    - makes policy changes auditable
    """

    try:
        p = load_edge_policy(settings.edge_policy_version)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="edge policy contract is not available",
        )

    etag = f'"{p.sha256}"'
    if request.headers.get("if-none-match") == etag:
        return StarletteResponse(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={
                "ETag": etag,
                "Cache-Control": f"max-age={p.cache_max_age_s}",
            },
        )

    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = f"max-age={p.cache_max_age_s}"

    return EdgePolicyContractOut(
        policy_version=p.version,
        policy_sha256=p.sha256,
        cache_max_age_s=p.cache_max_age_s,
        reporting=EdgePolicyReportingOut(
            sample_interval_s=p.reporting.sample_interval_s,
            alert_sample_interval_s=p.reporting.alert_sample_interval_s,
            heartbeat_interval_s=p.reporting.heartbeat_interval_s,
            alert_report_interval_s=p.reporting.alert_report_interval_s,
            max_points_per_batch=p.reporting.max_points_per_batch,
            buffer_max_points=p.reporting.buffer_max_points,
            buffer_max_age_s=p.reporting.buffer_max_age_s,
            backoff_initial_s=p.reporting.backoff_initial_s,
            backoff_max_s=p.reporting.backoff_max_s,
        ),
        delta_thresholds={k: p.delta_thresholds[k] for k in sorted(p.delta_thresholds)},
        alert_thresholds=EdgePolicyAlertThresholdsOut(
            microphone_offline_db=p.alert_thresholds.microphone_offline_db,
            microphone_offline_open_consecutive_samples=(
                p.alert_thresholds.microphone_offline_open_consecutive_samples
            ),
            microphone_offline_resolve_consecutive_samples=(
                p.alert_thresholds.microphone_offline_resolve_consecutive_samples
            ),
            water_pressure_low_psi=p.alert_thresholds.water_pressure_low_psi,
            water_pressure_recover_psi=p.alert_thresholds.water_pressure_recover_psi,
            oil_pressure_low_psi=p.alert_thresholds.oil_pressure_low_psi,
            oil_pressure_recover_psi=p.alert_thresholds.oil_pressure_recover_psi,
            oil_level_low_pct=p.alert_thresholds.oil_level_low_pct,
            oil_level_recover_pct=p.alert_thresholds.oil_level_recover_pct,
            drip_oil_level_low_pct=p.alert_thresholds.drip_oil_level_low_pct,
            drip_oil_level_recover_pct=p.alert_thresholds.drip_oil_level_recover_pct,
            oil_life_low_pct=p.alert_thresholds.oil_life_low_pct,
            oil_life_recover_pct=p.alert_thresholds.oil_life_recover_pct,
            battery_low_v=p.alert_thresholds.battery_low_v,
            battery_recover_v=p.alert_thresholds.battery_recover_v,
            signal_low_rssi_dbm=p.alert_thresholds.signal_low_rssi_dbm,
            signal_recover_rssi_dbm=p.alert_thresholds.signal_recover_rssi_dbm,
        ),
        cost_caps=EdgePolicyCostCapsOut(
            max_bytes_per_day=p.cost_caps.max_bytes_per_day,
            max_snapshots_per_day=p.cost_caps.max_snapshots_per_day,
            max_media_uploads_per_day=p.cost_caps.max_media_uploads_per_day,
        ),
        power_management=EdgePolicyPowerManagementOut(
            enabled=p.power_management.enabled,
            mode=p.power_management.mode,
            input_warn_min_v=p.power_management.input_warn_min_v,
            input_warn_max_v=p.power_management.input_warn_max_v,
            input_critical_min_v=p.power_management.input_critical_min_v,
            input_critical_max_v=p.power_management.input_critical_max_v,
            sustainable_input_w=p.power_management.sustainable_input_w,
            unsustainable_window_s=p.power_management.unsustainable_window_s,
            battery_trend_window_s=p.power_management.battery_trend_window_s,
            battery_drop_warn_v=p.power_management.battery_drop_warn_v,
            saver_sample_interval_s=p.power_management.saver_sample_interval_s,
            saver_heartbeat_interval_s=p.power_management.saver_heartbeat_interval_s,
            media_disabled_in_saver=p.power_management.media_disabled_in_saver,
        ),
        operation_defaults=EdgePolicyOperationDefaultsOut(
            default_sleep_poll_interval_s=p.operation_defaults.default_sleep_poll_interval_s,
            disable_requires_manual_restart=p.operation_defaults.disable_requires_manual_restart,
            admin_remote_shutdown_enabled=p.operation_defaults.admin_remote_shutdown_enabled,
            shutdown_grace_s_default=p.operation_defaults.shutdown_grace_s_default,
            control_command_ttl_s=p.operation_defaults.control_command_ttl_s,
        ),
    )
