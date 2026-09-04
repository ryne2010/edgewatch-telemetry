from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

import agent.cost_caps as cost_caps_module
from agent.cost_caps import DEFAULT_URGENT_RESERVE_BYTES, CostCapError, CostCapState, CostCapsPolicy


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


def test_cost_cap_state_save_fsyncs_file_and_parent_and_uses_private_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    file_fsyncs: list[int] = []
    directory_fsyncs: list[Path] = []
    monkeypatch.setattr(cost_caps_module.os, "fsync", file_fsyncs.append)
    monkeypatch.setattr(cost_caps_module, "_fsync_directory", directory_fsyncs.append)
    path = tmp_path / "state" / "cost_caps.json"
    state = CostCapState(path=path)

    state.record_bytes_sent(100)

    assert file_fsyncs
    assert directory_fsyncs == [path.parent]
    assert path.stat().st_mode & 0o777 == 0o600
    assert list(path.parent.glob(f".{path.name}.*.tmp")) == []


def test_invalid_existing_cost_cap_state_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "cost_caps.json"
    path.write_text('{"utc_day":"2026-08-09","bytes_sent_today":"unknown"}', encoding="utf-8")

    with pytest.raises(CostCapError, match="invalid cost-cap state"):
        CostCapState(path=path)


def test_telemetry_heartbeat_only_when_byte_cap_reached(tmp_path: Path) -> None:
    state = CostCapState(
        path=tmp_path / "cost_caps.json",
        now_fn=_Clock(datetime(2026, 2, 21, 12, 0, 0, tzinfo=timezone.utc)),
        urgent_reserve_bytes=25,
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
    assert state.allow_telemetry_reason("state_change", policy) is True
    assert state.allow_telemetry_reason("alert_change", policy) is True
    assert state.allow_telemetry_reason("alert_snapshot", policy) is True
    assert state.routine_bytes_remaining(policy) == 0
    assert state.urgent_bytes_remaining(policy) == 25

    state.record_bytes_sent(25)
    assert state.allow_telemetry_reason("heartbeat", policy) is False
    assert state.urgent_bytes_remaining(policy) == 0


def test_cost_cap_urgent_reserve_is_configurable_from_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EDGEWATCH_COST_CAP_STATE_PATH", str(tmp_path / "cost_caps.json"))
    monkeypatch.setenv("EDGEWATCH_COST_CAP_URGENT_RESERVE_BYTES", "4096")

    state = CostCapState.from_env(device_id="device-1")

    assert state.urgent_reserve_bytes == 4096


def test_cost_cap_urgent_reserve_defaults_and_rejects_invalid_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EDGEWATCH_COST_CAP_STATE_PATH", str(tmp_path / "cost_caps.json"))
    assert CostCapState.from_env(device_id="device-1").urgent_reserve_bytes == (DEFAULT_URGENT_RESERVE_BYTES)

    monkeypatch.setenv("EDGEWATCH_COST_CAP_URGENT_RESERVE_BYTES", "-1")
    with pytest.raises(CostCapError, match="non-negative integer"):
        CostCapState.from_env(device_id="device-1")


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
    assert audit["urgent_reserve_bytes"] == DEFAULT_URGENT_RESERVE_BYTES


def test_measured_interface_bytes_raise_but_never_reduce_counter(tmp_path: Path) -> None:
    state = CostCapState(
        path=tmp_path / "cost_caps.json",
        now_fn=_Clock(datetime(2026, 2, 21, 12, 0, 0, tzinfo=timezone.utc)),
    )

    state.record_bytes_sent(120)
    state.observe_bytes_sent_today(900)
    assert state.counters().bytes_sent_today == 900

    state.observe_bytes_sent_today(500)
    assert state.counters().bytes_sent_today == 900
