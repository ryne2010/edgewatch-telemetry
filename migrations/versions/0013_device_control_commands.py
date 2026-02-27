"""Add durable per-device control command queue.

Revision ID: 0013_device_control_commands
Revises: 0012_device_controls_access
Create Date: 2026-02-27

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0013_device_control_commands"
down_revision = "0012_device_controls_access"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _now_default():
    if _is_postgres():
        return sa.text("now()")
    return sa.text("CURRENT_TIMESTAMP")


def _json_type():
    if _is_postgres():
        return postgresql.JSONB(astext_type=sa.Text())
    return sa.JSON()


def _json_object_default():
    if _is_postgres():
        return sa.text("'{}'::jsonb")
    return sa.text("'{}'")


def upgrade() -> None:
    op.create_table(
        "device_control_commands",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column(
            "command_payload",
            _json_type(),
            nullable=False,
            server_default=_json_object_default(),
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_device_control_commands_device_status_expires_issued",
        "device_control_commands",
        ["device_id", "status", "expires_at", "issued_at"],
        unique=False,
    )
    op.create_index(
        "ix_device_control_commands_status_expires",
        "device_control_commands",
        ["status", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_device_control_commands_status_expires",
        table_name="device_control_commands",
    )
    op.drop_index(
        "ix_device_control_commands_device_status_expires_issued",
        table_name="device_control_commands",
    )
    op.drop_table("device_control_commands")
