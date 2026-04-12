from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.app.auth.principal import Principal
from api.app.db import Base
from api.app.models import Device, TelemetryPoint
from api.app.routes import devices as devices_routes


def _install_db_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "device-summary-routes.db"
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

    monkeypatch.setattr(devices_routes, "db_session", _db_session_override)
    return session_local


def _seed_device_summary_fixture(session_local) -> None:
    now = datetime.now(timezone.utc)
    with session_local() as session:
        session.add(
            Device(
                device_id="baxter-1",
                display_name="baxter-1",
                token_hash="hash",
                token_fingerprint="fingerprint",
                heartbeat_interval_s=300,
                offline_after_s=900,
                enabled=True,
            )
        )
        session.add(
            TelemetryPoint(
                device_id="baxter-1",
                message_id="msg-1",
                ts=now,
                metrics={
                    "water_pressure_psi": 42.5,
                    "battery_v": 12.4,
                    "signal_rssi_dbm": -92,
                },
            )
        )
        session.commit()


def test_list_device_summaries_limits_after_deduping_and_filtering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_local = _install_db_override(tmp_path, monkeypatch)
    _seed_device_summary_fixture(session_local)

    out = devices_routes.list_device_summaries(
        metrics=["water_pressure_psi", "battery_v", "battery_v", "bad-key", "water_pressure_psi"],
        limit_metrics=2,
        principal=Principal(email="admin@example.com", role="admin", source="test"),
    )

    assert len(out) == 1
    assert out[0].metrics == {
        "water_pressure_psi": 42.5,
        "battery_v": 12.4,
    }


def test_list_device_summaries_rejects_unique_metric_count_over_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_local = _install_db_override(tmp_path, monkeypatch)
    _seed_device_summary_fixture(session_local)

    with pytest.raises(HTTPException) as exc:
        devices_routes.list_device_summaries(
            metrics=["water_pressure_psi", "battery_v", "signal_rssi_dbm"],
            limit_metrics=2,
            principal=Principal(email="admin@example.com", role="admin", source="test"),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Too many metrics requested (max 2)"
