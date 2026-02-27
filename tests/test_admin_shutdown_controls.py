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
from api.app.routes import admin as admin_routes
from api.app.schemas import AdminDeviceShutdownIn


def _db_override(tmp_path: Path):
    db_path = tmp_path / "admin-shutdown-controls.db"
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


def _seed_device(session_local, *, device_id: str) -> None:
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


def test_admin_shutdown_command_enqueues_pending_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(admin_routes, "db_session", db_override)
    _seed_device(session_local, device_id="well-900")

    out = admin_routes.shutdown_device_admin(
        device_id="well-900",
        req=AdminDeviceShutdownIn(reason="seasonal intermission", shutdown_grace_s=45),
        principal=Principal(email="admin@example.com", role="admin", source="test"),
    )
    assert out.device_id == "well-900"
    assert out.operation_mode == "disabled"
    assert out.pending_command_count == 1
    assert out.latest_pending_shutdown_requested is True
    assert out.latest_pending_shutdown_grace_s == 45
    assert out.latest_pending_operation_mode == "disabled"

    with session_local() as session:
        command = (
            session.query(DeviceControlCommand)
            .filter(
                DeviceControlCommand.device_id == "well-900",
                DeviceControlCommand.status == "pending",
            )
            .one()
        )
        payload = command.command_payload
        assert payload["operation_mode"] == "disabled"
        assert payload["shutdown_requested"] is True
        assert payload["shutdown_grace_s"] == 45
        assert payload["shutdown_reason"] == "seasonal intermission"


def test_admin_shutdown_respects_policy_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        admin_routes,
        "load_edge_policy",
        lambda _version: SimpleNamespace(
            operation_defaults=SimpleNamespace(
                admin_remote_shutdown_enabled=False,
                shutdown_grace_s_default=30,
                control_command_ttl_s=180 * 24 * 3600,
                disable_requires_manual_restart=True,
            )
        ),
    )

    with pytest.raises(HTTPException) as err:
        admin_routes.shutdown_device_admin(
            device_id="well-901",
            req=AdminDeviceShutdownIn(reason="maintenance window", shutdown_grace_s=30),
            principal=Principal(email="admin@example.com", role="admin", source="test"),
        )
    assert err.value.status_code == 409
