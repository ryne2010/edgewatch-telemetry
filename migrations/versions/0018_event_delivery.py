"""Generalize notification delivery for non-alert event sources.

Revision ID: 0018_event_delivery
Revises: 0017_fleet_governance
Create Date: 2026-04-17

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0018_event_delivery"
down_revision = "0017_fleet_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_destinations",
        sa.Column("source_types", sa.JSON(), nullable=False, server_default=sa.text("'[\"alert\"]'")),
    )
    op.add_column(
        "notification_destinations",
        sa.Column("event_types", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )

    op.add_column(
        "notification_events",
        sa.Column("source_kind", sa.String(length=32), nullable=False, server_default=sa.text("'alert'")),
    )
    op.add_column("notification_events", sa.Column("source_id", sa.String(length=36), nullable=True))
    op.add_column(
        "notification_events",
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("notification_events", "payload")
    op.drop_column("notification_events", "source_id")
    op.drop_column("notification_events", "source_kind")
    op.drop_column("notification_destinations", "event_types")
    op.drop_column("notification_destinations", "source_types")
