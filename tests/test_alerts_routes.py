from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.app.auth.principal import Principal
from api.app.db import Base
from api.app.models import Alert, Device
from api.app.routes import alerts as alerts_routes


def _install_db_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "alerts-routes.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    @contextmanager
    def _db_session_override():
        session = session_local()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(alerts_routes, "db_session", _db_session_override)
    return session_local


def _seed_alert_fixture(session_local) -> None:
    now = datetime.now(timezone.utc)
    with session_local() as session:
        session.add_all(
            [
                Device(
                    device_id="pump-west-1",
                    display_name="Pump West 1",
                    token_hash="hash-1",
                    token_fingerprint="fp-1",
                    heartbeat_interval_s=60,
                    offline_after_s=600,
                    enabled=True,
                ),
                Device(
                    device_id="well-east-2",
                    display_name="Well East 2",
                    token_hash="hash-2",
                    token_fingerprint="fp-2",
                    heartbeat_interval_s=60,
                    offline_after_s=600,
                    enabled=True,
                ),
                Alert(
                    id="alert-1",
                    device_id="pump-west-1",
                    alert_type="BATTERY_LOW",
                    severity="warning",
                    message="Battery low at 11.5 V.",
                    created_at=now,
                ),
                Alert(
                    id="alert-2",
                    device_id="well-east-2",
                    alert_type="DEVICE_OFFLINE",
                    severity="critical",
                    message="Telemetry overdue by 15 minutes.",
                    created_at=now - timedelta(minutes=1),
                ),
            ]
        )
        session.commit()


def test_list_alerts_q_matches_device_type_and_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_local = _install_db_override(tmp_path, monkeypatch)
    _seed_alert_fixture(session_local)
    principal = Principal(email="admin@example.com", role="admin", source="test")

    by_device = alerts_routes.list_alerts(
        q="pump", before=None, before_id=None, limit=100, principal=principal
    )
    by_type = alerts_routes.list_alerts(
        q="device_off", before=None, before_id=None, limit=100, principal=principal
    )
    by_message = alerts_routes.list_alerts(
        q="11.5 v", before=None, before_id=None, limit=100, principal=principal
    )

    assert [row.id for row in by_device] == ["alert-1"]
    assert [row.id for row in by_type] == ["alert-2"]
    assert [row.id for row in by_message] == ["alert-1"]


def test_list_alerts_search_alias_is_supported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session_local = _install_db_override(tmp_path, monkeypatch)
    _seed_alert_fixture(session_local)

    rows = alerts_routes.list_alerts(
        search="telemetry overdue",
        q=None,
        before=None,
        before_id=None,
        limit=100,
        principal=Principal(email="admin@example.com", role="admin", source="test"),
    )

    assert [row.id for row in rows] == ["alert-2"]
