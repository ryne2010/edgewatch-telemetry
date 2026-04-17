from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

UpdateType = Literal["application_bundle", "asset_bundle", "system_image"]
ArtifactSignatureScheme = Literal["none", "openssl_rsa_sha256"]


class AdminDeviceCreate(BaseModel):
    device_id: str = Field(..., min_length=3, max_length=128)
    # Optional on create; server falls back to device_id.
    display_name: Optional[str] = Field(None, min_length=1, max_length=256)
    # Allow long opaque tokens/JWTs (bcrypt would truncate; we use PBKDF2).
    token: str = Field(..., min_length=8, max_length=2048)
    # Defaults align with contracts/edge_policy/* (battery & data optimized).
    heartbeat_interval_s: int = Field(300, ge=5, le=3600)
    offline_after_s: int = Field(900, ge=10, le=24 * 3600)
    owner_emails: Optional[List[str]] = None
    ota_channel: str = Field("stable", min_length=1, max_length=64)
    ota_updates_enabled: bool = True
    ota_busy_reason: Optional[str] = Field(None, min_length=1, max_length=256)
    ota_is_development: bool = False
    ota_locked_manifest_id: Optional[str] = Field(None, min_length=1, max_length=36)


class AdminDeviceUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=256)
    # Optional token rotation.
    token: Optional[str] = Field(None, min_length=8, max_length=2048)
    heartbeat_interval_s: Optional[int] = Field(None, ge=5, le=3600)
    offline_after_s: Optional[int] = Field(None, ge=10, le=24 * 3600)
    enabled: Optional[bool] = None
    ota_channel: Optional[str] = Field(None, min_length=1, max_length=64)
    ota_updates_enabled: Optional[bool] = None
    ota_busy_reason: Optional[str] = Field(None, min_length=1, max_length=256)
    ota_is_development: Optional[bool] = None
    ota_locked_manifest_id: Optional[str] = Field(None, min_length=1, max_length=36)


OperationMode = Literal["active", "sleep", "disabled"]
RuntimePowerMode = Literal["continuous", "eco", "deep_sleep"]
DeepSleepBackend = Literal["auto", "pi5_rtc", "external_supervisor", "none"]
DeviceAccessRole = Literal["viewer", "operator", "owner"]
DeviceStatus = Literal["online", "offline", "unknown", "sleep", "disabled"]


class DeviceOut(BaseModel):
    device_id: str
    display_name: str
    heartbeat_interval_s: int
    offline_after_s: int
    last_seen_at: Optional[datetime]
    enabled: bool
    operation_mode: OperationMode = "active"
    sleep_poll_interval_s: int = 7 * 24 * 3600
    runtime_power_mode: RuntimePowerMode = "continuous"
    deep_sleep_backend: DeepSleepBackend = "auto"
    alerts_muted_until: Optional[datetime] = None
    alerts_muted_reason: Optional[str] = None
    ota_channel: str = "stable"
    ota_updates_enabled: bool = True
    ota_busy_reason: Optional[str] = None
    ota_is_development: bool = False
    ota_locked_manifest_id: Optional[str] = None

    status: DeviceStatus
    seconds_since_last_seen: Optional[int]


class DeviceSummaryOut(BaseModel):
    """Fleet view: device + status + selected latest telemetry metrics.

    This avoids N+1 calls from the UI when rendering fleet dashboards.
    """

    device_id: str
    display_name: str
    heartbeat_interval_s: int
    offline_after_s: int
    last_seen_at: Optional[datetime]
    enabled: bool
    operation_mode: OperationMode = "active"
    sleep_poll_interval_s: int = 7 * 24 * 3600
    runtime_power_mode: RuntimePowerMode = "continuous"
    deep_sleep_backend: DeepSleepBackend = "auto"
    alerts_muted_until: Optional[datetime] = None
    alerts_muted_reason: Optional[str] = None
    ota_channel: str = "stable"
    ota_updates_enabled: bool = True
    ota_busy_reason: Optional[str] = None
    ota_is_development: bool = False
    ota_locked_manifest_id: Optional[str] = None

    status: DeviceStatus
    seconds_since_last_seen: Optional[int]

    latest_telemetry_at: Optional[datetime]
    latest_message_id: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)


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
    quarantined: int = 0


