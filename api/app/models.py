from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String,
    Integer,
    Float,
    DateTime,
    Boolean,
    JSON,
    Text,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def json_type() -> JSON:
    # Keep PostgreSQL JSONB in production while remaining portable for SQLite-based demos/tests.
    return JSON().with_variant(JSONB(astext_type=Text()), "postgresql")


class Device(Base):
    __tablename__ = "devices"

    device_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)

    # Device auth token: store only a PBKDF2 hash + a SHA-256 fingerprint for efficient lookup
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    token_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    heartbeat_interval_s: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    offline_after_s: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    operation_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    sleep_poll_interval_s: Mapped[int] = mapped_column(Integer, nullable=False, default=7 * 24 * 3600)
    runtime_power_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="continuous")
    deep_sleep_backend: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    alerts_muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    alerts_muted_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    cohort: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ota_channel: Mapped[str] = mapped_column(String(64), nullable=False, default="stable")
    ota_updates_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ota_busy_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    ota_is_development: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ota_locked_manifest_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("release_manifests.id"), nullable=True
    )
    labels: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    telemetry_points: Mapped[list["TelemetryPoint"]] = relationship(back_populates="device")

    ingestion_batches: Mapped[list[IngestionBatch]] = relationship(back_populates="device")
    alert_policy: Mapped["AlertPolicy | None"] = relationship(back_populates="device", uselist=False)
    notification_events: Mapped[list["NotificationEvent"]] = relationship(back_populates="device")
    admin_events: Mapped[list["AdminEvent"]] = relationship(back_populates="device")
    drift_events: Mapped[list["DriftEvent"]] = relationship(back_populates="device")
    quarantined_telemetry: Mapped[list["QuarantinedTelemetry"]] = relationship(back_populates="device")
    media_objects: Mapped[list["MediaObject"]] = relationship(back_populates="device")
    access_grants: Mapped[list["DeviceAccessGrant"]] = relationship(back_populates="device")
    fleet_memberships: Mapped[list["FleetDeviceMembership"]] = relationship(back_populates="device")
    control_commands: Mapped[list["DeviceControlCommand"]] = relationship(back_populates="device")
    procedure_invocations: Mapped[list["DeviceProcedureInvocation"]] = relationship(back_populates="device")
    reported_state_rows: Mapped[list["DeviceReportedState"]] = relationship(back_populates="device")
    device_events: Mapped[list["DeviceEvent"]] = relationship(back_populates="device")
    release_state: Mapped["DeviceReleaseState | None"] = relationship(back_populates="device", uselist=False)

    __table_args__ = (Index("ix_devices_token_fingerprint", "token_fingerprint", unique=True),)


class DeviceAccessGrant(Base):
    __tablename__ = "device_access_grants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id: Mapped[str] = mapped_column(String(128), ForeignKey("devices.device_id"), nullable=False)
    principal_email: Mapped[str] = mapped_column(String(320), nullable=False)
    access_role: Mapped[str] = mapped_column(String(16), nullable=False, default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    device: Mapped["Device"] = relationship(back_populates="access_grants")

    __table_args__ = (
        UniqueConstraint("device_id", "principal_email", name="uq_device_access_grants_device_principal"),
        Index("ix_device_access_grants_principal_role", "principal_email", "access_role"),
        Index("ix_device_access_grants_device_role", "device_id", "access_role"),
    )


class Fleet(Base):
    __tablename__ = "fleets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    default_ota_channel: Mapped[str] = mapped_column(String(64), nullable=False, default="stable")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    devices: Mapped[list["FleetDeviceMembership"]] = relationship(back_populates="fleet")
    access_grants: Mapped[list["FleetAccessGrant"]] = relationship(back_populates="fleet")

    __table_args__ = (
        UniqueConstraint("name", name="uq_fleets_name"),
        Index("ix_fleets_name", "name"),
    )


class FleetDeviceMembership(Base):
    __tablename__ = "fleet_device_memberships"

    fleet_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("fleets.id"), primary_key=True, nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("devices.device_id"), primary_key=True, nullable=False
    )
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    fleet: Mapped["Fleet"] = relationship(back_populates="devices")
    device: Mapped["Device"] = relationship(back_populates="fleet_memberships")

    __table_args__ = (Index("ix_fleet_device_memberships_device", "device_id"),)


