"""Telemetry partitioning + hourly rollups scale path.

Revision ID: 0010_telemetry_partition_rollups
Revises: 0009_admin_events_actor_subject
Create Date: 2026-02-21

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0010_telemetry_partition_rollups"
down_revision = "0009_admin_events_actor_subject"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _now_default():
    if _is_postgres():
        return sa.text("now()")
    return sa.text("CURRENT_TIMESTAMP")


def _create_dedupe_table() -> None:
    op.create_table(
        "telemetry_ingest_dedupe",
        sa.Column("device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("point_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_now_default(),
        ),
        sa.PrimaryKeyConstraint("device_id", "message_id", name="pk_telemetry_ingest_dedupe"),
    )
    op.create_index(
        "ix_telemetry_ingest_dedupe_point_ts",
        "telemetry_ingest_dedupe",
        ["point_ts"],
        unique=False,
    )

    if _is_postgres():
        op.execute(
            """
INSERT INTO telemetry_ingest_dedupe (device_id, message_id, point_ts, created_at)
SELECT device_id, message_id, ts, created_at
FROM telemetry_points
ON CONFLICT (device_id, message_id) DO NOTHING
            """.strip()
        )
    else:
        op.execute(
            """
INSERT OR IGNORE INTO telemetry_ingest_dedupe (device_id, message_id, point_ts, created_at)
SELECT device_id, message_id, ts, created_at
FROM telemetry_points
            """.strip()
        )


def _create_rollups_table() -> None:
    op.create_table(
        "telemetry_rollups_hourly",
        sa.Column("device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("metric_key", sa.String(length=64), nullable=False),
        sa.Column("bucket_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("min_value", sa.Float(), nullable=False),
        sa.Column("max_value", sa.Float(), nullable=False),
        sa.Column("avg_value", sa.Float(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_now_default(),
        ),
        sa.PrimaryKeyConstraint(
            "device_id",
            "metric_key",
            "bucket_ts",
            name="pk_telemetry_rollups_hourly",
        ),
    )
    op.create_index(
        "ix_telemetry_rollups_hourly_bucket_ts",
        "telemetry_rollups_hourly",
        ["bucket_ts"],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_rollups_hourly_metric_bucket",
        "telemetry_rollups_hourly",
        ["metric_key", "bucket_ts"],
        unique=False,
    )


def _upgrade_postgres_partitioned_telemetry() -> None:
    op.execute("ALTER TABLE telemetry_points RENAME TO telemetry_points_unpartitioned")

    op.execute(
        """
CREATE TABLE telemetry_points (
  id VARCHAR(36) NOT NULL,
  message_id VARCHAR(64) NOT NULL,
  device_id VARCHAR(128) NOT NULL REFERENCES devices(device_id),
  batch_id VARCHAR(36) NULL REFERENCES ingestion_batches(id),
  ts TIMESTAMPTZ NOT NULL,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (id, ts)
)
PARTITION BY RANGE (ts)
        """.strip()
    )

    op.execute(
        """
DO $$
DECLARE
  start_month TIMESTAMPTZ;
  end_month TIMESTAMPTZ;
  part_name TEXT;
BEGIN
  SELECT date_trunc('month', min(ts)) INTO start_month FROM telemetry_points_unpartitioned;
  IF start_month IS NULL THEN
    start_month := date_trunc('month', now());
  END IF;

  SELECT date_trunc('month', max(ts)) + interval '2 month' INTO end_month FROM telemetry_points_unpartitioned;
  IF end_month IS NULL OR end_month <= start_month THEN
    end_month := start_month + interval '2 month';
  END IF;

  WHILE start_month < end_month LOOP
    part_name := format('telemetry_points_p%s', to_char(start_month AT TIME ZONE 'UTC', 'YYYYMM'));
    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS %I PARTITION OF telemetry_points FOR VALUES FROM (%L) TO (%L)',
      part_name,
      start_month,
      start_month + interval '1 month'
    );
    start_month := start_month + interval '1 month';
  END LOOP;
END $$;
        """.strip()
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS telemetry_points_default
PARTITION OF telemetry_points
DEFAULT
        """.strip()
    )

    op.execute(
        """
INSERT INTO telemetry_points (id, message_id, device_id, batch_id, ts, metrics, created_at)
SELECT id, message_id, device_id, batch_id, ts, metrics, created_at
FROM telemetry_points_unpartitioned
ORDER BY ts
        """.strip()
    )

    op.execute("DROP TABLE telemetry_points_unpartitioned")

    op.create_index("ix_telemetry_device_ts", "telemetry_points", ["device_id", "ts"], unique=False)
    op.create_index("ix_telemetry_batch_id", "telemetry_points", ["batch_id"], unique=False)
    op.create_index("ix_telemetry_ts", "telemetry_points", ["ts"], unique=False)


def upgrade() -> None:
    _create_dedupe_table()
    _create_rollups_table()
    if _is_postgres():
        _upgrade_postgres_partitioned_telemetry()


def _downgrade_postgres_partitioned_telemetry() -> None:
    op.execute("ALTER TABLE telemetry_points RENAME TO telemetry_points_partitioned")

    op.create_table(
        "telemetry_points",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("device_id", sa.String(length=128), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("batch_id", sa.String(length=36), sa.ForeignKey("ingestion_batches.id"), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metrics",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("device_id", "message_id", name="uq_telemetry_device_message_id"),
    )
    op.create_index("ix_telemetry_device_ts", "telemetry_points", ["device_id", "ts"], unique=False)
    op.create_index("ix_telemetry_batch_id", "telemetry_points", ["batch_id"], unique=False)
    op.create_index("ix_telemetry_ts", "telemetry_points", ["ts"], unique=False)

    op.execute(
        """
INSERT INTO telemetry_points (id, message_id, device_id, batch_id, ts, metrics, created_at)
SELECT id, message_id, device_id, batch_id, ts, metrics, created_at
FROM telemetry_points_partitioned
ORDER BY ts
ON CONFLICT (device_id, message_id) DO NOTHING
        """.strip()
    )

    op.execute("DROP TABLE telemetry_points_partitioned CASCADE")


def downgrade() -> None:
    if _is_postgres():
        _downgrade_postgres_partitioned_telemetry()

    op.drop_index("ix_telemetry_rollups_hourly_metric_bucket", table_name="telemetry_rollups_hourly")
    op.drop_index("ix_telemetry_rollups_hourly_bucket_ts", table_name="telemetry_rollups_hourly")
    op.drop_table("telemetry_rollups_hourly")

    op.drop_index("ix_telemetry_ingest_dedupe_point_ts", table_name="telemetry_ingest_dedupe")
    op.drop_table("telemetry_ingest_dedupe")
