from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from ..db import db_session
from ..models import Device
from ..schemas import AdminDeviceCreate, AdminDeviceUpdate, DeviceOut
from ..security import require_admin, hash_token, token_fingerprint
from ..services.monitor import compute_status
from datetime import datetime, timezone

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.post("/devices", dependencies=[Depends(require_admin)], response_model=DeviceOut)
def create_device(req: AdminDeviceCreate) -> DeviceOut:
    with db_session() as session:
        existing = session.query(Device).filter(Device.device_id == req.device_id).one_or_none()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device already exists")

        d = Device(
            device_id=req.device_id,
            display_name=req.display_name,
            token_hash=hash_token(req.token),
            token_fingerprint=token_fingerprint(req.token),
            heartbeat_interval_s=req.heartbeat_interval_s,
            offline_after_s=req.offline_after_s,
            enabled=True,
        )
        session.add(d)

        now = datetime.now(timezone.utc)
        status_str, seconds = compute_status(d, now)
        return DeviceOut(
            device_id=d.device_id,
            display_name=d.display_name,
            heartbeat_interval_s=d.heartbeat_interval_s,
            offline_after_s=d.offline_after_s,
            last_seen_at=d.last_seen_at,
            enabled=d.enabled,
            status=status_str,
            seconds_since_last_seen=seconds,
        )


@router.patch("/devices/{device_id}", dependencies=[Depends(require_admin)], response_model=DeviceOut)
def update_device(device_id: str, req: AdminDeviceUpdate) -> DeviceOut:
    with db_session() as session:
        d = session.query(Device).filter(Device.device_id == device_id).one_or_none()
        if not d:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

        if req.display_name is not None:
            d.display_name = req.display_name
        if req.heartbeat_interval_s is not None:
            d.heartbeat_interval_s = req.heartbeat_interval_s
        if req.offline_after_s is not None:
            d.offline_after_s = req.offline_after_s
        if req.enabled is not None:
            d.enabled = req.enabled

        now = datetime.now(timezone.utc)
        status_str, seconds = compute_status(d, now)
        return DeviceOut(
            device_id=d.device_id,
            display_name=d.display_name,
            heartbeat_interval_s=d.heartbeat_interval_s,
            offline_after_s=d.offline_after_s,
            last_seen_at=d.last_seen_at,
            enabled=d.enabled,
            status=status_str,
            seconds_since_last_seen=seconds,
        )


@router.get("/devices", dependencies=[Depends(require_admin)], response_model=List[DeviceOut])
def list_devices_admin() -> List[DeviceOut]:
    now = datetime.now(timezone.utc)
    with db_session() as session:
        devices = session.query(Device).order_by(Device.device_id.asc()).all()
        out: List[DeviceOut] = []
        for d in devices:
            status_str, seconds = compute_status(d, now)
            out.append(
                DeviceOut(
                    device_id=d.device_id,
                    display_name=d.display_name,
                    heartbeat_interval_s=d.heartbeat_interval_s,
                    offline_after_s=d.offline_after_s,
                    last_seen_at=d.last_seen_at,
                    enabled=d.enabled,
                    status=status_str,
                    seconds_since_last_seen=seconds,
                )
            )
        return out
