"""Add admin_events table for admin mutation attribution.

Revision ID: 0008_admin_events
Revises: 0007_media_objects
Create Date: 2026-02-21

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0008_admin_events"
down_revision = "0007_media_objects"
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
        "admin_events",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("actor_email", sa.String(length=320), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False, server_default=sa.text("'device'")),
        sa.Column(
            "target_device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=True
        ),
        sa.Column("details", _json_type(), nullable=False, server_default=_json_object_default()),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
    )
    op.create_index("ix_admin_events_created", "admin_events", ["created_at"], unique=False)
    op.create_index(
        "ix_admin_events_actor_created",
        "admin_events",
        ["actor_email", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_admin_events_target_created",
        "admin_events",
        ["target_type", "target_device_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_admin_events_target_created", table_name="admin_events")
    op.drop_index("ix_admin_events_actor_created", table_name="admin_events")
    op.drop_index("ix_admin_events_created", table_name="admin_events")
    op.drop_table("admin_events")
