from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String,
    Integer,
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

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    telemetry_points: Mapped[list["TelemetryPoint"]] = relationship(back_populates="device")

    ingestion_batches: Mapped[list[IngestionBatch]] = relationship(back_populates="device")
    alert_policy: Mapped["AlertPolicy | None"] = relationship(back_populates="device", uselist=False)
    notification_events: Mapped[list["NotificationEvent"]] = relationship(back_populates="device")
    drift_events: Mapped[list["DriftEvent"]] = relationship(back_populates="device")
    quarantined_telemetry: Mapped[list["QuarantinedTelemetry"]] = relationship(back_populates="device")

    __table_args__ = (Index("ix_devices_token_fingerprint", "token_fingerprint", unique=True),)


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
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str] = mapped_column(String(64), nullable=False)
    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str] = mapped_column(String(1024), nullable=False)
    destination_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    alert: Mapped["Alert | None"] = relationship(back_populates="notification_events")
    device: Mapped["Device"] = relationship(back_populates="notification_events")

    __table_args__ = (
        Index("ix_notification_events_device_created", "device_id", "created_at"),
        Index("ix_notification_events_device_alert_created", "device_id", "alert_type", "created_at"),
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
