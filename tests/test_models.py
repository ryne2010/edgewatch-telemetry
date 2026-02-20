from __future__ import annotations

from typing import Any

from sqlalchemy import UniqueConstraint

from api.app.models import TelemetryPoint


def test_telemetry_message_id_is_unique_per_device() -> None:
    # We enforce idempotency per-device, not globally.
    # SQLAlchemy's typing for __table__ is broad; cast to Any to keep Pyright happy.
    table: Any = TelemetryPoint.__table__
    uqs = [c for c in table.constraints if isinstance(c, UniqueConstraint)]
    assert any(set(c.columns.keys()) == {"device_id", "message_id"} for c in uqs), (
        "Expected unique constraint on (device_id, message_id)"
    )
