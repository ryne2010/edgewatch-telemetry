from __future__ import annotations

import logging

from ..config import settings
from ..db import engine
from ..migrations import upgrade_head
from ..observability import configure_logging


logger = logging.getLogger("edgewatch.job.migrate")


def main() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    configure_logging(level=level, log_format=settings.log_format)

    upgrade_head(engine=engine)

    logger.info("migrate complete")


if __name__ == "__main__":
    main()
