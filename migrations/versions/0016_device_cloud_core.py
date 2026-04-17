"""Add device cloud core tables and OTA governance fields.

Revision ID: 0016_device_cloud_core
Revises: 0015_device_low_power_runtime
Create Date: 2026-04-17

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0016_device_cloud_core"
down_revision = "0015_device_low_power_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("ota_channel", sa.String(length=64), nullable=False, server_default=sa.text("'stable'")),
    )
    op.add_column(
        "devices",
        sa.Column("ota_updates_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column("devices", sa.Column("ota_busy_reason", sa.String(length=256), nullable=True))
    op.add_column(
        "devices",
        sa.Column("ota_is_development", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("devices", sa.Column("ota_locked_manifest_id", sa.String(length=36), nullable=True))

    op.add_column(
        "release_manifests",
        sa.Column(
            "update_type",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'application_bundle'"),
        ),
    )
    op.add_column(
        "release_manifests",
        sa.Column("artifact_uri", sa.String(length=2048), nullable=False, server_default=sa.text("''")),
    )
    op.add_column(
        "release_manifests",
        sa.Column("artifact_size", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "release_manifests",
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False, server_default=sa.text("''")),
    )
    op.add_column(
        "release_manifests",
        sa.Column("artifact_signature", sa.Text(), nullable=False, server_default=sa.text("''")),
    )
    op.add_column(
        "release_manifests",
        sa.Column(
            "artifact_signature_scheme",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'none'"),
        ),
    )
    op.add_column(
        "release_manifests",
        sa.Column("compatibility", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )

    op.add_column(
        "deployments",
        sa.Column("stage_timeout_s", sa.Integer(), nullable=False, server_default=sa.text("1800")),
    )
    op.add_column(
        "deployments",
        sa.Column("defer_rate_threshold", sa.Float(), nullable=False, server_default=sa.text("0.5")),
    )

    op.add_column(
        "device_release_state", sa.Column("current_manifest_id", sa.String(length=36), nullable=True)
    )
    op.add_column(
        "device_release_state", sa.Column("current_artifact_sha256", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "device_release_state", sa.Column("last_failed_manifest_id", sa.String(length=36), nullable=True)
    )
    op.add_column(
        "device_release_state", sa.Column("pending_manifest_id", sa.String(length=36), nullable=True)
    )
    op.add_column(
        "device_release_state", sa.Column("pending_artifact_sha256", sa.String(length=64), nullable=True)
    )

    op.create_table(
        "device_procedure_definitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("request_schema", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("response_schema", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("timeout_s", sa.Integer(), nullable=False, server_default=sa.text("300")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_by", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_device_procedure_definitions_name"),
    )
    op.create_index(
        "ix_device_procedure_definitions_enabled_name",
        "device_procedure_definitions",
        ["enabled", "name"],
    )

    op.create_table(
        "device_procedure_invocations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("definition_id", sa.String(length=36), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("result_payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("reason_code", sa.String(length=128), nullable=True),
        sa.Column("reason_detail", sa.String(length=1024), nullable=True),
        sa.Column("requester_email", sa.String(length=320), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.ForeignKeyConstraint(["definition_id"], ["device_procedure_definitions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_device_procedure_invocations_device_status_expires_issued",
        "device_procedure_invocations",
        ["device_id", "status", "expires_at", "issued_at"],
    )
    op.create_index(
        "ix_device_procedure_invocations_definition_created",
        "device_procedure_invocations",
        ["definition_id", "issued_at"],
    )

    op.create_table(
        "device_reported_state",
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("schema_type", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.PrimaryKeyConstraint("device_id", "key"),
    )
    op.create_index("ix_device_reported_state_updated_at", "device_reported_state", ["updated_at"])

    op.create_table(
        "device_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default=sa.text("'device'")),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default=sa.text("'info'")),
        sa.Column("body", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_device_events_device_created", "device_events", ["device_id", "created_at"])
    op.create_index("ix_device_events_type_created", "device_events", ["event_type", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_device_events_type_created", table_name="device_events")
    op.drop_index("ix_device_events_device_created", table_name="device_events")
    op.drop_table("device_events")

    op.drop_index("ix_device_reported_state_updated_at", table_name="device_reported_state")
    op.drop_table("device_reported_state")

    op.drop_index(
        "ix_device_procedure_invocations_definition_created",
        table_name="device_procedure_invocations",
    )
    op.drop_index(
        "ix_device_procedure_invocations_device_status_expires_issued",
        table_name="device_procedure_invocations",
    )
    op.drop_table("device_procedure_invocations")

    op.drop_index("ix_device_procedure_definitions_enabled_name", table_name="device_procedure_definitions")
    op.drop_table("device_procedure_definitions")

    op.drop_column("device_release_state", "pending_artifact_sha256")
    op.drop_column("device_release_state", "pending_manifest_id")
    op.drop_column("device_release_state", "last_failed_manifest_id")
    op.drop_column("device_release_state", "current_artifact_sha256")
    op.drop_column("device_release_state", "current_manifest_id")

    op.drop_column("deployments", "defer_rate_threshold")
    op.drop_column("deployments", "stage_timeout_s")

    op.drop_column("release_manifests", "compatibility")
    op.drop_column("release_manifests", "artifact_signature_scheme")
    op.drop_column("release_manifests", "artifact_signature")
    op.drop_column("release_manifests", "artifact_sha256")
    op.drop_column("release_manifests", "artifact_size")
    op.drop_column("release_manifests", "artifact_uri")
    op.drop_column("release_manifests", "update_type")

    op.drop_column("devices", "ota_locked_manifest_id")
    op.drop_column("devices", "ota_is_development")
    op.drop_column("devices", "ota_busy_reason")
    op.drop_column("devices", "ota_updates_enabled")
    op.drop_column("devices", "ota_channel")
