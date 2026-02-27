"""Add per-device operation controls and ownership grants.

Revision ID: 0012_device_controls_access
Revises: 0011_notification_destinations
Create Date: 2026-02-27

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0012_device_controls_access"
down_revision = "0011_notification_destinations"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _now_default():
    if _is_postgres():
        return sa.text("now()")
    return sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column(
            "operation_mode",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
    )
    op.add_column(
        "devices",
        sa.Column(
            "sleep_poll_interval_s",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("604800"),
        ),
    )
    op.add_column("devices", sa.Column("alerts_muted_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("devices", sa.Column("alerts_muted_reason", sa.String(length=512), nullable=True))
    op.create_index("ix_devices_operation_mode", "devices", ["operation_mode"], unique=False)

    op.create_table(
        "device_access_grants",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("principal_email", sa.String(length=320), nullable=False),
        sa.Column(
            "access_role",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'viewer'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint("device_id", "principal_email", name="uq_device_access_grants_device_principal"),
    )
    op.create_index(
        "ix_device_access_grants_principal_role",
        "device_access_grants",
        ["principal_email", "access_role"],
        unique=False,
    )
    op.create_index(
        "ix_device_access_grants_device_role",
        "device_access_grants",
        ["device_id", "access_role"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_device_access_grants_device_role", table_name="device_access_grants")
    op.drop_index("ix_device_access_grants_principal_role", table_name="device_access_grants")
    op.drop_table("device_access_grants")

    op.drop_index("ix_devices_operation_mode", table_name="devices")
    op.drop_column("devices", "alerts_muted_reason")
    op.drop_column("devices", "alerts_muted_until")
    op.drop_column("devices", "sleep_poll_interval_s")
    op.drop_column("devices", "operation_mode")
