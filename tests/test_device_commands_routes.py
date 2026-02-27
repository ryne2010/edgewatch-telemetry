from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.app.auth.principal import Principal
from api.app.db import Base
from api.app.models import Device, DeviceControlCommand
from api.app.routes import device_commands as device_commands_routes
from api.app.routes import device_controls as device_controls_routes
from api.app.schemas import DeviceOperationControlUpdateIn


def _db_override(tmp_path: Path):
    db_path = tmp_path / "device-controls-routes.db"
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


def _seed_device(session_local, *, device_id: str) -> Device:
    with session_local() as session:
        row = Device(
            device_id=device_id,
            display_name=device_id,
            token_hash="hash",
            token_fingerprint=f"fp-{device_id}",
            heartbeat_interval_s=600,
            offline_after_s=1800,
            enabled=True,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def test_operation_controls_enqueue_and_supersede_pending_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(device_controls_routes, "db_session", db_override)
    monkeypatch.setattr("api.app.services.device_access.settings", SimpleNamespace(authz_enabled=False))

    principal = Principal(email="owner@example.com", role="viewer", source="test")
    _seed_device(session_local, device_id="well-001")

    out1 = device_controls_routes.update_device_operation_controls(
        device_id="well-001",
        req=DeviceOperationControlUpdateIn(operation_mode="sleep", sleep_poll_interval_s=3600),
        principal=principal,
    )
    assert out1.operation_mode == "sleep"
    assert out1.pending_command_count == 1
    assert out1.latest_pending_command_expires_at is not None
    assert out1.latest_pending_operation_mode == "sleep"
    assert out1.latest_pending_shutdown_requested is False

    out2 = device_controls_routes.update_device_operation_controls(
        device_id="well-001",
        req=DeviceOperationControlUpdateIn(operation_mode="active", sleep_poll_interval_s=None),
        principal=principal,
    )
    assert out2.operation_mode == "active"
    assert out2.pending_command_count == 1
    assert out2.latest_pending_operation_mode == "active"
    assert out2.latest_pending_shutdown_requested is False

    with session_local() as session:
        rows = (
            session.query(DeviceControlCommand)
            .filter(DeviceControlCommand.device_id == "well-001")
            .order_by(DeviceControlCommand.issued_at.asc())
            .all()
        )
        assert len(rows) == 2
        assert rows[0].status == "superseded"
        assert rows[0].superseded_at is not None
        assert rows[1].status == "pending"


def test_get_controls_reports_pending_command_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(device_controls_routes, "db_session", db_override)
    monkeypatch.setattr("api.app.services.device_access.settings", SimpleNamespace(authz_enabled=False))

    principal = Principal(email="owner@example.com", role="viewer", source="test")
    _seed_device(session_local, device_id="well-002")

    initial = device_controls_routes.get_device_controls(device_id="well-002", principal=principal)
    assert initial.pending_command_count == 0
    assert initial.latest_pending_command_expires_at is None
    assert initial.latest_pending_operation_mode is None

    device_controls_routes.update_device_operation_controls(
        device_id="well-002",
        req=DeviceOperationControlUpdateIn(operation_mode="sleep", sleep_poll_interval_s=7200),
        principal=principal,
    )
    after = device_controls_routes.get_device_controls(device_id="well-002", principal=principal)
    assert after.pending_command_count == 1
    assert after.latest_pending_command_expires_at is not None
    assert after.latest_pending_operation_mode == "sleep"


def test_device_command_ack_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(device_controls_routes, "db_session", db_override)
    monkeypatch.setattr(device_commands_routes, "db_session", db_override)
    monkeypatch.setattr("api.app.services.device_access.settings", SimpleNamespace(authz_enabled=False))

    principal = Principal(email="owner@example.com", role="viewer", source="test")
    _seed_device(session_local, device_id="well-003")

    device_controls_routes.update_device_operation_controls(
        device_id="well-003",
        req=DeviceOperationControlUpdateIn(operation_mode="disabled", sleep_poll_interval_s=None),
        principal=principal,
    )

    with session_local() as session:
        pending = (
            session.query(DeviceControlCommand)
            .filter(
                DeviceControlCommand.device_id == "well-003",
                DeviceControlCommand.status == "pending",
            )
            .one()
        )
        command_id = pending.id
        device = session.query(Device).filter(Device.device_id == "well-003").one()

    ack1 = device_commands_routes.ack_command(command_id=command_id, device=device)
    ack2 = device_commands_routes.ack_command(command_id=command_id, device=device)
    assert ack1.status == "acknowledged"
    assert ack2.status == "acknowledged"
    assert ack2.acknowledged_at is not None

    with pytest.raises(HTTPException) as err:
        device_commands_routes.ack_command(command_id="missing", device=device)
    assert err.value.status_code == 404
