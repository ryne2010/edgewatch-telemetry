from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from api.app.db import Base
from api.app.models import Alert, AlertPolicy, Device, NotificationDestination, NotificationEvent
from api.app.services.notifications import process_alert_notification


def _settings(**overrides: Any) -> SimpleNamespace:
    state = {
        "alert_webhook_url": "",
        "alert_webhook_kind": "generic",
        "alert_webhook_timeout_s": 1.0,
        "alert_dedupe_window_s": 900,
        "alert_throttle_window_s": 3600,
        "alert_throttle_max_notifications": 20,
        "alert_quiet_hours_start": "22:00",
        "alert_quiet_hours_end": "06:00",
        "alert_quiet_hours_tz": "UTC",
    }
    state.update(overrides)
    return SimpleNamespace(**state)


def _create_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    device_table: Any = Device.__table__
    alert_table: Any = Alert.__table__
    alert_policy_table: Any = AlertPolicy.__table__
    notification_event_table: Any = NotificationEvent.__table__
    notification_destination_table: Any = NotificationDestination.__table__
    Base.metadata.create_all(
        engine,
        tables=[
            device_table,
            alert_table,
            alert_policy_table,
            notification_event_table,
            notification_destination_table,
        ],
    )
    return Session(engine)


def _seed_alert(session: Session) -> Alert:
    session.add(
        Device(
            device_id="demo-well-001",
            display_name="Demo Well 001",
            token_hash="hash",
            token_fingerprint="fp",
            heartbeat_interval_s=300,
            offline_after_s=900,
            enabled=True,
        )
    )
    alert = Alert(
        device_id="demo-well-001",
        alert_type="WATER_PRESSURE_LOW",
        severity="warning",
        message="Water pressure low",
        created_at=datetime.now(timezone.utc),
    )
    session.add(alert)
    session.flush()
    return alert


def test_process_alert_notification_records_suppressed_no_adapter(monkeypatch) -> None:
    fake_settings = _settings(alert_webhook_url="")
    monkeypatch.setattr("api.app.services.notifications.settings", fake_settings)
    monkeypatch.setattr("api.app.services.routing.settings", fake_settings)

    with _create_session() as session:
        alert = _seed_alert(session)
        process_alert_notification(session, alert, now=datetime.now(timezone.utc))
        session.commit()

        rows = session.query(NotificationEvent).all()
        assert len(rows) == 1
        assert rows[0].decision == "suppressed_no_adapter"
        assert rows[0].reason == "no notification adapter configured"
        assert rows[0].delivered is False


def test_process_alert_notification_delivers_to_all_enabled_destinations(monkeypatch) -> None:
    fake_settings = _settings(alert_webhook_url="")
    monkeypatch.setattr("api.app.services.notifications.settings", fake_settings)
    monkeypatch.setattr("api.app.services.routing.settings", fake_settings)

    calls: list[str] = []

    def _fake_post(url: str, json: dict[str, Any], timeout: float) -> SimpleNamespace:  # noqa: ARG001
        calls.append(url)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr("api.app.services.notifications.requests.post", _fake_post)

    with _create_session() as session:
        alert = _seed_alert(session)
        session.add(
            NotificationDestination(
                name="primary",
                channel="webhook",
                kind="generic",
                webhook_url="https://hooks.example.com/primary",
                enabled=True,
            )
        )
        session.add(
            NotificationDestination(
                name="secondary",
                channel="webhook",
                kind="discord",
                webhook_url="https://hooks.example.com/secondary",
                enabled=True,
            )
        )
        session.add(
            NotificationDestination(
                name="telegram",
                channel="webhook",
                kind="telegram",
                webhook_url="https://api.telegram.org/botTOKEN/sendMessage?chat_id=12345",
                enabled=True,
            )
        )
        session.flush()

        process_alert_notification(session, alert, now=datetime.now(timezone.utc))
        session.commit()

        assert sorted(calls) == [
            "https://api.telegram.org/botTOKEN/sendMessage?chat_id=12345",
            "https://hooks.example.com/primary",
            "https://hooks.example.com/secondary",
        ]

        rows = session.query(NotificationEvent).order_by(NotificationEvent.created_at.asc()).all()
        assert len(rows) == 3
        assert all(r.decision == "delivered" for r in rows)
        assert all(r.delivered is True for r in rows)
        assert all(r.destination_fingerprint for r in rows)


def test_process_alert_notification_telegram_requires_chat_id(monkeypatch) -> None:
    fake_settings = _settings(alert_webhook_url="")
    monkeypatch.setattr("api.app.services.notifications.settings", fake_settings)
    monkeypatch.setattr("api.app.services.routing.settings", fake_settings)

    calls: list[str] = []

    def _fake_post(url: str, json: dict[str, Any], timeout: float) -> SimpleNamespace:  # noqa: ARG001
        calls.append(url)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr("api.app.services.notifications.requests.post", _fake_post)

    with _create_session() as session:
        alert = _seed_alert(session)
        session.add(
            NotificationDestination(
                name="telegram-bad",
                channel="webhook",
                kind="telegram",
                webhook_url="https://api.telegram.org/botTOKEN/sendMessage",
                enabled=True,
            )
        )
        session.flush()

        process_alert_notification(session, alert, now=datetime.now(timezone.utc))
        session.commit()

        assert calls == []
        rows = session.query(NotificationEvent).all()
        assert len(rows) == 1
        assert rows[0].decision == "delivery_failed"
        assert rows[0].reason == "telegram chat_id missing in webhook URL query"
        assert rows[0].error_class == "MISSING_CHAT_ID"
        assert rows[0].delivered is False


def test_process_alert_notification_uses_env_fallback_when_db_destinations_missing(monkeypatch) -> None:
    fake_settings = _settings(alert_webhook_url="https://hooks.example.com/env-default")
    monkeypatch.setattr("api.app.services.notifications.settings", fake_settings)
    monkeypatch.setattr("api.app.services.routing.settings", fake_settings)

    calls: list[str] = []

    def _fake_post(url: str, json: dict[str, Any], timeout: float) -> SimpleNamespace:  # noqa: ARG001
        calls.append(url)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr("api.app.services.notifications.requests.post", _fake_post)

    with _create_session() as session:
        alert = _seed_alert(session)
        process_alert_notification(session, alert, now=datetime.now(timezone.utc))
        session.commit()

        assert calls == ["https://hooks.example.com/env-default"]

        rows = session.query(NotificationEvent).all()
        assert len(rows) == 1
        assert rows[0].decision == "delivered"
        assert rows[0].delivered is True
