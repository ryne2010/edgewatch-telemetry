from __future__ import annotations

import importlib
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.device_policy import PendingControlCommand

AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

agent_main = importlib.import_module("edgewatch_agent")


def test_command_state_roundtrip(tmp_path: Path) -> None:
    state_path = tmp_path / "command_state.json"
    agent_main._save_command_state(
        state_path,
        last_applied_command_id="cmd-1",
        pending_ack_command_id="cmd-2",
    )
    last_applied, pending_ack = agent_main._load_command_state(state_path)
    assert last_applied == "cmd-1"
    assert pending_ack == "cmd-2"


def test_apply_pending_command_is_once_and_persistent(tmp_path: Path) -> None:
    base_policy = agent_main._default_policy("demo-well-001")
    policy = replace(
        base_policy,
        pending_control_command=PendingControlCommand(
            id="cmd-1",
            issued_at="2026-02-27T00:00:00Z",
            expires_at="2026-08-27T00:00:00Z",
            operation_mode="sleep",
            sleep_poll_interval_s=7200,
            shutdown_requested=False,
            shutdown_grace_s=30,
            alerts_muted_until=None,
            alerts_muted_reason="offseason",
        ),
    )
    state_path = tmp_path / "command_state.json"

    mode1, sleep1, last1, ack1, applied1 = agent_main._apply_pending_control_command_override(
        policy=policy,
        last_applied_command_id=None,
        pending_ack_command_id=None,
        command_state_path=state_path,
    )
    assert mode1 == "sleep"
    assert sleep1 == 7200
    assert last1 == "cmd-1"
    assert ack1 == "cmd-1"
    assert applied1 == "cmd-1"

    mode2, sleep2, last2, ack2, applied2 = agent_main._apply_pending_control_command_override(
        policy=policy,
        last_applied_command_id=last1,
        pending_ack_command_id=ack1,
        command_state_path=state_path,
    )
    assert mode2 == "sleep"
    assert sleep2 == 7200
    assert last2 == "cmd-1"
    assert ack2 == "cmd-1"
    assert applied2 is None

    saved_last, saved_ack = agent_main._load_command_state(state_path)
    assert saved_last == "cmd-1"
    assert saved_ack == "cmd-1"


def test_expired_pending_command_is_not_applied(tmp_path: Path) -> None:
    base_policy = agent_main._default_policy("demo-well-001")
    policy = replace(
        base_policy,
        pending_control_command=PendingControlCommand(
            id="cmd-expired",
            issued_at="2026-01-01T00:00:00Z",
            expires_at="2026-01-02T00:00:00Z",
            operation_mode="disabled",
            sleep_poll_interval_s=3600,
            shutdown_requested=True,
            shutdown_grace_s=45,
            alerts_muted_until=None,
            alerts_muted_reason=None,
        ),
    )
    state_path = tmp_path / "command_state.json"

    mode, sleep_s, last_applied, pending_ack, applied = agent_main._apply_pending_control_command_override(
        policy=policy,
        last_applied_command_id=None,
        pending_ack_command_id=None,
        command_state_path=state_path,
    )
    assert mode == base_policy.operation_mode
    assert sleep_s == base_policy.sleep_poll_interval_s
    assert last_applied is None
    assert pending_ack is None
    assert applied is None


def test_ack_helper_clears_pending_on_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_path = tmp_path / "command_state.json"
    agent_main._save_command_state(
        state_path,
        last_applied_command_id="cmd-1",
        pending_ack_command_id="cmd-1",
    )

    monkeypatch.setattr(
        agent_main,
        "ack_control_command",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=204, headers={}, text=""),
    )

    pending, last_log = agent_main._maybe_ack_pending_command(
        session=SimpleNamespace(),
        api_url="http://localhost:8082",
        token="tok",
        pending_ack_command_id="cmd-1",
        last_applied_command_id="cmd-1",
        command_state_path=state_path,
        now_s=1000.0,
        last_log_at=0.0,
    )
    assert pending is None
    assert last_log == 0.0
    saved_last, saved_ack = agent_main._load_command_state(state_path)
    assert saved_last == "cmd-1"
    assert saved_ack is None


