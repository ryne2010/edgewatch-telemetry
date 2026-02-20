from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String,
    Integer,
    DateTime,
    Boolean,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

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

    client_ts_min: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    client_ts_max: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Additive drift visibility (unknown metric keys observed in this ingestion).
    unknown_metric_keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    device: Mapped["Device"] = relationship(back_populates="ingestion_batches")
    telemetry_points: Mapped[list["TelemetryPoint"]] = relationship(back_populates="ingestion_batch")

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

    __table_args__ = (Index("ix_alerts_device_created", "device_id", "created_at"),)
