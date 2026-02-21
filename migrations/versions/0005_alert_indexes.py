"""Add indexes to support alert pagination and open-only queries.

Revision ID: 0005_alert_indexes
Revises: 0004_alerting_pipeline
Create Date: 2026-02-21

"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "0005_alert_indexes"
down_revision = "0004_alerting_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Global feed ordering uses (created_at desc, id desc)
    op.create_index(
        "ix_alerts_created_id",
        "alerts",
        ["created_at", "id"],
        unique=False,
    )

    # Open-only feeds filter resolved_at IS NULL and order by created_at.
    op.create_index(
        "ix_alerts_resolved_created",
        "alerts",
        ["resolved_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_alerts_resolved_created", table_name="alerts")
    op.drop_index("ix_alerts_created_id", table_name="alerts")
