from __future__ import annotations

import logging

from ..config import settings
from ..db import engine, db_session
from ..migrations import maybe_run_startup_migrations
from ..observability import configure_logging
from ..services.monitor import ensure_offline_alerts


logger = logging.getLogger("edgewatch.job.offline_check")


def main() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    configure_logging(level=level, log_format=settings.log_format)

    # For job runners, it's convenient to ensure schema exists.
    maybe_run_startup_migrations(engine=engine)

    with db_session() as session:
        ensure_offline_alerts(session)

    logger.info("offline_check complete")


if __name__ == "__main__":
    main()
