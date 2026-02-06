from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AdminDeviceCreate(BaseModel):
    device_id: str = Field(..., min_length=3, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=256)
    token: str = Field(..., min_length=8, max_length=256)
    heartbeat_interval_s: int = Field(60, ge=5, le=3600)
    offline_after_s: int = Field(300, ge=10, le=24 * 3600)


class AdminDeviceUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=256)
    heartbeat_interval_s: Optional[int] = Field(None, ge=5, le=3600)
    offline_after_s: Optional[int] = Field(None, ge=10, le=24 * 3600)
    enabled: Optional[bool] = None


class DeviceOut(BaseModel):
    device_id: str
    display_name: str
    heartbeat_interval_s: int
    offline_after_s: int
    last_seen_at: Optional[datetime]
    enabled: bool

    status: str
    seconds_since_last_seen: Optional[int]


class TelemetryPointIn(BaseModel):
    message_id: str = Field(..., min_length=8, max_length=64)
    ts: datetime
    metrics: Dict[str, Any] = Field(default_factory=dict)


class IngestRequest(BaseModel):
    points: List[TelemetryPointIn] = Field(..., min_length=1, max_length=500)


class IngestResponse(BaseModel):
    device_id: str
    accepted: int
    duplicates: int


class AlertOut(BaseModel):
    id: str
    device_id: str
    alert_type: str
    severity: str
    message: str
    created_at: datetime
    resolved_at: Optional[datetime]


class TimeseriesPointOut(BaseModel):
    bucket_ts: datetime
    value: float


class TimeseriesMultiPointOut(BaseModel):
    bucket_ts: datetime
    values: Dict[str, Optional[float]]
