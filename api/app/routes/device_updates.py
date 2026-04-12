from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..db import db_session
from ..models import Device
from ..schemas import DeviceUpdateReportIn, DeviceUpdateReportOut
from ..security import require_device_auth
from ..services.device_updates import report_device_update


router = APIRouter(prefix="/api/v1", tags=["device-updates"])


@router.post("/device-updates/{deployment_id}/report", response_model=DeviceUpdateReportOut)
def report_update_state(
    deployment_id: str,
    req: DeviceUpdateReportIn,
    device: Device = Depends(require_device_auth),
) -> DeviceUpdateReportOut:
    with db_session() as session:
        try:
            deployment, target = report_device_update(
                session,
                deployment_id=deployment_id,
                device_id=device.device_id,
                state=req.state,
                reason_code=req.reason_code,
                reason_detail=req.reason_detail,
            )
        except LookupError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Deployment target not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        return DeviceUpdateReportOut(
            deployment_id=deployment.id,
            device_id=device.device_id,
            status=target.status,
            stage=int(deployment.stage),
            deployment_status=deployment.status,
            updated_at=deployment.updated_at,
        )
