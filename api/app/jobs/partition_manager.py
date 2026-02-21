from __future__ import annotations

import logging

from ..config import settings
from ..services.telemetry_partitions import ensure_monthly_partitions
from ..services.telemetry_rollups import refresh_recent_hourly_rollups


logger = logging.getLogger("edgewatch.partition_manager")


def run_partition_manager() -> None:
    if not settings.telemetry_partitioning_enabled and not settings.telemetry_rollups_enabled:
        logger.info("partition_manager_disabled")
        return

    created_partitions: list[str] = []
    if settings.telemetry_partitioning_enabled:
        created_partitions = ensure_monthly_partitions(
            months_back=settings.telemetry_partition_lookback_months,
            months_ahead=settings.telemetry_partition_prewarm_months,
        )

    rollup_rows = 0
    if settings.telemetry_rollups_enabled:
        rollup_rows = refresh_recent_hourly_rollups(backfill_hours=settings.telemetry_rollup_backfill_hours)

    logger.info(
        "partition_manager_complete",
        extra={
            "fields": {
                "partitioning_enabled": settings.telemetry_partitioning_enabled,
                "rollups_enabled": settings.telemetry_rollups_enabled,
                "partitions_created": len(created_partitions),
                "partitions_created_names": created_partitions,
                "rollup_rows_upserted": int(rollup_rows),
            }
        },
    )


def main() -> None:
    run_partition_manager()


if __name__ == "__main__":
    main()
