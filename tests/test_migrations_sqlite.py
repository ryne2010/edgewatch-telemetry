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
    assert "telemetry_ingest_dedupe" in tables
    assert "telemetry_rollups_hourly" in tables
    assert "device_access_grants" in tables
    assert "device_control_commands" in tables

    admin_columns = {col["name"] for col in inspector.get_columns("admin_events")}
    assert "actor_subject" in admin_columns

    device_columns = {col["name"] for col in inspector.get_columns("devices")}
    assert "operation_mode" in device_columns
    assert "sleep_poll_interval_s" in device_columns
    assert "alerts_muted_until" in device_columns
    assert "alerts_muted_reason" in device_columns

    command_columns = {col["name"] for col in inspector.get_columns("device_control_commands")}
    assert "device_id" in command_columns
    assert "command_payload" in command_columns
    assert "status" in command_columns
    assert "issued_at" in command_columns
    assert "expires_at" in command_columns
    assert "acknowledged_at" in command_columns
    assert "superseded_at" in command_columns
