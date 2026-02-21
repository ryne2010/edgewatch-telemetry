from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..db import engine


_MONTHLY_PARTITION_RE = re.compile(r"^telemetry_points_p(\d{6})$")


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _month_floor_utc(value: datetime) -> datetime:
    ts = _normalize_utc(value)
    return datetime(ts.year, ts.month, 1, tzinfo=timezone.utc)


def _add_months(value: datetime, months: int) -> datetime:
    base = _month_floor_utc(value)
    idx = (base.year * 12 + (base.month - 1)) + int(months)
    year, month_idx = divmod(idx, 12)
    return datetime(year, month_idx + 1, 1, tzinfo=timezone.utc)


def _partition_name(month_start: datetime) -> str:
    month_start = _month_floor_utc(month_start)
    return f"telemetry_points_p{month_start.year:04d}{month_start.month:02d}"


def _is_postgres() -> bool:
    return engine.dialect.name == "postgresql"


def _is_partitioned(conn: Connection) -> bool:
    row = conn.execute(
        text(
            """
SELECT EXISTS (
  SELECT 1
  FROM pg_partitioned_table pt
  JOIN pg_class c ON c.oid = pt.partrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = current_schema()
    AND c.relname = 'telemetry_points'
)
            """.strip()
        )
    ).scalar_one()
    return bool(row)


def _list_partition_tables(conn: Connection) -> list[str]:
    rows = conn.execute(
        text(
            """
SELECT child.relname
FROM pg_inherits i
JOIN pg_class parent ON parent.oid = i.inhparent
JOIN pg_namespace ns ON ns.oid = parent.relnamespace
JOIN pg_class child ON child.oid = i.inhrelid
WHERE ns.nspname = current_schema()
  AND parent.relname = 'telemetry_points'
ORDER BY child.relname
            """.strip()
        )
    ).all()
    return [str(r[0]) for r in rows]


def ensure_monthly_partitions(*, months_back: int, months_ahead: int) -> list[str]:
    """Create missing monthly telemetry partitions around the current month."""
    if not _is_postgres():
        return []

    created: list[str] = []
    now = datetime.now(timezone.utc)
    months_back = max(0, int(months_back))
    months_ahead = max(0, int(months_ahead))
    anchor = _month_floor_utc(now)

    with engine.begin() as conn:
        if not _is_partitioned(conn):
            return []

        existing = set(_list_partition_tables(conn))

        for offset in range(-months_back, months_ahead + 1):
            month_start = _add_months(anchor, offset)
            month_end = _add_months(month_start, 1)
            part_name = _partition_name(month_start)
            if part_name in existing:
                continue

            conn.execute(
                text(
                    f"""
CREATE TABLE IF NOT EXISTS "{part_name}"
PARTITION OF telemetry_points
FOR VALUES FROM (:start_ts) TO (:end_ts)
                    """.strip()
                ),
                {"start_ts": month_start, "end_ts": month_end},
            )
            created.append(part_name)

        conn.execute(
            text(
                """
CREATE TABLE IF NOT EXISTS telemetry_points_default
PARTITION OF telemetry_points
DEFAULT
                """.strip()
            )
        )

    return created


def drop_expired_monthly_partitions(*, cutoff: datetime) -> list[str]:
    """Drop whole monthly partitions when their upper bound is older than cutoff."""
    if not _is_postgres():
        return []

    cutoff_utc = _normalize_utc(cutoff)
    dropped: list[str] = []

    with engine.begin() as conn:
        if not _is_partitioned(conn):
            return []

        for partition_name in _list_partition_tables(conn):
            match = _MONTHLY_PARTITION_RE.fullmatch(partition_name)
            if not match:
                continue

            ym = match.group(1)
            month_start = datetime(int(ym[:4]), int(ym[4:]), 1, tzinfo=timezone.utc)
            month_end = _add_months(month_start, 1)
            if month_end > cutoff_utc:
                continue

            conn.execute(text(f'DROP TABLE IF EXISTS "{partition_name}"'))
            dropped.append(partition_name)

    return dropped
