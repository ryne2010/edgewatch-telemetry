from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Alembic Config object, which provides access to values within the .ini file.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Ensure the repo root is on sys.path when invoked from odd working dirs.
# This lets `api.app.*` imports resolve.
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from api.app.db import Base  # noqa: E402
import api.app.models  # noqa: F401,E402  (register models)


target_metadata = Base.metadata


def _get_database_url() -> str:
    # Primary: env var (works in containers + CI)
    url = os.getenv("DATABASE_URL")
    if url and url.strip():
        return url.strip()

    # Secondary: alembic.ini placeholder.
    url = config.get_main_option("sqlalchemy.url")
    if url and url.strip():
        return url.strip()

    raise RuntimeError("DATABASE_URL is not set. Provide DATABASE_URL or set sqlalchemy.url in alembic.ini")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""

    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _get_database_url()

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
