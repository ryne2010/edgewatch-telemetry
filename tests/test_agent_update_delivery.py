from __future__ import annotations

import importlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from agent.device_policy import PendingUpdateCommand

AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

agent_main = importlib.import_module("edgewatch_agent")


def test_pending_update_command_defers_when_power_guard_blocks(tmp_path: Path, monkeypatch) -> None:
    base_policy = agent_main._default_policy("demo-well-001")
    policy = replace(
        base_policy,
        pending_update_command=PendingUpdateCommand(
            deployment_id="dep-1",
            manifest_id="man-1",
            git_tag="v1.2.3",
            commit_sha="a" * 40,
            issued_at="2026-02-27T00:00:00Z",
            expires_at="2026-08-27T00:00:00Z",
            signature="sig",
            signature_key_id="key-1",
            rollback_to_tag="v1.2.2",
            health_timeout_s=300,
            power_guard_required=True,
        ),
    )
    reports: list[str] = []
    monkeypatch.setattr(
        agent_main,
        "report_update_state",
        lambda *_args, **kwargs: (
            reports.append(str(kwargs.get("state", ""))),
            SimpleNamespace(status_code=200, text="", headers={}),
        )[1],
    )
    update_state = tmp_path / "update_state.json"
    agent_main._maybe_apply_pending_update_command(
        session=SimpleNamespace(),
        api_url="http://localhost:8082",
        token="tok",
        policy=policy,
        update_state_path=update_state,
        power_input_out_of_range=True,
        power_unsustainable=False,
        now_s=1000.0,
    )
    assert reports == ["deferred"]


def test_pending_update_command_dry_run_reports_healthy_and_persists_state(
    tmp_path: Path, monkeypatch
) -> None:
    base_policy = agent_main._default_policy("demo-well-001")
    policy = replace(
        base_policy,
        pending_update_command=PendingUpdateCommand(
            deployment_id="dep-2",
            manifest_id="man-2",
            git_tag="v2.0.0",
            commit_sha="b" * 40,
            issued_at="2026-02-27T00:00:00Z",
            expires_at="2026-08-27T00:00:00Z",
            signature="sig",
            signature_key_id="key-2",
            rollback_to_tag=None,
            health_timeout_s=300,
            power_guard_required=False,
        ),
    )

    reports: list[str] = []
    monkeypatch.setattr(
        agent_main,
        "report_update_state",
        lambda *_args, **kwargs: (
            reports.append(str(kwargs.get("state", ""))),
            SimpleNamespace(status_code=200, text="", headers={}),
        )[1],
    )
    monkeypatch.setattr(agent_main, "_verify_tag_commit", lambda **_kwargs: (True, "ok"))
    monkeypatch.setenv("EDGEWATCH_ENABLE_OTA_APPLY", "0")

    update_state = tmp_path / "update_state.json"
    agent_main._maybe_apply_pending_update_command(
        session=SimpleNamespace(),
        api_url="http://localhost:8082",
        token="tok",
        policy=policy,
        update_state_path=update_state,
        power_input_out_of_range=False,
        power_unsustainable=False,
        now_s=2000.0,
    )

    assert reports == ["downloading", "verifying", "applying", "restarting", "healthy"]
    state = json.loads(update_state.read_text(encoding="utf-8"))
    assert state["last_applied_deployment_id"] == "dep-2"
    assert state["last_healthy_tag"] == "v2.0.0"
    assert state["last_failed_deployment_id"] is None
