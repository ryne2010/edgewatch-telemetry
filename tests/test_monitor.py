from __future__ import annotations

from datetime import datetime, timedelta, timezone

from api.app.models import Device
from api.app.services.monitor import compute_status


def _device(*, last_seen_at: datetime | None, offline_after_s: int) -> Device:
    # Instantiate an unmapped Device instance (no DB required) for pure status tests.
    return Device(
        device_id="demo-001",
        display_name="Demo",
        token_hash="x",
        token_fingerprint="y",
        heartbeat_interval_s=30,
        offline_after_s=offline_after_s,
        last_seen_at=last_seen_at,
        enabled=True,
    )


def test_compute_status_unknown_when_never_seen() -> None:
    d = _device(last_seen_at=None, offline_after_s=60)
    status, seconds = compute_status(d, now=datetime.now(timezone.utc))
    assert status == "unknown"
    assert seconds is None


def test_compute_status_online_vs_offline_threshold() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    d_online = _device(last_seen_at=now - timedelta(seconds=59), offline_after_s=60)
    status, seconds = compute_status(d_online, now=now)
    assert status == "online"
    assert seconds == 59

    d_offline = _device(last_seen_at=now - timedelta(seconds=61), offline_after_s=60)
    status, seconds = compute_status(d_offline, now=now)
    assert status == "offline"
    assert seconds == 61


def test_compute_status_sleep_and_disabled_modes() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    d_sleep = _device(last_seen_at=now - timedelta(seconds=10), offline_after_s=60)
    d_sleep.operation_mode = "sleep"
    status_sleep, seconds_sleep = compute_status(d_sleep, now=now)
    assert status_sleep == "sleep"
    assert seconds_sleep == 10

    d_disabled_mode = _device(last_seen_at=now - timedelta(seconds=10), offline_after_s=60)
    d_disabled_mode.operation_mode = "disabled"
    status_disabled, seconds_disabled = compute_status(d_disabled_mode, now=now)
    assert status_disabled == "disabled"
    assert seconds_disabled == 10

    d_disabled_flag = _device(last_seen_at=None, offline_after_s=60)
    d_disabled_flag.enabled = False
    status_disabled_flag, seconds_disabled_flag = compute_status(d_disabled_flag, now=now)
    assert status_disabled_flag == "disabled"
    assert seconds_disabled_flag is None
