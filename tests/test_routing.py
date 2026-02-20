from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from api.app.services.routing import AlertCandidate, AlertRouter, RoutingPolicy, in_quiet_hours


class _FakeQuery:
    def __init__(self, *, first_result: object | None = None, scalar_result: int = 0) -> None:
        self._first_result = first_result
        self._scalar_result = scalar_result

    def filter(self, *_args: object, **_kwargs: object) -> "_FakeQuery":
        return self

    def order_by(self, *_args: object, **_kwargs: object) -> "_FakeQuery":
        return self

    def first(self) -> object | None:
        return self._first_result

    def scalar(self) -> int:
        return self._scalar_result


class _FakeSession:
    def __init__(self, *, dedupe_exists: bool = False, sent_count: int = 0) -> None:
        self._dedupe_exists = dedupe_exists
        self._sent_count = sent_count

    def query(self, *_args: object, **_kwargs: object) -> _FakeQuery:
        return _FakeQuery(
            first_result=("event",) if self._dedupe_exists else None,
            scalar_result=self._sent_count,
        )


def _candidate() -> AlertCandidate:
    return AlertCandidate(
        alert_id="a-1",
        device_id="dev-1",
        alert_type="DEVICE_OFFLINE",
        severity="warning",
        message="offline",
    )


def test_in_quiet_hours_handles_cross_midnight_window() -> None:
    assert (
        in_quiet_hours(
            now=datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc),
            start_minute=22 * 60,
            end_minute=6 * 60,
            tz_name="UTC",
        )
        is True
    )
    assert (
        in_quiet_hours(
            now=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            start_minute=22 * 60,
            end_minute=6 * 60,
            tz_name="UTC",
        )
        is False
    )


def test_router_suppresses_quiet_hours(monkeypatch) -> None:
    router = AlertRouter()
    monkeypatch.setattr(
        router,
        "_load_policy",
        lambda _session, _device_id: RoutingPolicy(
            dedupe_window_s=0,
            throttle_window_s=0,
            throttle_max_notifications=0,
            quiet_hours_start_minute=22 * 60,
            quiet_hours_end_minute=6 * 60,
            quiet_hours_tz="UTC",
            enabled=True,
        ),
    )

    decision = router.should_notify(
        cast(Any, _FakeSession()),
        _candidate(),
        now=datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc),
    )

    assert decision.should_notify is False
    assert decision.decision == "suppressed_quiet_hours"


def test_router_suppresses_dedupe_window(monkeypatch) -> None:
    router = AlertRouter()
    monkeypatch.setattr(
        router,
        "_load_policy",
        lambda _session, _device_id: RoutingPolicy(
            dedupe_window_s=900,
            throttle_window_s=3600,
            throttle_max_notifications=20,
            quiet_hours_start_minute=None,
            quiet_hours_end_minute=None,
            quiet_hours_tz="UTC",
            enabled=True,
        ),
    )

    decision = router.should_notify(
        cast(Any, _FakeSession(dedupe_exists=True)),
        _candidate(),
        now=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )

    assert decision.should_notify is False
    assert decision.decision == "suppressed_dedupe"


def test_router_suppresses_throttle(monkeypatch) -> None:
    router = AlertRouter()
    monkeypatch.setattr(
        router,
        "_load_policy",
        lambda _session, _device_id: RoutingPolicy(
            dedupe_window_s=0,
            throttle_window_s=3600,
            throttle_max_notifications=2,
            quiet_hours_start_minute=None,
            quiet_hours_end_minute=None,
            quiet_hours_tz="UTC",
            enabled=True,
        ),
    )

    decision = router.should_notify(
        cast(Any, _FakeSession(dedupe_exists=False, sent_count=2)),
        _candidate(),
        now=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )

    assert decision.should_notify is False
    assert decision.decision == "suppressed_throttle"


def test_router_delivers_when_policy_allows(monkeypatch) -> None:
    router = AlertRouter()
    monkeypatch.setattr(
        router,
        "_load_policy",
        lambda _session, _device_id: RoutingPolicy(
            dedupe_window_s=0,
            throttle_window_s=0,
            throttle_max_notifications=0,
            quiet_hours_start_minute=None,
            quiet_hours_end_minute=None,
            quiet_hours_tz="UTC",
            enabled=True,
        ),
    )

    decision = router.should_notify(
        cast(Any, _FakeSession()),
        _candidate(),
        now=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    )

    assert decision.should_notify is True
    assert decision.decision == "deliver"
