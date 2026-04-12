"""Add low-power runtime mode fields to devices.

Revision ID: 0015_device_low_power_runtime
Revises: 0014_release_deployments_ota
Create Date: 2026-03-17

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0015_device_low_power_runtime"
down_revision = "0014_release_deployments_ota"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column(
            "runtime_power_mode",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'continuous'"),
        ),
    )
    op.add_column(
        "devices",
        sa.Column(
            "deep_sleep_backend",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'auto'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("devices", "deep_sleep_backend")
    op.drop_column("devices", "runtime_power_mode")
