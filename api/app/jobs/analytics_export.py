from __future__ import annotations

import logging

from ..config import settings
from ..db import engine, db_session
from ..migrations import maybe_run_startup_migrations
from ..observability import configure_logging
from ..services.analytics_export import run_export_once


logger = logging.getLogger("edgewatch.job.analytics_export")


def main() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    configure_logging(level=level, log_format=settings.log_format)

    maybe_run_startup_migrations(engine=engine)

    with db_session() as session:
        batch = run_export_once(session)

    logger.info(
        "analytics_export_complete",
        extra={
            "fields": {
                "batch_id": batch.id,
                "status": batch.status,
                "row_count": batch.row_count,
                "watermark_from": batch.watermark_from.isoformat() if batch.watermark_from else None,
                "watermark_to": batch.watermark_to.isoformat() if batch.watermark_to else None,
            }
        },
    )

    if batch.status != "success":
        raise RuntimeError("analytics export failed")


if __name__ == "__main__":
    main()