class FleetAccessGrant(Base):
    __tablename__ = "fleet_access_grants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    fleet_id: Mapped[str] = mapped_column(String(36), ForeignKey("fleets.id"), nullable=False)
    principal_email: Mapped[str] = mapped_column(String(320), nullable=False)
    access_role: Mapped[str] = mapped_column(String(16), nullable=False, default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    fleet: Mapped["Fleet"] = relationship(back_populates="access_grants")

    __table_args__ = (
        UniqueConstraint("fleet_id", "principal_email", name="uq_fleet_access_grants_fleet_principal"),
        Index("ix_fleet_access_grants_principal_role", "principal_email", "access_role"),
        Index("ix_fleet_access_grants_fleet_role", "fleet_id", "access_role"),
    )


class DeviceControlCommand(Base):
    __tablename__ = "device_control_commands"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id: Mapped[str] = mapped_column(String(128), ForeignKey("devices.device_id"), nullable=False)
    command_payload: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    device: Mapped["Device"] = relationship(back_populates="control_commands")

    __table_args__ = (
        Index(
            "ix_device_control_commands_device_status_expires_issued",
            "device_id",
            "status",
            "expires_at",
            "issued_at",
        ),
        Index("ix_device_control_commands_status_expires", "status", "expires_at"),
    )


class DeviceProcedureDefinition(Base):
    __tablename__ = "device_procedure_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    request_schema: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
    response_schema: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
    timeout_s: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    invocations: Mapped[list["DeviceProcedureInvocation"]] = relationship(back_populates="definition")

    __table_args__ = (
        UniqueConstraint("name", name="uq_device_procedure_definitions_name"),
        Index("ix_device_procedure_definitions_enabled_name", "enabled", "name"),
    )


class DeviceProcedureInvocation(Base):
    __tablename__ = "device_procedure_invocations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id: Mapped[str] = mapped_column(String(128), ForeignKey("devices.device_id"), nullable=False)
    definition_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("device_procedure_definitions.id"), nullable=False
    )
    request_payload: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
    result_payload: Mapped[dict | None] = mapped_column(json_type(), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    reason_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason_detail: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    requester_email: Mapped[str] = mapped_column(String(320), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    device: Mapped["Device"] = relationship(back_populates="procedure_invocations")
    definition: Mapped["DeviceProcedureDefinition"] = relationship(back_populates="invocations")

    __table_args__ = (
        Index(
            "ix_device_procedure_invocations_device_status_expires_issued",
            "device_id",
            "status",
            "expires_at",
            "issued_at",
        ),
        Index("ix_device_procedure_invocations_definition_created", "definition_id", "issued_at"),
    )


class DeviceReportedState(Base):
    __tablename__ = "device_reported_state"

    device_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("devices.device_id"), primary_key=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(128), primary_key=True, nullable=False)
    value_json: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
    schema_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    device: Mapped["Device"] = relationship(back_populates="reported_state_rows")

    __table_args__ = (Index("ix_device_reported_state_updated_at", "updated_at"),)


class DeviceEvent(Base):
    __tablename__ = "device_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id: Mapped[str] = mapped_column(String(128), ForeignKey("devices.device_id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="device")
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    body: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    device: Mapped["Device"] = relationship(back_populates="device_events")

    __table_args__ = (
        Index("ix_device_events_device_created", "device_id", "created_at"),
        Index("ix_device_events_type_created", "event_type", "created_at"),
    )


