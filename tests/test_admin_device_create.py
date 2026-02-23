from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.app.auth.principal import Principal
from api.app.db import Base
from api.app.models import Device
from api.app.routes import admin as admin_routes
from api.app.schemas import AdminDeviceCreate


def test_create_device_defaults_display_name_to_device_id_when_missing(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "admin-create-device.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    @contextmanager
    def _db_session_override():
        session = SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(admin_routes, "db_session", _db_session_override)

    payload = AdminDeviceCreate.model_validate(
        {
            "device_id": "well-101",
            "token": "9bc8be9f1e8a4f6fb9e0a66f04b15faa",
            "heartbeat_interval_s": 300,
            "offline_after_s": 900,
        }
    )

    out = admin_routes.create_device(
        payload,
        principal=Principal(email="admin@example.com", role="admin", source="test"),
    )

    assert out.device_id == "well-101"
    assert out.display_name == "well-101"

    with SessionLocal() as session:
        row = session.query(Device).filter(Device.device_id == "well-101").one()
        assert row.display_name == "well-101"