class MediaCreateRequest(BaseModel):
    message_id: str = Field(..., min_length=8, max_length=64)
    camera_id: str = Field(..., min_length=1, max_length=32)
    captured_at: datetime
    reason: Literal["scheduled", "alert_transition", "manual"]
    sha256: str = Field(..., min_length=64, max_length=64)
    bytes: int = Field(..., gt=0)
    mime_type: str = Field(..., min_length=3, max_length=128)


class MediaUploadInstructionOut(BaseModel):
    method: Literal["PUT"]
    url: str
    headers: Dict[str, str] = Field(default_factory=dict)


class MediaObjectOut(BaseModel):
    id: str
    device_id: str
    camera_id: str
    message_id: str
    captured_at: datetime
    reason: str
    sha256: str
    bytes: int
    mime_type: str
    object_path: str
    gcs_uri: Optional[str]
    local_path: Optional[str]
    uploaded_at: Optional[datetime]
    created_at: datetime


class MediaCreateResponse(BaseModel):
    media: MediaObjectOut
    upload: MediaUploadInstructionOut


class TelemetryContractMetricOut(BaseModel):
    type: str
    unit: Optional[str] = None
    description: Optional[str] = None


class TelemetryContractOut(BaseModel):
    version: str
    sha256: str
    metrics: Dict[str, TelemetryContractMetricOut]
    profiles: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class IngestionBatchOut(BaseModel):
    id: str
    device_id: str
    received_at: datetime
    contract_version: str
    contract_hash: str
    points_submitted: int
    points_accepted: int
    duplicates: int
    points_quarantined: int
    client_ts_min: Optional[datetime]
    client_ts_max: Optional[datetime]
    unknown_metric_keys: List[str]
    type_mismatch_keys: List[str]
    drift_summary: Dict[str, Any]
    source: str
    pipeline_mode: str
    processing_status: str


