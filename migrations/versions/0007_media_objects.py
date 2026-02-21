"""Add media_objects table for camera metadata + uploads.

Revision ID: 0007_media_objects
Revises: 0006_performance_indexes
Create Date: 2026-02-21

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0007_media_objects"
down_revision = "0006_performance_indexes"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _now_default():
    if _is_postgres():
        return sa.text("now()")
    return sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "media_objects",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("camera_id", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("object_path", sa.String(length=1024), nullable=False),
        sa.Column("gcs_uri", sa.String(length=1024), nullable=True),
        sa.Column("local_path", sa.String(length=1024), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.UniqueConstraint("device_id", "message_id", "camera_id", name="uq_media_device_message_camera"),
    )

    op.create_index(
        "ix_media_objects_device_captured",
        "media_objects",
        ["device_id", "captured_at"],
        unique=False,
    )
    op.create_index(
        "ix_media_objects_device_camera_captured",
        "media_objects",
        ["device_id", "camera_id", "captured_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_media_objects_device_camera_captured", table_name="media_objects")
    op.drop_index("ix_media_objects_device_captured", table_name="media_objects")
    op.drop_table("media_objects")
