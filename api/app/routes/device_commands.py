from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..db import db_session
from ..models import Device
from ..schemas import DeviceCommandAckOut
from ..security import require_device_auth
from ..services.device_commands import ack_device_command


router = APIRouter(prefix="/api/v1", tags=["device-commands"])


@router.post("/device-commands/{command_id}/ack", response_model=DeviceCommandAckOut)
def ack_command(
    command_id: str,
    device: Device = Depends(require_device_auth),
) -> DeviceCommandAckOut:
    with db_session() as session:
        row = ack_device_command(
            session,
            device_id=device.device_id,
            command_id=command_id,
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Command not found")
        return DeviceCommandAckOut(
            id=row.id,
            device_id=row.device_id,
            status=row.status,
            acknowledged_at=row.acknowledged_at,
        )
