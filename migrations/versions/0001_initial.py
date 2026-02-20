"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-02-19

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _json_type():
    if _is_postgres():
        return postgresql.JSONB(astext_type=sa.Text())
    return sa.JSON()


def _json_object_default():
    if _is_postgres():
        return sa.text("'{}'::jsonb")
    return sa.text("'{}'")


def _now_default():
    if _is_postgres():
        return sa.text("now()")
    return sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("device_id", sa.String(length=128), primary_key=True, nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("token_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("heartbeat_interval_s", sa.Integer(), nullable=False, server_default=sa.text("60")),
        sa.Column("offline_after_s", sa.Integer(), nullable=False, server_default=sa.text("300")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_now_default(),
        ),
    )
    op.create_index("ix_devices_token_fingerprint", "devices", ["token_fingerprint"], unique=False)

    op.create_table(
        "telemetry_points",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metrics",
            _json_type(),
            nullable=False,
            server_default=_json_object_default(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_now_default(),
        ),
        sa.UniqueConstraint("device_id", "message_id", name="uq_telemetry_device_message_id"),
    )
    op.create_index("ix_telemetry_device_ts", "telemetry_points", ["device_id", "ts"], unique=False)

    op.create_table(
        "alerts",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("alert_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("message", sa.String(length=1024), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_now_default(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_alerts_device_created", "alerts", ["device_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_alerts_device_created", table_name="alerts")
    op.drop_table("alerts")

    op.drop_index("ix_telemetry_device_ts", table_name="telemetry_points")
    op.drop_table("telemetry_points")

    op.drop_index("ix_devices_token_fingerprint", table_name="devices")
    op.drop_table("devices")
