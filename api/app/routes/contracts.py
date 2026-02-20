from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ..config import settings
from ..contracts import load_telemetry_contract
from ..schemas import TelemetryContractOut, TelemetryContractMetricOut

router = APIRouter(prefix="/api/v1", tags=["contracts"])


@router.get("/contracts/telemetry", response_model=TelemetryContractOut)
def get_telemetry_contract() -> TelemetryContractOut:
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

    return TelemetryContractOut(
        version=c.version,
        sha256=c.sha256,
        metrics={
            k: TelemetryContractMetricOut(type=v.type, unit=v.unit, description=v.description)
            for k, v in sorted(c.metrics.items())
        },
    )
