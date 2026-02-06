from __future__ import annotations

import uuid
from datetime import datetime

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

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    telemetry_points: Mapped[list["TelemetryPoint"]] = relationship(back_populates="device")

    __table_args__ = (
        Index("ix_devices_token_fingerprint", "token_fingerprint"),
    )


class TelemetryPoint(Base):
    __tablename__ = "telemetry_points"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id: Mapped[str] = mapped_column(String(64), nullable=False)

    device_id: Mapped[str] = mapped_column(String(128), ForeignKey("devices.device_id"), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    device: Mapped["Device"] = relationship(back_populates="telemetry_points")

    __table_args__ = (
        UniqueConstraint("message_id", name="uq_telemetry_message_id"),
        Index("ix_telemetry_device_ts", "device_id", "ts"),
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id: Mapped[str] = mapped_column(String(128), ForeignKey("devices.device_id"), nullable=False)

    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    message: Mapped[str] = mapped_column(String(1024), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_alerts_device_created", "device_id", "created_at"),
    )
