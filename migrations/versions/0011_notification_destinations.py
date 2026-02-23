"""Add notification destinations table for UI-managed webhook endpoints.

Revision ID: 0011_notification_destinations
Revises: 0010_telemetry_partition_rollups
Create Date: 2026-02-22

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0011_notification_destinations"
down_revision = "0010_telemetry_partition_rollups"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _now_default():
    if _is_postgres():
        return sa.text("now()")
    return sa.text("CURRENT_TIMESTAMP")


def _bool_true_default():
    if _is_postgres():
        return sa.text("true")
    return sa.text("1")


def upgrade() -> None:
    op.create_table(
        "notification_destinations",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "channel",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'webhook'"),
        ),
        sa.Column(
            "kind",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'generic'"),
        ),
        sa.Column("webhook_url", sa.String(length=2048), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=_bool_true_default()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint("name", name="uq_notification_destinations_name"),
    )
    op.create_index(
        "ix_notification_destinations_enabled_created",
        "notification_destinations",
        ["enabled", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notification_destinations_enabled_created", table_name="notification_destinations")
    op.drop_table("notification_destinations")
