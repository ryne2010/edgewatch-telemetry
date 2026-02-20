"""Add alert routing, drift events, quarantine, and analytics export tables.

Revision ID: 0004_alerting_pipeline
Revises: 0003_ingestion_batches
Create Date: 2026-02-20

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0004_alerting_pipeline"
down_revision = "0003_ingestion_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_batches",
        sa.Column("points_quarantined", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "ingestion_batches",
        sa.Column(
            "type_mismatch_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "ingestion_batches",
        sa.Column(
            "drift_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "ingestion_batches",
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'device'"),
        ),
    )
    op.add_column(
        "ingestion_batches",
        sa.Column(
            "pipeline_mode",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'direct'"),
        ),
    )
    op.add_column(
        "ingestion_batches",
        sa.Column(
            "processing_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'completed'"),
        ),
    )

    op.create_table(
        "alert_policies",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=True),
        sa.Column("dedupe_window_s", sa.Integer(), nullable=False, server_default=sa.text("900")),
        sa.Column("throttle_window_s", sa.Integer(), nullable=False, server_default=sa.text("3600")),
        sa.Column(
            "throttle_max_notifications",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("20"),
        ),
        sa.Column("quiet_hours_start_minute", sa.Integer(), nullable=True),
        sa.Column("quiet_hours_end_minute", sa.Integer(), nullable=True),
        sa.Column("quiet_hours_tz", sa.String(length=64), nullable=False, server_default=sa.text("'UTC'")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("device_id", name="uq_alert_policies_device"),
    )

    op.create_table(
        "notification_events",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("alert_id", sa.String(length=36), sa.ForeignKey("alerts.id"), nullable=True),
        sa.Column("device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("alert_type", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=64), nullable=False),
        sa.Column("delivered", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reason", sa.String(length=1024), nullable=False),
        sa.Column("destination_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("error_class", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_notification_events_device_created",
        "notification_events",
        ["device_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_notification_events_device_alert_created",
        "notification_events",
        ["device_id", "alert_type", "created_at"],
        unique=False,
    )

    op.create_table(
        "drift_events",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("batch_id", sa.String(length=36), sa.ForeignKey("ingestion_batches.id"), nullable=False),
        sa.Column("device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_drift_events_batch_created",
        "drift_events",
        ["batch_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "quarantined_telemetry",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("batch_id", sa.String(length=36), sa.ForeignKey("ingestion_batches.id"), nullable=False),
        sa.Column("device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "errors",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_quarantined_telemetry_batch_created",
        "quarantined_telemetry",
        ["batch_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_quarantined_telemetry_device_created",
        "quarantined_telemetry",
        ["device_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "export_batches",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("watermark_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("watermark_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("contract_hash", sa.String(length=64), nullable=False),
        sa.Column("gcs_uri", sa.String(length=1024), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'running'")),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_export_batches_status_started",
        "export_batches",
        ["status", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_export_batches_status_started", table_name="export_batches")
    op.drop_table("export_batches")

    op.drop_index("ix_quarantined_telemetry_device_created", table_name="quarantined_telemetry")
    op.drop_index("ix_quarantined_telemetry_batch_created", table_name="quarantined_telemetry")
    op.drop_table("quarantined_telemetry")

    op.drop_index("ix_drift_events_batch_created", table_name="drift_events")
    op.drop_table("drift_events")

    op.drop_index("ix_notification_events_device_alert_created", table_name="notification_events")
    op.drop_index("ix_notification_events_device_created", table_name="notification_events")
    op.drop_table("notification_events")

    op.drop_table("alert_policies")

    op.drop_column("ingestion_batches", "processing_status")
    op.drop_column("ingestion_batches", "pipeline_mode")
    op.drop_column("ingestion_batches", "source")
    op.drop_column("ingestion_batches", "drift_summary")
    op.drop_column("ingestion_batches", "type_mismatch_keys")
    op.drop_column("ingestion_batches", "points_quarantined")