class ReleaseManifest(Base):
    __tablename__ = "release_manifests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    git_tag: Mapped[str] = mapped_column(String(128), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    update_type: Mapped[str] = mapped_column(String(32), nullable=False, default="application_bundle")
    artifact_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    artifact_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    artifact_signature: Mapped[str] = mapped_column(Text, nullable=False, default="")
    artifact_signature_scheme: Mapped[str] = mapped_column(String(64), nullable=False, default="none")
    compatibility: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    signature_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    constraints: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    deployments: Mapped[list["Deployment"]] = relationship(back_populates="manifest")

    __table_args__ = (
        UniqueConstraint("git_tag", "commit_sha", name="uq_release_manifests_tag_commit"),
        Index("ix_release_manifests_created_at", "created_at"),
        Index("ix_release_manifests_status_created_at", "status", "created_at"),
    )


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    manifest_id: Mapped[str] = mapped_column(String(36), ForeignKey("release_manifests.id"), nullable=False)
    strategy: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
    stage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    halt_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_by: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    failure_rate_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    no_quorum_timeout_s: Mapped[int] = mapped_column(Integer, nullable=False, default=1800)
    stage_timeout_s: Mapped[int] = mapped_column(Integer, nullable=False, default=1800)
    defer_rate_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    command_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    power_guard_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    health_timeout_s: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    rollback_to_tag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_selector: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)

    manifest: Mapped["ReleaseManifest"] = relationship(back_populates="deployments")
    targets: Mapped[list["DeploymentTarget"]] = relationship(back_populates="deployment")
    events: Mapped[list["DeploymentEvent"]] = relationship(back_populates="deployment")

    __table_args__ = (
        Index("ix_deployments_manifest_created_at", "manifest_id", "created_at"),
        Index("ix_deployments_status_updated_at", "status", "updated_at"),
    )


class DeploymentTarget(Base):
    __tablename__ = "deployment_targets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    deployment_id: Mapped[str] = mapped_column(String(36), ForeignKey("deployments.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(128), ForeignKey("devices.device_id"), nullable=False)
    stage_assigned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    last_report_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    report_details: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)

    deployment: Mapped["Deployment"] = relationship(back_populates="targets")
    device: Mapped["Device"] = relationship()

    __table_args__ = (
        UniqueConstraint("deployment_id", "device_id", name="uq_deployment_targets_deployment_device"),
        Index("ix_deployment_targets_deployment_status", "deployment_id", "status"),
        Index("ix_deployment_targets_device_last_report_at", "device_id", "last_report_at"),
    )


class DeviceReleaseState(Base):
    __tablename__ = "device_release_state"

    device_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("devices.device_id"), primary_key=True, nullable=False
    )
    current_tag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    current_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_manifest_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_healthy_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failed_tag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_failed_manifest_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    rollback_tag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pending_manifest_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    pending_artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_deployment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    device: Mapped["Device"] = relationship(back_populates="release_state")


class DeploymentEvent(Base):
    __tablename__ = "deployment_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    deployment_id: Mapped[str] = mapped_column(String(36), ForeignKey("deployments.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    deployment: Mapped["Deployment"] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_deployment_events_deployment_created_at", "deployment_id", "created_at"),
        Index("ix_deployment_events_event_type_created_at", "event_type", "created_at"),
    )


class TelemetryPoint(Base):
    __tablename__ = "telemetry_points"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id: Mapped[str] = mapped_column(String(64), nullable=False)

    device_id: Mapped[str] = mapped_column(String(128), ForeignKey("devices.device_id"), nullable=False)

    # Optional pointer to a single ingestion event/batch (lineage-lite).
    batch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ingestion_batches.id"), nullable=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metrics: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    device: Mapped["Device"] = relationship(back_populates="telemetry_points")

    ingestion_batch: Mapped[IngestionBatch | None] = relationship(back_populates="telemetry_points")

    __table_args__ = (
        # Idempotency should be per-device (message IDs are generated on the edge).
        # A global uniqueness constraint could accidentally dedupe two different devices.
        UniqueConstraint("device_id", "message_id", name="uq_telemetry_device_message_id"),
        Index("ix_telemetry_device_ts", "device_id", "ts"),
        Index("ix_telemetry_batch_id", "batch_id"),
    )


