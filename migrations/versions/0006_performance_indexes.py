"""Performance indexes for open-alert feeds and retention.

Revision ID: 0006_performance_indexes
Revises: 0005_alert_indexes
Create Date: 2026-02-21

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0006_performance_indexes"
down_revision = "0005_alert_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alerts: open-only feeds are the hot path for dashboards.
    # A partial index is smaller + faster than indexing all rows.
    op.create_index(
        "ix_alerts_open_created_id",
        "alerts",
        ["created_at", "id"],
        unique=False,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )

    # Device detail often queries open alerts for a single device.
    op.create_index(
        "ix_alerts_device_open_created_id",
        "alerts",
        ["device_id", "created_at", "id"],
        unique=False,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )

    # Retention jobs delete by timestamp; a simple ts index reduces table scans.
    op.create_index("ix_telemetry_ts", "telemetry_points", ["ts"], unique=False)
    op.create_index(
        "ix_quarantined_telemetry_ts",
        "quarantined_telemetry",
        ["ts"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_quarantined_telemetry_ts", table_name="quarantined_telemetry")
    op.drop_index("ix_telemetry_ts", table_name="telemetry_points")

    op.drop_index("ix_alerts_device_open_created_id", table_name="alerts")
    op.drop_index("ix_alerts_open_created_id", table_name="alerts")
