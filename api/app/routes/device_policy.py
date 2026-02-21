from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import Response as StarletteResponse

from ..config import settings
from ..edge_policy import load_edge_policy
from ..models import Device
from ..schemas import DevicePolicyOut, EdgePolicyAlertThresholdsOut, EdgePolicyReportingOut
from ..security import require_device_auth


router = APIRouter(prefix="/api/v1", tags=["device-policy"])


def _make_etag(*parts: str) -> str:
    joined = ":".join(parts).encode("utf-8")
    digest = hashlib.sha256(joined).hexdigest()
    # Strong ETag; safe because this is a deterministic hash.
    return f'"{digest}"'


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

    etag = _make_etag(
        policy.sha256,
        str(device.heartbeat_interval_s),
        str(device.offline_after_s),
        f"wp_low={wp_low}",
        f"batt_low={batt_low}",
        f"sig_low={sig_low}",
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
    )
