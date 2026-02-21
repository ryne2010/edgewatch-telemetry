from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.app.db import Base
from api.app.models import AdminEvent, Device
from api.app.services.admin_audit import record_admin_event


def test_record_admin_event_persists_actor_email() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    device_table: Any = Device.__table__
    admin_event_table: Any = AdminEvent.__table__
    Base.metadata.create_all(engine, tables=[device_table, admin_event_table])

    with Session(engine) as session:
        record_admin_event(
            session,
            actor_email="operator@example.com",
            action="device.create",
            target_type="device",
            target_device_id=None,
            details={"enabled": True},
            request_id="req-123",
        )
        session.commit()

        row = session.query(AdminEvent).one()
        assert row.actor_email == "operator@example.com"
        assert row.action == "device.create"
        assert row.details == {"enabled": True}
        assert row.request_id == "req-123"