class IngestionBatchPageOut(BaseModel):
    items: List[IngestionBatchOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class DriftEventOut(BaseModel):
    id: str
    batch_id: str
    device_id: str
    event_type: str
    action: str
    details: Dict[str, Any]
    created_at: datetime


class DriftEventPageOut(BaseModel):
    items: List[DriftEventOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class NotificationEventOut(BaseModel):
    id: str
    alert_id: Optional[str]
    device_id: str
    source_kind: str
    source_id: Optional[str] = None
    alert_type: str
    channel: str
    decision: str
    delivered: bool
    reason: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class NotificationEventPageOut(BaseModel):
    items: List[NotificationEventOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class DeviceAccessGrantPutIn(BaseModel):
    access_role: DeviceAccessRole = "viewer"


class DeviceAccessGrantOut(BaseModel):
    device_id: str
    principal_email: str
    access_role: DeviceAccessRole
    created_at: datetime
    updated_at: datetime


class FleetCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = Field(None, max_length=1024)
    default_ota_channel: str = Field("stable", min_length=1, max_length=64)


class FleetUpdateIn(BaseModel):
    description: Optional[str] = Field(None, max_length=1024)
    default_ota_channel: Optional[str] = Field(None, min_length=1, max_length=64)


class FleetOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    default_ota_channel: str
    created_at: datetime
    updated_at: datetime
    device_count: int = 0


class FleetMembershipOut(BaseModel):
    fleet_id: str
    device_id: str
    added_at: datetime


class FleetAccessGrantPutIn(BaseModel):
    access_role: DeviceAccessRole = "viewer"


class FleetAccessGrantOut(BaseModel):
    fleet_id: str
    principal_email: str
    access_role: DeviceAccessRole
    created_at: datetime
    updated_at: datetime


class DeviceControlsOut(BaseModel):
    device_id: str
    operation_mode: OperationMode
    sleep_poll_interval_s: int
    runtime_power_mode: RuntimePowerMode = "continuous"
    deep_sleep_backend: DeepSleepBackend = "auto"
    disable_requires_manual_restart: bool = True
    alerts_muted_until: Optional[datetime] = None
    alerts_muted_reason: Optional[str] = None
    pending_command_count: int = 0
    latest_pending_command_expires_at: Optional[datetime] = None
    latest_pending_operation_mode: Optional[OperationMode] = None
    latest_pending_shutdown_requested: bool = False
    latest_pending_shutdown_grace_s: Optional[int] = None


ProcedureInvocationStatus = Literal["queued", "in_progress", "succeeded", "failed", "expired", "superseded"]
EventSeverity = Literal["info", "warning", "error"]


class DeviceProcedureDefinitionCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = Field(None, max_length=1024)
    request_schema: Dict[str, Any] = Field(default_factory=dict)
    response_schema: Dict[str, Any] = Field(default_factory=dict)
    timeout_s: int = Field(300, ge=1, le=24 * 3600)
    enabled: bool = True


class DeviceProcedureDefinitionUpdateIn(BaseModel):
    description: Optional[str] = Field(None, max_length=1024)
    request_schema: Optional[Dict[str, Any]] = None
    response_schema: Optional[Dict[str, Any]] = None
    timeout_s: Optional[int] = Field(None, ge=1, le=24 * 3600)
    enabled: Optional[bool] = None


class DeviceProcedureDefinitionOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    request_schema: Dict[str, Any] = Field(default_factory=dict)
    response_schema: Dict[str, Any] = Field(default_factory=dict)
    timeout_s: int
    enabled: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class DeviceProcedureInvokeIn(BaseModel):
    request_payload: Dict[str, Any] = Field(default_factory=dict)
    ttl_s: int = Field(300, ge=1, le=24 * 3600)


class DeviceProcedureResultIn(BaseModel):
    status: Literal["succeeded", "failed"]
    result_payload: Optional[Dict[str, Any]] = None
    reason_code: Optional[str] = Field(None, min_length=1, max_length=128)
    reason_detail: Optional[str] = Field(None, min_length=1, max_length=1024)


class DeviceProcedureInvocationOut(BaseModel):
    id: str
    device_id: str
    definition_id: str
    definition_name: str
    request_payload: Dict[str, Any] = Field(default_factory=dict)
    result_payload: Optional[Dict[str, Any]] = None
    status: ProcedureInvocationStatus
    reason_code: Optional[str] = None
    reason_detail: Optional[str] = None
    requester_email: str
    issued_at: datetime
    expires_at: datetime
    acknowledged_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    superseded_at: Optional[datetime] = None


class PendingProcedureInvocationOut(BaseModel):
    id: str
    definition_id: str
    definition_name: str
    request_payload: Dict[str, Any] = Field(default_factory=dict)
    issued_at: datetime
    expires_at: datetime
    timeout_s: int


class DeviceReportedStateIn(BaseModel):
    state: Dict[str, Any] = Field(default_factory=dict)
    schema_types: Dict[str, str] = Field(default_factory=dict)


class DeviceReportedStateItemOut(BaseModel):
    key: str
    value_json: Any
    schema_type: Optional[str] = None
    updated_at: datetime


class DeviceEventIn(BaseModel):
    event_type: str = Field(..., min_length=1, max_length=128)
    severity: EventSeverity = "info"
    body: Dict[str, Any] = Field(default_factory=dict)
    source: str = Field("device", min_length=1, max_length=32)


class DeviceEventOut(BaseModel):
    id: str
    device_id: str
    event_type: str
    severity: str
    source: str
    body: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


OperatorSearchEntity = Literal[
    "device",
    "fleet",
    "alert",
    "ingestion_batch",
    "drift_event",
    "device_event",
    "procedure_definition",
    "procedure_invocation",
    "deployment",
    "release_manifest",
    "admin_event",
    "notification_event",
    "notification_destination",
    "export_batch",
]
OperatorEventSource = Literal[
    "alert",
    "notification_event",
    "device_event",
    "procedure_invocation",
    "deployment_event",
    "release_manifest_event",
    "admin_event",
]


class OperatorSearchResultOut(BaseModel):
    entity_type: OperatorSearchEntity
    entity_id: str
    title: str
    subtitle: Optional[str] = None
    device_id: Optional[str] = None
    created_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OperatorSearchPageOut(BaseModel):
    items: List[OperatorSearchResultOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class OperatorEventOut(BaseModel):
    source_kind: OperatorEventSource
    entity_id: str
    device_id: Optional[str] = None
    event_name: str
    severity: str
    created_at: datetime
    payload: Dict[str, Any] = Field(default_factory=dict)


class OperatorEventPageOut(BaseModel):
    items: List[OperatorEventOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class DeviceOperationControlUpdateIn(BaseModel):
    operation_mode: OperationMode
    sleep_poll_interval_s: Optional[int] = Field(None, ge=60, le=60 * 60 * 24 * 30)
    runtime_power_mode: Optional[RuntimePowerMode] = None
    deep_sleep_backend: Optional[DeepSleepBackend] = None


class DeviceAlertsControlUpdateIn(BaseModel):
    alerts_muted_until: Optional[datetime] = None
    alerts_muted_reason: Optional[str] = Field(None, max_length=512)


class AdminDeviceShutdownIn(BaseModel):
    reason: str = Field(..., min_length=3, max_length=512)
    shutdown_grace_s: Optional[int] = Field(None, ge=1, le=3600)


class NotificationDestinationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    channel: Literal["webhook"] = "webhook"
    kind: Literal["generic", "slack", "discord", "telegram"] = "generic"
    webhook_url: str = Field(..., min_length=8, max_length=2048)
    source_types: List[str] = Field(default_factory=lambda: ["alert"])
    event_types: List[str] = Field(default_factory=list)
    enabled: bool = True


class NotificationDestinationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    channel: Optional[Literal["webhook"]] = None
    kind: Optional[Literal["generic", "slack", "discord", "telegram"]] = None
    webhook_url: Optional[str] = Field(None, min_length=8, max_length=2048)
    source_types: Optional[List[str]] = None
    event_types: Optional[List[str]] = None
    enabled: Optional[bool] = None


class NotificationDestinationOut(BaseModel):
    id: str
    name: str
    channel: str
    kind: str
    source_types: List[str] = Field(default_factory=list)
    event_types: List[str] = Field(default_factory=list)
    enabled: bool
    webhook_url_masked: str
    destination_fingerprint: str
    created_at: datetime
    updated_at: datetime


class AdminEventOut(BaseModel):
    id: str
    actor_email: str
    actor_subject: Optional[str]
    action: str
    target_type: str
    target_device_id: Optional[str]
    details: Dict[str, Any]
    request_id: Optional[str]
    created_at: datetime


class AdminEventPageOut(BaseModel):
    items: List[AdminEventOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class ExportBatchOut(BaseModel):
    id: str
    started_at: datetime
    finished_at: Optional[datetime]
    watermark_from: Optional[datetime]
    watermark_to: Optional[datetime]
    contract_version: str
    contract_hash: str
    gcs_uri: Optional[str]
    row_count: int
    status: str
    error_message: Optional[str]


class ExportBatchPageOut(BaseModel):
    items: List[ExportBatchOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


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
    microphone_offline_db: float
    microphone_offline_open_consecutive_samples: int = 2
    microphone_offline_resolve_consecutive_samples: int = 1

    water_pressure_low_psi: float
    water_pressure_recover_psi: float

    oil_pressure_low_psi: float
    oil_pressure_recover_psi: float

    oil_level_low_pct: float
    oil_level_recover_pct: float

    drip_oil_level_low_pct: float
    drip_oil_level_recover_pct: float

    oil_life_low_pct: float
    oil_life_recover_pct: float

    battery_low_v: float
    battery_recover_v: float

    signal_low_rssi_dbm: float
    signal_recover_rssi_dbm: float


class EdgePolicyCostCapsOut(BaseModel):
    max_bytes_per_day: int
    max_snapshots_per_day: int
    max_media_uploads_per_day: int


class EdgePolicyPowerManagementOut(BaseModel):
    enabled: bool
    mode: str
    input_warn_min_v: float
    input_warn_max_v: float
    input_critical_min_v: float
    input_critical_max_v: float
    sustainable_input_w: float
    unsustainable_window_s: int
    battery_trend_window_s: int
    battery_drop_warn_v: float
    saver_sample_interval_s: int
    saver_heartbeat_interval_s: int
    media_disabled_in_saver: bool


class EdgePolicyOperationDefaultsOut(BaseModel):
    default_sleep_poll_interval_s: int
    default_runtime_power_mode: RuntimePowerMode = "continuous"
    default_deep_sleep_backend: DeepSleepBackend = "auto"
    disable_requires_manual_restart: bool
    admin_remote_shutdown_enabled: bool = True
    shutdown_grace_s_default: int = 30
    control_command_ttl_s: int = 180 * 24 * 3600


class EdgePolicyContractOut(BaseModel):
    """Public edge policy contract (device-side optimization).

    This is intentionally public (no secrets):
    - helps the UI show thresholds
    - makes policy changes auditable
    - helps edge devices validate expectations
    """

    policy_version: str
    policy_sha256: str
    cache_max_age_s: int

    reporting: EdgePolicyReportingOut
    delta_thresholds: Dict[str, float]
    alert_thresholds: EdgePolicyAlertThresholdsOut
    cost_caps: EdgePolicyCostCapsOut
    power_management: EdgePolicyPowerManagementOut
    operation_defaults: EdgePolicyOperationDefaultsOut


class EdgePolicyContractSourceOut(BaseModel):
    policy_version: str
    yaml_text: str


class EdgePolicyContractUpdateIn(BaseModel):
    yaml_text: str = Field(..., min_length=1, max_length=200_000)


class PendingControlCommandOut(BaseModel):
    id: str
    issued_at: datetime
    expires_at: datetime
    operation_mode: OperationMode
    sleep_poll_interval_s: int
    runtime_power_mode: RuntimePowerMode = "continuous"
    deep_sleep_backend: DeepSleepBackend = "auto"
    shutdown_requested: bool = False
    shutdown_grace_s: int = 30
    alerts_muted_until: Optional[datetime] = None
    alerts_muted_reason: Optional[str] = None


class PendingUpdateCommandOut(BaseModel):
    deployment_id: str
    manifest_id: str
    git_tag: str
    commit_sha: str
    update_type: UpdateType
    artifact_uri: str
    artifact_size: int
    artifact_sha256: str
    artifact_signature: str
    artifact_signature_scheme: ArtifactSignatureScheme
    compatibility: Dict[str, Any] = Field(default_factory=dict)
    issued_at: datetime
    expires_at: datetime
    signature: str
    signature_key_id: str
    rollback_to_tag: Optional[str] = None
    health_timeout_s: int
    power_guard_required: bool


class DeviceCommandAckOut(BaseModel):
    id: str
    device_id: str
    status: str
    acknowledged_at: Optional[datetime] = None


class DevicePolicyOut(BaseModel):
    device_id: str

    policy_version: str
    policy_sha256: str
    cache_max_age_s: int

    heartbeat_interval_s: int
    offline_after_s: int
    operation_mode: OperationMode = "active"
    sleep_poll_interval_s: int = 7 * 24 * 3600
    runtime_power_mode: RuntimePowerMode = "continuous"
    deep_sleep_backend: DeepSleepBackend = "auto"
    disable_requires_manual_restart: bool = True
    updates_enabled: bool = True
    updates_pending: bool = False
    busy_reason: Optional[str] = None

    reporting: EdgePolicyReportingOut
    delta_thresholds: Dict[str, float]
    alert_thresholds: EdgePolicyAlertThresholdsOut
    cost_caps: EdgePolicyCostCapsOut
    power_management: EdgePolicyPowerManagementOut
    pending_control_command: Optional[PendingControlCommandOut] = None
    pending_procedure_invocation: Optional[PendingProcedureInvocationOut] = None
    pending_update_command: Optional[PendingUpdateCommandOut] = None


class ReleaseManifestCreateIn(BaseModel):
    git_tag: str = Field(..., min_length=1, max_length=128)
    commit_sha: str = Field(..., min_length=7, max_length=64)
    update_type: UpdateType = "application_bundle"
    artifact_uri: str = Field(..., min_length=1, max_length=2048)
    artifact_size: int = Field(..., gt=0)
    artifact_sha256: str = Field(..., min_length=64, max_length=64)
    artifact_signature: str = Field("", max_length=8192)
    artifact_signature_scheme: ArtifactSignatureScheme = "none"
    compatibility: Dict[str, Any] = Field(default_factory=dict)
    signature: str = Field(..., min_length=1, max_length=8192)
    signature_key_id: str = Field(..., min_length=1, max_length=64)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    status: str = Field("active", min_length=1, max_length=32)


class ReleaseManifestUpdateIn(BaseModel):
    status: Optional[str] = Field(None, min_length=1, max_length=32)


class ReleaseManifestOut(BaseModel):
    id: str
    git_tag: str
    commit_sha: str
    update_type: UpdateType
    artifact_uri: str
    artifact_size: int
    artifact_sha256: str
    artifact_signature: str
    artifact_signature_scheme: ArtifactSignatureScheme
    compatibility: Dict[str, Any] = Field(default_factory=dict)
    signature: str
    signature_key_id: str
    constraints: Dict[str, Any] = Field(default_factory=dict)
    created_by: str
    created_at: datetime
    status: str


class DeploymentTargetSelectorIn(BaseModel):
    mode: Literal["all", "cohort", "labels", "explicit_ids", "channel"] = "all"
    cohort: Optional[str] = Field(None, min_length=1, max_length=128)
    channel: Optional[str] = Field(None, min_length=1, max_length=64)
    labels: Dict[str, str] = Field(default_factory=dict)
    device_ids: List[str] = Field(default_factory=list, max_length=5000)


class DeploymentCreateIn(BaseModel):
    manifest_id: str = Field(..., min_length=1, max_length=36)
    target_selector: Dict[str, Any] = Field(default_factory=lambda: {"mode": "all"})
    rollout_stages_pct: List[int] = Field(
        default_factory=lambda: [1, 10, 50, 100], min_length=1, max_length=10
    )
    failure_rate_threshold: float = Field(0.2, ge=0.0, le=1.0)
    no_quorum_timeout_s: int = Field(1800, ge=60, le=7 * 24 * 3600)
    stage_timeout_s: int = Field(1800, ge=60, le=7 * 24 * 3600)
    defer_rate_threshold: float = Field(0.5, ge=0.0, le=1.0)
    health_timeout_s: int = Field(300, ge=10, le=24 * 3600)
    command_ttl_s: int = Field(180 * 24 * 3600, ge=60, le=400 * 24 * 3600)
    power_guard_required: bool = True
    rollback_to_tag: Optional[str] = Field(None, min_length=1, max_length=128)


class DeploymentTargetOut(BaseModel):
    device_id: str
    stage_assigned: int
    status: str
    last_report_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    report_details: Dict[str, Any] = Field(default_factory=dict)


class DeploymentEventOut(BaseModel):
    id: str
    deployment_id: str
    event_type: str
    device_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DeploymentOut(BaseModel):
    id: str
    manifest_id: str
    strategy: Dict[str, Any] = Field(default_factory=dict)
    stage: int
    status: str
    halt_reason: Optional[str] = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    failure_rate_threshold: float
    no_quorum_timeout_s: int
    stage_timeout_s: int
    defer_rate_threshold: float
    command_expires_at: datetime
    power_guard_required: bool
    health_timeout_s: int
    rollback_to_tag: Optional[str] = None
    target_selector: Dict[str, Any] = Field(default_factory=dict)
    total_targets: int = 0
    queued_targets: int = 0
    in_progress_targets: int = 0
    deferred_targets: int = 0
    healthy_targets: int = 0
    failed_targets: int = 0
    rolled_back_targets: int = 0


class DeploymentDetailOut(DeploymentOut):
    manifest: ReleaseManifestOut
    targets: List[DeploymentTargetOut] = Field(default_factory=list)
    events: List[DeploymentEventOut] = Field(default_factory=list)


class DeploymentTargetPageOut(BaseModel):
    items: List[DeploymentTargetOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class DeploymentActionOut(BaseModel):
    id: str
    status: str
    stage: int
    halt_reason: Optional[str] = None
    updated_at: datetime


class DeviceUpdateReportIn(BaseModel):
    state: Literal[
        "downloading",
        "downloaded",
        "verifying",
        "applying",
        "staged",
        "switching",
        "restarting",
        "healthy",
        "rolled_back",
        "failed",
        "deferred",
    ]
    reason_code: Optional[str] = Field(None, min_length=1, max_length=128)
    reason_detail: Optional[str] = Field(None, min_length=1, max_length=1024)


class DeviceUpdateReportOut(BaseModel):
    deployment_id: str
    device_id: str
    status: str
    stage: int
    deployment_status: str
    updated_at: datetime
