from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agent.cost_caps import CostCapState, CostCapsPolicy


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def test_cost_cap_state_persists_and_resets_on_utc_day_change(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 2, 21, 12, 0, 0, tzinfo=timezone.utc))
    path = tmp_path / "cost_caps.json"

    state = CostCapState(path=path, now_fn=clock)
    state.record_bytes_sent(120)
    state.record_snapshot_capture()

    counters = state.counters()
    assert counters.utc_day == "2026-02-21"
    assert counters.bytes_sent_today == 120
    assert counters.snapshots_today == 1
    assert counters.media_uploads_today == 1

    reloaded = CostCapState(path=path, now_fn=clock)
    assert reloaded.counters().bytes_sent_today == 120
    assert reloaded.counters().snapshots_today == 1

    clock.now = datetime(2026, 2, 22, 0, 0, 1, tzinfo=timezone.utc)
    reset = reloaded.counters()
    assert reset.utc_day == "2026-02-22"
    assert reset.bytes_sent_today == 0
    assert reset.snapshots_today == 0
    assert reset.media_uploads_today == 0


def test_telemetry_heartbeat_only_when_byte_cap_reached(tmp_path: Path) -> None:
    state = CostCapState(
        path=tmp_path / "cost_caps.json",
        now_fn=_Clock(datetime(2026, 2, 21, 12, 0, 0, tzinfo=timezone.utc)),
    )
    policy = CostCapsPolicy(
        max_bytes_per_day=100,
        max_snapshots_per_day=10,
        max_media_uploads_per_day=10,
    )

    state.record_bytes_sent(99)
    assert state.allow_telemetry_reason("delta", policy) is True

    state.record_bytes_sent(1)
    assert state.telemetry_heartbeat_only(policy) is True
    assert state.allow_telemetry_reason("delta", policy) is False
    assert state.allow_telemetry_reason("heartbeat", policy) is True
    assert state.allow_telemetry_reason("startup", policy) is True


def test_snapshot_capture_blocked_when_caps_hit(tmp_path: Path) -> None:
    state = CostCapState(
        path=tmp_path / "cost_caps.json",
        now_fn=_Clock(datetime(2026, 2, 21, 12, 0, 0, tzinfo=timezone.utc)),
    )
    policy = CostCapsPolicy(
        max_bytes_per_day=500,
        max_snapshots_per_day=2,
        max_media_uploads_per_day=2,
    )

    assert state.allow_snapshot_capture(policy) is True
    state.record_snapshot_capture()
    assert state.allow_snapshot_capture(policy) is True
    state.record_snapshot_capture()
    assert state.allow_snapshot_capture(policy) is False

    audit = state.audit_metrics(policy)
    assert audit["cost_cap_active"] is True
    assert audit["snapshots_today"] == 2
    assert audit["media_uploads_today"] == 2
