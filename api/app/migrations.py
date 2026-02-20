from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from .config import settings


logger = logging.getLogger("edgewatch.migrations")


# Fixed advisory lock ID to prevent concurrent migrations.
# Any 64-bit integer works; keep it stable for this repo.
_MIGRATION_LOCK_ID = 7352956239587289721


def _alembic_config(database_url: str) -> Config:
    # alembic.ini lives at repo root.
    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))

    # Make sure the script location resolves even when CWD is not repo root.
    cfg.set_main_option("script_location", str(repo_root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def upgrade_head(*, engine: Engine) -> None:
    """Run `alembic upgrade head` with a Postgres advisory lock.

    This is safe to call from multiple processes concurrently: only one will hold the lock.

    Staff-level note:
    - In production you often run migrations as a separate job (Cloud Run Job / CI step).
    - For local dev and small demos, running on startup can be acceptable when locked.
    """

    database_url = settings.database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is empty; cannot run migrations")

    lock_conn = None
    try:
        # Acquire a global advisory lock so only one process migrates at a time.
        # IMPORTANT: session-level advisory locks are held *per connection*.
        # We keep this connection open for the duration of the migration.
        try:
            lock_conn = engine.connect()
            lock_conn.execute(text("SELECT pg_advisory_lock(:id)"), {"id": _MIGRATION_LOCK_ID})
            lock_conn.commit()
            logger.info("acquired migration advisory lock")
        except Exception:
            if lock_conn is not None:
                try:
                    lock_conn.close()
                except Exception:
                    pass
                lock_conn = None
            logger.warning("pg_advisory_lock failed; continuing without lock")

        cfg = _alembic_config(database_url)
        command.upgrade(cfg, "head")
        logger.info("DB migrations applied (head)")

    finally:
        if lock_conn is not None:
            try:
                lock_conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": _MIGRATION_LOCK_ID})
                lock_conn.commit()
            except Exception:
                # Don't fail shutdown on unlock errors.
                pass
            try:
                lock_conn.close()
            except Exception:
                pass


def maybe_run_startup_migrations(*, engine: Engine) -> None:
    if not settings.auto_migrate:
        logger.info("AUTO_MIGRATE disabled")
        return
    logger.info("AUTO_MIGRATE enabled; applying migrations")
    upgrade_head(engine=engine)