class TelemetryIngestDedupe(Base):
    __tablename__ = "telemetry_ingest_dedupe"

    device_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("devices.device_id"),
        primary_key=True,
        nullable=False,
    )
    message_id: Mapped[str] = mapped_column(String(64), primary_key=True, nullable=False)
    point_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (Index("ix_telemetry_ingest_dedupe_point_ts", "point_ts"),)


class TelemetryRollupHourly(Base):
    __tablename__ = "telemetry_rollups_hourly"

    device_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("devices.device_id"),
        primary_key=True,
        nullable=False,
    )
    metric_key: Mapped[str] = mapped_column(String(64), primary_key=True, nullable=False)
    bucket_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_value: Mapped[float] = mapped_column(Float, nullable=False)
    max_value: Mapped[float] = mapped_column(Float, nullable=False)
    avg_value: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_telemetry_rollups_hourly_bucket_ts", "bucket_ts"),
        Index("ix_telemetry_rollups_hourly_metric_bucket", "metric_key", "bucket_ts"),
    )


class IngestionBatch(Base):
    __tablename__ = "ingestion_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    device_id: Mapped[str] = mapped_column(String(128), ForeignKey("devices.device_id"), nullable=False)

    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    points_submitted: Mapped[int] = mapped_column(Integer, nullable=False)
    points_accepted: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicates: Mapped[int] = mapped_column(Integer, nullable=False)
    points_quarantined: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    client_ts_min: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    client_ts_max: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Additive drift visibility (unknown metric keys observed in this ingestion).
    unknown_metric_keys: Mapped[list[str]] = mapped_column(json_type(), nullable=False, default=list)
    type_mismatch_keys: Mapped[list[str]] = mapped_column(json_type(), nullable=False, default=list)
    drift_summary: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)

    # Ingestion lineage dimensions for replay/pubsub observability.
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="device")
    pipeline_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="direct")
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    device: Mapped["Device"] = relationship(back_populates="ingestion_batches")
    telemetry_points: Mapped[list["TelemetryPoint"]] = relationship(back_populates="ingestion_batch")
    drift_events: Mapped[list["DriftEvent"]] = relationship(back_populates="ingestion_batch")
    quarantined_points: Mapped[list["QuarantinedTelemetry"]] = relationship(back_populates="ingestion_batch")

    __table_args__ = (Index("ix_ingestion_batches_device_received", "device_id", "received_at"),)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id: Mapped[str] = mapped_column(String(128), ForeignKey("devices.device_id"), nullable=False)

    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    message: Mapped[str] = mapped_column(String(1024), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notification_events: Mapped[list["NotificationEvent"]] = relationship(back_populates="alert")

    __table_args__ = (
        # Device drill-down queries
        Index("ix_alerts_device_created", "device_id", "created_at"),
        # Global feed pagination ordering (created_at desc, id desc)
        Index("ix_alerts_created_id", "created_at", "id"),
        # Open-only feeds filter resolved_at IS NULL and order by created_at
        Index("ix_alerts_resolved_created", "resolved_at", "created_at"),
    )


class AlertPolicy(Base):
    __tablename__ = "alert_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id: Mapped[str | None] = mapped_column(String(128), ForeignKey("devices.device_id"), nullable=True)

    dedupe_window_s: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    throttle_window_s: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    throttle_max_notifications: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    quiet_hours_start_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quiet_hours_end_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quiet_hours_tz: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    device: Mapped["Device | None"] = relationship(back_populates="alert_policy")

    __table_args__ = (UniqueConstraint("device_id", name="uq_alert_policies_device"),)


class NotificationEvent(Base):
    __tablename__ = "notification_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    alert_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("alerts.id"), nullable=True)
    device_id: Mapped[str] = mapped_column(String(128), ForeignKey("devices.device_id"), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="alert")
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str] = mapped_column(String(64), nullable=False)
    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str] = mapped_column(String(1024), nullable=False)
    destination_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    alert: Mapped["Alert | None"] = relationship(back_populates="notification_events")
    device: Mapped["Device"] = relationship(back_populates="notification_events")

    __table_args__ = (
        Index("ix_notification_events_device_created", "device_id", "created_at"),
        Index("ix_notification_events_device_alert_created", "device_id", "alert_type", "created_at"),
    )