def test_ack_helper_retries_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_path = tmp_path / "command_state.json"
    monkeypatch.setattr(
        agent_main,
        "ack_control_command",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=500, headers={}, text="boom"),
    )

    pending, last_log = agent_main._maybe_ack_pending_command(
        session=SimpleNamespace(),
        api_url="http://localhost:8082",
        token="tok",
        pending_ack_command_id="cmd-9",
        last_applied_command_id="cmd-9",
        command_state_path=state_path,
        now_s=600.0,
        last_log_at=0.0,
    )
    assert pending == "cmd-9"
    assert last_log == 600.0


def test_pending_shutdown_state_skips_execution_when_remote_shutdown_disabled() -> None:
    state = agent_main.AgentState()
    pending = PendingControlCommand(
        id="cmd-shutdown-1",
        issued_at="2026-02-27T00:00:00Z",
        expires_at="2026-08-27T00:00:00Z",
        operation_mode="disabled",
        sleep_poll_interval_s=3600,
        shutdown_requested=True,
        shutdown_grace_s=30,
        alerts_muted_until=None,
        alerts_muted_reason="offseason",
    )
    agent_main._sync_pending_shutdown_state(
        state=state,
        pending_command=pending,
        last_applied_command_id="cmd-shutdown-1",
        now_utc=datetime(2026, 2, 27, tzinfo=timezone.utc),
        now_s=1000.0,
    )
    assert state.pending_shutdown_command_id == "cmd-shutdown-1"

    executed = agent_main._maybe_execute_pending_shutdown(
        state=state,
        pending_ack_command_id=None,
        allow_remote_shutdown=False,
        now_s=1100.0,
    )
    assert executed is False
    assert state.pending_shutdown_command_id is None


def test_pending_shutdown_executes_after_ack_and_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = agent_main.AgentState()
    pending = PendingControlCommand(
        id="cmd-shutdown-2",
        issued_at="2026-02-27T00:00:00Z",
        expires_at="2026-08-27T00:00:00Z",
        operation_mode="disabled",
        sleep_poll_interval_s=3600,
        shutdown_requested=True,
        shutdown_grace_s=45,
        alerts_muted_until=None,
        alerts_muted_reason="maintenance",
    )
    calls: list[tuple[int, str]] = []
    monkeypatch.setattr(
        agent_main,
        "_run_remote_shutdown",
        lambda *, shutdown_grace_s, command_id: (calls.append((shutdown_grace_s, command_id)), True)[1],
    )

    agent_main._sync_pending_shutdown_state(
        state=state,
        pending_command=pending,
        last_applied_command_id="cmd-shutdown-2",
        now_utc=datetime(2026, 2, 27, tzinfo=timezone.utc),
        now_s=2000.0,
    )
    assert state.pending_shutdown_command_id == "cmd-shutdown-2"

    # Must not execute until ack clears.
    executed_waiting_ack = agent_main._maybe_execute_pending_shutdown(
        state=state,
        pending_ack_command_id="cmd-shutdown-2",
        allow_remote_shutdown=True,
        now_s=2100.0,
    )
    assert executed_waiting_ack is False
    assert calls == []

    # Ack is clear but grace has not elapsed yet.
    executed_waiting_grace = agent_main._maybe_execute_pending_shutdown(
        state=state,
        pending_ack_command_id=None,
        allow_remote_shutdown=True,
        now_s=2030.0,
    )
    assert executed_waiting_grace is False
    assert calls == []

    # After grace window, shutdown executes.
    executed = agent_main._maybe_execute_pending_shutdown(
        state=state,
        pending_ack_command_id=None,
        allow_remote_shutdown=True,
        now_s=2060.0,
    )
    assert executed is True
    assert calls == [(45, "cmd-shutdown-2")]
    assert state.pending_shutdown_command_id is None
