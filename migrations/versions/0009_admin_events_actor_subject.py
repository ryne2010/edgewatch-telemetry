"""Add actor_subject to admin_events for principal attribution.

Revision ID: 0009_admin_events_actor_subject
Revises: 0008_admin_events
Create Date: 2026-02-21

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0009_admin_events_actor_subject"
down_revision = "0008_admin_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("admin_events", sa.Column("actor_subject", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("admin_events", "actor_subject")
