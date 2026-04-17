from __future__ import annotations

import importlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from agent.device_policy import PendingProcedureInvocation

AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

agent_main = importlib.import_module("edgewatch_agent")


def test_pending_procedure_invocation_executes_and_reports_success(tmp_path: Path, monkeypatch) -> None:
    base_policy = agent_main._default_policy("demo-well-001")
    policy = replace(
        base_policy,
        pending_procedure_invocation=PendingProcedureInvocation(
            id="inv-1",
            definition_id="def-1",
            definition_name="capture_snapshot",
            request_payload={"camera_id": "cam1"},
            issued_at="2026-02-27T00:00:00Z",
            expires_at="2026-08-27T00:00:00Z",
            timeout_s=30,
        ),
    )

    reports: list[dict[str, object]] = []
    monkeypatch.setattr(
        agent_main,
        "report_procedure_result",
        lambda *_args, **kwargs: (
            reports.append(
                {
                    "invocation_id": kwargs["invocation_id"],
                    "status": kwargs["status"],
                    "result_payload": kwargs.get("result_payload"),
                }
            ),
            SimpleNamespace(status_code=200, text="", headers={}),
        )[1],
    )
    monkeypatch.setenv("EDGEWATCH_PROCEDURE_RUNNER_CMD", "echo")

    def _fake_run(*_args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True}), stderr="")

    monkeypatch.setattr(agent_main.subprocess, "run", _fake_run)

    state_path = tmp_path / "procedure_state.json"
    agent_main._maybe_run_pending_procedure_invocation(
        session=SimpleNamespace(),
        api_url="http://localhost:8082",
        token="tok",
        policy=policy,
        procedure_state_path=state_path,
    )

    assert reports == [
        {
            "invocation_id": "inv-1",
            "status": "succeeded",
            "result_payload": {"ok": True},
        }
    ]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["last_completed_invocation_id"] == "inv-1"
