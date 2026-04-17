"""Add fleet governance tables.

Revision ID: 0017_fleet_governance
Revises: 0016_device_cloud_core
Create Date: 2026-04-17

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0017_fleet_governance"
down_revision = "0016_device_cloud_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fleets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column(
            "default_ota_channel",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'stable'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_fleets_name"),
    )
    op.create_index("ix_fleets_name", "fleets", ["name"])

    op.create_table(
        "fleet_device_memberships",
        sa.Column("fleet_id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["fleet_id"], ["fleets.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.PrimaryKeyConstraint("fleet_id", "device_id"),
    )
    op.create_index("ix_fleet_device_memberships_device", "fleet_device_memberships", ["device_id"])

    op.create_table(
        "fleet_access_grants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("fleet_id", sa.String(length=36), nullable=False),
        sa.Column("principal_email", sa.String(length=320), nullable=False),
        sa.Column(
            "access_role",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'viewer'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["fleet_id"], ["fleets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fleet_id", "principal_email", name="uq_fleet_access_grants_fleet_principal"),
    )
    op.create_index(
        "ix_fleet_access_grants_principal_role",
        "fleet_access_grants",
        ["principal_email", "access_role"],
    )
    op.create_index(
        "ix_fleet_access_grants_fleet_role",
        "fleet_access_grants",
        ["fleet_id", "access_role"],
    )


def downgrade() -> None:
    op.drop_index("ix_fleet_access_grants_fleet_role", table_name="fleet_access_grants")
    op.drop_index("ix_fleet_access_grants_principal_role", table_name="fleet_access_grants")
    op.drop_table("fleet_access_grants")

    op.drop_index("ix_fleet_device_memberships_device", table_name="fleet_device_memberships")
    op.drop_table("fleet_device_memberships")

    op.drop_index("ix_fleets_name", table_name="fleets")
    op.drop_table("fleets")
