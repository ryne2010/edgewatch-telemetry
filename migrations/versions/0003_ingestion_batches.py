"""Add ingestion_batches for contract + drift visibility.

Revision ID: 0003_ingestion_batches
Revises: 0002_unique_token_fingerprint
Create Date: 2026-02-19

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0003_ingestion_batches"
down_revision = "0002_unique_token_fingerprint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_batches",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("contract_hash", sa.String(length=64), nullable=False),
        sa.Column("points_submitted", sa.Integer(), nullable=False),
        sa.Column("points_accepted", sa.Integer(), nullable=False),
        sa.Column("duplicates", sa.Integer(), nullable=False),
        sa.Column("client_ts_min", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_ts_max", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "unknown_metric_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_ingestion_batches_device_received",
        "ingestion_batches",
        ["device_id", "received_at"],
        unique=False,
    )

    # Optional lineage pointer from points to a batch.
    op.add_column("telemetry_points", sa.Column("batch_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_telemetry_points_batch_id",
        "telemetry_points",
        "ingestion_batches",
        ["batch_id"],
        ["id"],
    )
    op.create_index("ix_telemetry_batch_id", "telemetry_points", ["batch_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_telemetry_batch_id", table_name="telemetry_points")
    op.drop_constraint("fk_telemetry_points_batch_id", "telemetry_points", type_="foreignkey")
    op.drop_column("telemetry_points", "batch_id")

    op.drop_index("ix_ingestion_batches_device_received", table_name="ingestion_batches")
    op.drop_table("ingestion_batches")
