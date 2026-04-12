"""Add OTA release/deployment persistence for RPi fleet updates.

Revision ID: 0014_release_deployments_ota
Revises: 0013_device_control_commands
Create Date: 2026-02-27

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0014_release_deployments_ota"
down_revision = "0013_device_control_commands"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _now_default():
    if _is_postgres():
        return sa.text("now()")
    return sa.text("CURRENT_TIMESTAMP")


def _json_type():
    if _is_postgres():
        return postgresql.JSONB(astext_type=sa.Text())
    return sa.JSON()


def _json_object_default():
    if _is_postgres():
        return sa.text("'{}'::jsonb")
    return sa.text("'{}'")


def _bool_default(value: bool):
    if _is_postgres():
        return sa.text("true" if value else "false")
    return sa.text("1" if value else "0")


def upgrade() -> None:
    op.add_column("devices", sa.Column("cohort", sa.String(length=128), nullable=True))
    op.add_column(
        "devices",
        sa.Column("labels", _json_type(), nullable=False, server_default=_json_object_default()),
    )

    op.create_table(
        "release_manifests",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("git_tag", sa.String(length=128), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("signature_key_id", sa.String(length=64), nullable=False),
        sa.Column("constraints", _json_type(), nullable=False, server_default=_json_object_default()),
        sa.Column("created_by", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'active'")),
        sa.UniqueConstraint("git_tag", "commit_sha", name="uq_release_manifests_tag_commit"),
    )
    op.create_index(
        "ix_release_manifests_created_at",
        "release_manifests",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_release_manifests_status_created_at",
        "release_manifests",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "deployments",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("manifest_id", sa.String(length=36), sa.ForeignKey("release_manifests.id"), nullable=False),
        sa.Column("strategy", _json_type(), nullable=False, server_default=_json_object_default()),
        sa.Column("stage", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'active'")),
        sa.Column("halt_reason", sa.String(length=1024), nullable=True),
        sa.Column("created_by", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
        sa.Column("failure_rate_threshold", sa.Float(), nullable=False, server_default=sa.text("0.2")),
        sa.Column("no_quorum_timeout_s", sa.Integer(), nullable=False, server_default=sa.text("1800")),
        sa.Column("command_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("power_guard_required", sa.Boolean(), nullable=False, server_default=_bool_default(True)),
        sa.Column("health_timeout_s", sa.Integer(), nullable=False, server_default=sa.text("300")),
        sa.Column("rollback_to_tag", sa.String(length=128), nullable=True),
        sa.Column("target_selector", _json_type(), nullable=False, server_default=_json_object_default()),
    )
    op.create_index(
        "ix_deployments_manifest_created_at",
        "deployments",
        ["manifest_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_deployments_status_updated_at",
        "deployments",
        ["status", "updated_at"],
        unique=False,
    )

    op.create_table(
        "deployment_targets",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("deployment_id", sa.String(length=36), sa.ForeignKey("deployments.id"), nullable=False),
        sa.Column("device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("stage_assigned", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("last_report_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=1024), nullable=True),
        sa.Column("report_details", _json_type(), nullable=False, server_default=_json_object_default()),
        sa.UniqueConstraint("deployment_id", "device_id", name="uq_deployment_targets_deployment_device"),
    )
    op.create_index(
        "ix_deployment_targets_deployment_status",
        "deployment_targets",
        ["deployment_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_deployment_targets_device_last_report_at",
        "deployment_targets",
        ["device_id", "last_report_at"],
        unique=False,
    )

    op.create_table(
        "device_release_state",
        sa.Column("device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), primary_key=True),
        sa.Column("current_tag", sa.String(length=128), nullable=True),
        sa.Column("current_commit", sa.String(length=64), nullable=True),
        sa.Column("last_healthy_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failed_tag", sa.String(length=128), nullable=True),
        sa.Column("rollback_tag", sa.String(length=128), nullable=True),
        sa.Column("last_deployment_id", sa.String(length=36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
    )

    op.create_table(
        "deployment_events",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("deployment_id", sa.String(length=36), sa.ForeignKey("deployments.id"), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=True),
        sa.Column("details", _json_type(), nullable=False, server_default=_json_object_default()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now_default()),
    )
    op.create_index(
        "ix_deployment_events_deployment_created_at",
        "deployment_events",
        ["deployment_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_deployment_events_event_type_created_at",
        "deployment_events",
        ["event_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_deployment_events_event_type_created_at", table_name="deployment_events")
    op.drop_index("ix_deployment_events_deployment_created_at", table_name="deployment_events")
    op.drop_table("deployment_events")

    op.drop_table("device_release_state")

    op.drop_index("ix_deployment_targets_device_last_report_at", table_name="deployment_targets")
    op.drop_index("ix_deployment_targets_deployment_status", table_name="deployment_targets")
    op.drop_table("deployment_targets")

    op.drop_index("ix_deployments_status_updated_at", table_name="deployments")
    op.drop_index("ix_deployments_manifest_created_at", table_name="deployments")
    op.drop_table("deployments")

    op.drop_index("ix_release_manifests_status_created_at", table_name="release_manifests")
    op.drop_index("ix_release_manifests_created_at", table_name="release_manifests")
    op.drop_table("release_manifests")

    op.drop_column("devices", "labels")
    op.drop_column("devices", "cohort")
