from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_head_supports_sqlite(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "edgewatch.sqlite3"
    database_url = f"sqlite+pysqlite:///{db_path}"
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", database_url)

    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")

    inspector = inspect(create_engine(database_url))
    tables = set(inspector.get_table_names())

    assert "devices" in tables
    assert "telemetry_points" in tables
    assert "ingestion_batches" in tables
    assert "notification_events" in tables
    assert "media_objects" in tables
    assert "admin_events" in tables

    admin_columns = {col["name"] for col in inspector.get_columns("admin_events")}
    assert "actor_subject" in admin_columns
