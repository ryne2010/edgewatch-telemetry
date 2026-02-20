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