class NotificationDestination(Base):
    __tablename__ = "notification_destinations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="webhook")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="generic")
    webhook_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_types: Mapped[list[str]] = mapped_column(json_type(), nullable=False, default=list)
    event_types: Mapped[list[str]] = mapped_column(json_type(), nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("name", name="uq_notification_destinations_name"),
        Index("ix_notification_destinations_enabled_created", "enabled", "created_at"),
    )


class AdminEvent(Base):
    __tablename__ = "admin_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_email: Mapped[str] = mapped_column(String(320), nullable=False)
    actor_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False, default="device")
    target_device_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("devices.device_id"), nullable=True
    )
    details: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    device: Mapped["Device | None"] = relationship(back_populates="admin_events")

    __table_args__ = (
        Index("ix_admin_events_created", "created_at"),
        Index("ix_admin_events_actor_created", "actor_email", "created_at"),
        Index("ix_admin_events_target_created", "target_type", "target_device_id", "created_at"),
    )


class DriftEvent(Base):
    __tablename__ = "drift_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    batch_id: Mapped[str] = mapped_column(String(36), ForeignKey("ingestion_batches.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(128), ForeignKey("devices.device_id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    ingestion_batch: Mapped["IngestionBatch"] = relationship(back_populates="drift_events")
    device: Mapped["Device"] = relationship(back_populates="drift_events")

    __table_args__ = (Index("ix_drift_events_batch_created", "batch_id", "created_at"),)


class QuarantinedTelemetry(Base):
    __tablename__ = "quarantined_telemetry"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    batch_id: Mapped[str] = mapped_column(String(36), ForeignKey("ingestion_batches.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(String(128), ForeignKey("devices.device_id"), nullable=False)
    message_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metrics: Mapped[dict] = mapped_column(json_type(), nullable=False, default=dict)
    errors: Mapped[list[str]] = mapped_column(json_type(), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    ingestion_batch: Mapped["IngestionBatch"] = relationship(back_populates="quarantined_points")
    device: Mapped["Device"] = relationship(back_populates="quarantined_telemetry")

    __table_args__ = (
        Index("ix_quarantined_telemetry_batch_created", "batch_id", "created_at"),
        Index("ix_quarantined_telemetry_device_created", "device_id", "created_at"),
    )


class ExportBatch(Base):
    __tablename__ = "export_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    watermark_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    watermark_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    gcs_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (Index("ix_export_batches_status_started", "status", "started_at"),)


class MediaObject(Base):
    __tablename__ = "media_objects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id: Mapped[str] = mapped_column(String(128), ForeignKey("devices.device_id"), nullable=False)
    camera_id: Mapped[str] = mapped_column(String(32), nullable=False)
    message_id: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    object_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    gcs_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    local_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    device: Mapped["Device"] = relationship(back_populates="media_objects")

    __table_args__ = (
        UniqueConstraint("device_id", "message_id", "camera_id", name="uq_media_device_message_camera"),
        Index("ix_media_objects_device_captured", "device_id", "captured_at"),
        Index("ix_media_objects_device_camera_captured", "device_id", "camera_id", "captured_at"),
    )
