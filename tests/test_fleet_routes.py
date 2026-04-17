from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.app.auth.principal import Principal
from api.app.db import Base
from api.app.models import Device
from api.app.routes import fleets as fleet_routes


def _db_override(tmp_path: Path):
    db_path = tmp_path / "fleet-routes.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    @contextmanager
    def _db_session():
        session = session_local()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return session_local, _db_session


def _seed_device(session_local, device_id: str = "well-301") -> Device:
    with session_local() as session:
        row = Device(
            device_id=device_id,
            display_name=device_id,
            token_hash="hash",
            token_fingerprint=f"fp-{device_id}",
            heartbeat_interval_s=300,
            offline_after_s=900,
            enabled=True,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def test_admin_fleet_create_membership_and_read_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(fleet_routes, "db_session", db_override)
    admin = Principal(email="admin@example.com", role="admin", source="test")
    viewer = Principal(email="viewer@example.com", role="viewer", source="test")
    device = _seed_device(session_local)

    fleet = fleet_routes.create_fleet(
        fleet_routes.FleetCreateIn(
            name="Pilot West", description="Pilot devices", default_ota_channel="pilot"
        ),
        principal=admin,
    )
    assert fleet.name == "Pilot West"
    assert fleet.default_ota_channel == "pilot"

    membership = fleet_routes.add_device_to_fleet(fleet.id, device.device_id, principal=admin)
    assert membership.device_id == device.device_id

    grant = fleet_routes.put_fleet_access_admin(
        fleet.id,
        "viewer@example.com",
        fleet_routes.FleetAccessGrantPutIn(access_role="viewer"),
        principal=admin,
    )
    assert grant.principal_email == "viewer@example.com"

    accessible = fleet_routes.list_accessible_fleets(principal=viewer)
    assert [row.id for row in accessible] == [fleet.id]

    devices = fleet_routes.list_fleet_devices(fleet.id, principal=viewer)
    assert [row.device_id for row in devices] == [device.device_id]
