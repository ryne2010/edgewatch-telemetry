from __future__ import annotations

from datetime import datetime, timezone

from api.app.services.telemetry_partitions import (
    _add_months,
    _month_floor_utc,
    drop_expired_monthly_partitions,
    ensure_monthly_partitions,
)
from api.app.services.telemetry_rollups import refresh_hourly_rollups


def test_month_helpers_roll_over_year_boundaries() -> None:
    start = datetime(2026, 1, 15, 3, 30, tzinfo=timezone.utc)
    floored = _month_floor_utc(start)
    assert floored == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert _add_months(floored, -2) == datetime(2025, 11, 1, 0, 0, tzinfo=timezone.utc)
    assert _add_months(floored, 13) == datetime(2027, 2, 1, 0, 0, tzinfo=timezone.utc)


def test_partition_and_rollup_services_are_noop_off_postgres() -> None:
    # Unit tests run against sqlite in harness; these helpers should be safe no-ops.
    cutoff = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)
    assert ensure_monthly_partitions(months_back=1, months_ahead=2) == []
    assert drop_expired_monthly_partitions(cutoff=cutoff) == []
    assert refresh_hourly_rollups(since=cutoff, until=cutoff) == 0
