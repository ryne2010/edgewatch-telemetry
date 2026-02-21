from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from ..db import engine


_NUMERIC_VALUE_RE = r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$"


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def refresh_hourly_rollups(*, since: datetime, until: datetime) -> int:
    """Aggregate numeric metrics into hourly rollups for long-range charting."""
    if engine.dialect.name != "postgresql":
        return 0

    since_utc = _normalize_utc(since)
    until_utc = _normalize_utc(until)
    if since_utc >= until_utc:
        return 0

    sql = text(
        """
WITH agg AS (
  SELECT
    tp.device_id AS device_id,
    kv.key AS metric_key,
    date_trunc('hour', tp.ts) AS bucket_ts,
    COUNT(*)::integer AS sample_count,
    MIN((kv.value)::double precision) AS min_value,
    MAX((kv.value)::double precision) AS max_value,
    AVG((kv.value)::double precision) AS avg_value
  FROM telemetry_points tp
  CROSS JOIN LATERAL jsonb_each_text(tp.metrics) AS kv(key, value)
  WHERE tp.ts >= :since_ts
    AND tp.ts < :until_ts
    AND kv.value ~ :numeric_re
  GROUP BY tp.device_id, kv.key, date_trunc('hour', tp.ts)
)
INSERT INTO telemetry_rollups_hourly (
  device_id,
  metric_key,
  bucket_ts,
  sample_count,
  min_value,
  max_value,
  avg_value,
  updated_at
)
SELECT
  agg.device_id,
  agg.metric_key,
  agg.bucket_ts,
  agg.sample_count,
  agg.min_value,
  agg.max_value,
  agg.avg_value,
  now()
FROM agg
ON CONFLICT (device_id, metric_key, bucket_ts)
DO UPDATE
SET
  sample_count = EXCLUDED.sample_count,
  min_value = EXCLUDED.min_value,
  max_value = EXCLUDED.max_value,
  avg_value = EXCLUDED.avg_value,
  updated_at = now()
        """.strip()
    )

    with engine.begin() as conn:
        result = conn.execute(
            sql,
            {
                "since_ts": since_utc,
                "until_ts": until_utc,
                "numeric_re": _NUMERIC_VALUE_RE,
            },
        )
        return max(0, int(result.rowcount or 0))


def refresh_recent_hourly_rollups(*, backfill_hours: int) -> int:
    now = datetime.now(timezone.utc)
    hours = max(1, int(backfill_hours))
    return refresh_hourly_rollups(since=now - timedelta(hours=hours), until=now + timedelta(hours=1))
