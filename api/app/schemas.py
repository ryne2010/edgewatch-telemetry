from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AdminDeviceCreate(BaseModel):
    device_id: str = Field(..., min_length=3, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=256)
    # Allow long opaque tokens/JWTs (bcrypt would truncate; we use PBKDF2).
    token: str = Field(..., min_length=8, max_length=2048)
    # Defaults align with contracts/edge_policy/* (battery & data optimized).
    heartbeat_interval_s: int = Field(300, ge=5, le=3600)
    offline_after_s: int = Field(900, ge=10, le=24 * 3600)


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
    batch_id: str
    accepted: int
    duplicates: int


class TelemetryContractMetricOut(BaseModel):
    type: str
    unit: Optional[str] = None
    description: Optional[str] = None


class TelemetryContractOut(BaseModel):
    version: str
    sha256: str
    metrics: Dict[str, TelemetryContractMetricOut]


class IngestionBatchOut(BaseModel):
    id: str
    device_id: str
    received_at: datetime
    contract_version: str
    contract_hash: str
    points_submitted: int
    points_accepted: int
    duplicates: int
    client_ts_min: Optional[datetime]
    client_ts_max: Optional[datetime]
    unknown_metric_keys: List[str]


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


# ---------------------------------------------------------------------------
# Edge policy (device-side optimization)
# ---------------------------------------------------------------------------


class EdgePolicyReportingOut(BaseModel):
    sample_interval_s: int
    alert_sample_interval_s: int
    heartbeat_interval_s: int
    alert_report_interval_s: int

    max_points_per_batch: int
    buffer_max_points: int
    buffer_max_age_s: int

    backoff_initial_s: int
    backoff_max_s: int


class EdgePolicyAlertThresholdsOut(BaseModel):
    water_pressure_low_psi: float
    water_pressure_recover_psi: float

    battery_low_v: float
    battery_recover_v: float

    signal_low_rssi_dbm: float
    signal_recover_rssi_dbm: float


class DevicePolicyOut(BaseModel):
    device_id: str

    policy_version: str
    policy_sha256: str
    cache_max_age_s: int

    heartbeat_interval_s: int
    offline_after_s: int

    reporting: EdgePolicyReportingOut
    delta_thresholds: Dict[str, float]
    alert_thresholds: EdgePolicyAlertThresholdsOut
