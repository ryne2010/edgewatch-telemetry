from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import Response as StarletteResponse

from ..config import settings
from ..contracts import load_telemetry_contract
from ..edge_policy import load_edge_policy
from ..schemas import (
    EdgePolicyAlertThresholdsOut,
    EdgePolicyContractOut,
    EdgePolicyReportingOut,
    TelemetryContractOut,
    TelemetryContractMetricOut,
)

router = APIRouter(prefix="/api/v1", tags=["contracts"])


@router.get("/contracts/telemetry", response_model=TelemetryContractOut, responses={304: {"description": "Not Modified"}})
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
                "Cache-Control": 'max-age=3600',
            },
        )

    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = 'max-age=3600'

    return TelemetryContractOut(
        version=c.version,
        sha256=c.sha256,
        metrics={
            k: TelemetryContractMetricOut(type=v.type, unit=v.unit, description=v.description)
            for k, v in sorted(c.metrics.items())
        },
    )


@router.get("/contracts/edge_policy", response_model=EdgePolicyContractOut, responses={304: {"description": "Not Modified"}})
def get_edge_policy_contract(request: Request, response: Response) -> EdgePolicyContractOut | StarletteResponse:
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
                "Cache-Control": f'max-age={p.cache_max_age_s}',
            },
        )

    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = f'max-age={p.cache_max_age_s}'

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
    )

