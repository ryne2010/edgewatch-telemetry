from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..config import settings
from ..db import db_session, engine


logger = logging.getLogger("edgewatch.retention")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _cutoff_days(days: int) -> datetime:
    return _utc_now() - timedelta(days=max(0, int(days)))


def _dialect() -> str:
    try:
        return engine.dialect.name
    except Exception:
        return "unknown"


def _delete_cte_batched(*, table: str, ts_column: str, cutoff: datetime, batch_size: int) -> int:
    """Delete rows in batches for Postgres using a CTE.

    This avoids a single massive DELETE that can hold locks too long.

    Returns number of rows deleted in this batch.
    """

    sql = text(
        f"""
WITH doomed AS (
  SELECT id FROM {table}
  WHERE {ts_column} < :cutoff
  ORDER BY {ts_column} ASC
  LIMIT :batch_size
)
DELETE FROM {table}
USING doomed
WHERE {table}.id = doomed.id
        """.strip()
    )

    with engine.begin() as conn:
        res = conn.execute(sql, {"cutoff": cutoff, "batch_size": int(batch_size)})
        # SQLAlchemy result.rowcount is best-effort; in Postgres it is reliable.
        return int(res.rowcount or 0)


def _delete_simple(*, table: str, ts_column: str, cutoff: datetime) -> int:
    """Delete rows without batching (fallback for non-Postgres)."""

    sql = text(f"DELETE FROM {table} WHERE {ts_column} < :cutoff")
    with engine.begin() as conn:
        res = conn.execute(sql, {"cutoff": cutoff})
        return int(res.rowcount or 0)


def run_retention() -> None:
    if not settings.retention_enabled:
        logger.info("Retention disabled (RETENTION_ENABLED=false)")
        return

    dry_run = os.getenv("RETENTION_DRY_RUN", "").strip().lower() in {"1", "true", "yes", "y", "on"}

    tel_cutoff = _cutoff_days(settings.telemetry_retention_days)
    q_cutoff = _cutoff_days(settings.quarantine_retention_days)

    batch_size = max(100, int(settings.retention_batch_size))
    max_batches = max(1, int(settings.retention_max_batches))

    dialect = _dialect()
    logger.info(
        "retention_start",
        extra={
            "fields": {
                "dialect": dialect,
                "dry_run": dry_run,
                "telemetry_retention_days": settings.telemetry_retention_days,
                "quarantine_retention_days": settings.quarantine_retention_days,
                "batch_size": batch_size,
                "max_batches": max_batches,
            }
        },
    )

    if dry_run:
        # Best-effort counts.
        with db_session() as session:
            tel = session.execute(
                text("SELECT COUNT(1) FROM telemetry_points WHERE ts < :cutoff"), {"cutoff": tel_cutoff}
            ).scalar_one()
            qt = session.execute(
                text("SELECT COUNT(1) FROM quarantined_telemetry WHERE ts < :cutoff"), {"cutoff": q_cutoff}
            ).scalar_one()
            logger.info(
                "retention_dry_run_counts",
                extra={"fields": {"telemetry_points": int(tel), "quarantined_telemetry": int(qt)}},
            )
        return

    deleted_total = {"telemetry_points": 0, "quarantined_telemetry": 0}

    def _run_table(*, table: str, cutoff: datetime) -> int:
        deleted = 0
        if dialect == "postgresql":
            for _ in range(max_batches):
                n = _delete_cte_batched(table=table, ts_column="ts", cutoff=cutoff, batch_size=batch_size)
                deleted += n
                if n < batch_size:
                    break
        else:
            deleted = _delete_simple(table=table, ts_column="ts", cutoff=cutoff)
        return deleted

    try:
        deleted_total["telemetry_points"] = _run_table(table="telemetry_points", cutoff=tel_cutoff)
        deleted_total["quarantined_telemetry"] = _run_table(table="quarantined_telemetry", cutoff=q_cutoff)
    except SQLAlchemyError:
        logger.exception("retention_failed")
        raise

    logger.info("retention_complete", extra={"fields": deleted_total})


def main() -> None:
    run_retention()


if __name__ == "__main__":
    main()
