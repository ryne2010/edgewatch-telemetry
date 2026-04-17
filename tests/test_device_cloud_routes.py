from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.app.auth.principal import Principal
from api.app.db import Base
from api.app.models import Device
from api.app.routes import device_cloud as device_cloud_routes
from api.app.routes import device_policy as device_policy_routes
from api.app.schemas import (
    DeviceEventIn,
    DeviceProcedureDefinitionCreateIn,
    DeviceProcedureInvokeIn,
    DeviceProcedureResultIn,
    DeviceReportedStateIn,
)


def _db_override(tmp_path: Path):
    db_path = tmp_path / "device-cloud-routes.db"
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


def _seed_device(session_local, device_id: str = "well-101") -> Device:
    with session_local() as session:
        device = Device(
            device_id=device_id,
            display_name=device_id,
            token_hash="hash",
            token_fingerprint=f"fp-{device_id}",
            heartbeat_interval_s=300,
            offline_after_s=900,
            enabled=True,
        )
        session.add(device)
        session.commit()
        session.refresh(device)
        return device


def _request():
    class _Req:
        headers: dict[str, str] = {}

    return _Req()


def test_procedure_definition_invoke_policy_and_result_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(device_cloud_routes, "db_session", db_override)
    monkeypatch.setattr(device_policy_routes, "db_session", db_override)
    device = _seed_device(session_local)

    admin = Principal(email="admin@example.com", role="admin", source="test")
    operator = Principal(email="operator@example.com", role="operator", source="test")

    definition = device_cloud_routes.create_device_procedure_definition(
        DeviceProcedureDefinitionCreateIn(
            name="capture_snapshot",
            description="Capture a diagnostic image",
            request_schema={"type": "object", "properties": {"camera_id": {"type": "string"}}},
            response_schema={"type": "object"},
            timeout_s=120,
            enabled=True,
        ),
        principal=admin,
    )
    assert definition.name == "capture_snapshot"

    invocation = device_cloud_routes.invoke_device_procedure(
        device_id=device.device_id,
        definition_name="capture_snapshot",
        req=DeviceProcedureInvokeIn(request_payload={"camera_id": "cam1"}, ttl_s=600),
        principal=operator,
    )
    assert invocation.status == "queued"
    assert invocation.definition_name == "capture_snapshot"

    resp = Response()
    policy = cast(Any, device_policy_routes.get_device_policy(cast(Any, _request()), resp, device))
    assert policy.pending_procedure_invocation is not None
    assert policy.pending_procedure_invocation.id == invocation.id
    assert policy.pending_procedure_invocation.definition_name == "capture_snapshot"

    completed = device_cloud_routes.complete_device_procedure_invocation(
        invocation_id=invocation.id,
        req=DeviceProcedureResultIn(
            status="succeeded",
            result_payload={"path": "/tmp/image.jpg"},
            reason_code=None,
            reason_detail=None,
        ),
        device=device,
    )
    assert completed.status == "succeeded"
    assert completed.result_payload == {"path": "/tmp/image.jpg"}

    listed = device_cloud_routes.list_device_procedure_invocations(
        device_id=device.device_id,
        limit=20,
        principal=operator,
    )
    assert [row.id for row in listed] == [invocation.id]
    assert listed[0].status == "succeeded"


def test_device_state_and_events_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(device_cloud_routes, "db_session", db_override)
    device = _seed_device(session_local, device_id="well-202")
    viewer = Principal(email="viewer@example.com", role="viewer", source="test")

    state_rows = device_cloud_routes.report_device_state(
        DeviceReportedStateIn(
            state={"pump_enabled": True, "firmware_channel": "pilot"},
            schema_types={"pump_enabled": "bool", "firmware_channel": "string"},
        ),
        device=device,
    )
    assert {row.key for row in state_rows} == {"pump_enabled", "firmware_channel"}

    fetched_state = device_cloud_routes.get_device_reported_state(
        device_id=device.device_id, principal=viewer
    )
    assert {row.key for row in fetched_state} == {"firmware_channel", "pump_enabled"}

    event = device_cloud_routes.publish_device_event(
        DeviceEventIn(
            event_type="procedure.capture_snapshot.requested",
            severity="info",
            body={"camera_id": "cam2"},
            source="device",
        ),
        device=device,
    )
    assert event.device_id == device.device_id
    assert event.event_type == "procedure.capture_snapshot.requested"

    events = device_cloud_routes.list_device_events(
        device_id=device.device_id,
        event_type="procedure.capture_snapshot.requested",
        limit=20,
        principal=viewer,
    )
    assert [row.id for row in events] == [event.id]
