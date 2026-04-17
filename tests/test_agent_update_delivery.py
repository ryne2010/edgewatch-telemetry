from __future__ import annotations

import importlib
import json
import sys
import tarfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from agent.device_policy import PendingUpdateCommand

AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

agent_main = importlib.import_module("edgewatch_agent")


def _make_artifact(tmp_path: Path, name: str) -> tuple[str, int, str]:
    payload_dir = tmp_path / f"{name}-dir"
    payload_dir.mkdir(parents=True, exist_ok=True)
    (payload_dir / "README.txt").write_text(f"{name}\n", encoding="utf-8")
    archive = tmp_path / f"{name}.tar"
    with tarfile.open(archive, "w") as tar:
        tar.add(payload_dir, arcname=".")
    return archive.as_uri(), archive.stat().st_size, agent_main._sha256_file(archive)


def test_pending_update_command_defers_when_power_guard_blocks(tmp_path: Path, monkeypatch) -> None:
    base_policy = agent_main._default_policy("demo-well-001")
    artifact_uri, artifact_size, artifact_sha256 = _make_artifact(tmp_path, "dep-1")
    policy = replace(
        base_policy,
        pending_update_command=PendingUpdateCommand(
            deployment_id="dep-1",
            manifest_id="man-1",
            git_tag="v1.2.3",
            commit_sha="a" * 40,
            update_type="application_bundle",
            artifact_uri=artifact_uri,
            artifact_size=artifact_size,
            artifact_sha256=artifact_sha256,
            artifact_signature="",
            artifact_signature_scheme="none",
            compatibility={},
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
    artifact_uri, artifact_size, artifact_sha256 = _make_artifact(tmp_path, "dep-2")
    policy = replace(
        base_policy,
        pending_update_command=PendingUpdateCommand(
            deployment_id="dep-2",
            manifest_id="man-2",
            git_tag="v2.0.0",
            commit_sha="b" * 40,
            update_type="application_bundle",
            artifact_uri=artifact_uri,
            artifact_size=artifact_size,
            artifact_sha256=artifact_sha256,
            artifact_signature="",
            artifact_signature_scheme="none",
            compatibility={},
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
    monkeypatch.setenv("EDGEWATCH_ENABLE_OTA_APPLY", "0")
    monkeypatch.setenv("EDGEWATCH_OTA_CACHE_DIR", str(tmp_path / "cache"))

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

    assert reports == ["downloading", "downloaded", "verifying", "applying", "staged", "switching", "healthy"]
    state = json.loads(update_state.read_text(encoding="utf-8"))
    assert state["last_applied_deployment_id"] == "dep-2"
    assert state["last_healthy_tag"] == "v2.0.0"
    assert state["last_applied_artifact_sha256"] == artifact_sha256
    assert state["last_failed_deployment_id"] is None


def test_system_image_update_uses_repo_default_wrapper_when_env_unset(tmp_path: Path, monkeypatch) -> None:
    artifact = tmp_path / "system.img"
    artifact.write_bytes(b"edgewatch-system-image")
    monkeypatch.delenv("EDGEWATCH_SYSTEM_IMAGE_APPLY_CMD", raising=False)
    monkeypatch.setenv("EDGEWATCH_SYSTEM_IMAGE_STAGE_DIR", str(tmp_path / "stage"))
    ok, reason = agent_main._invoke_system_image_updater(
        artifact_path=artifact,
        manifest_id="manifest-system-1",
        artifact_sha256=agent_main._sha256_file(artifact),
    )
    assert ok is True, reason
    latest = json.loads((tmp_path / "stage" / "latest.json").read_text(encoding="utf-8"))
    assert latest["manifest_id"] == "manifest-system-1"
    assert latest["status"] == "staged"


def test_boot_health_timeout_uses_repo_default_rollback_wrapper_when_env_unset(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("EDGEWATCH_SYSTEM_IMAGE_ROLLBACK_CMD", raising=False)
    monkeypatch.setenv("EDGEWATCH_SYSTEM_IMAGE_STAGE_DIR", str(tmp_path / "stage"))
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir / "latest.json").write_text(
        json.dumps(
            {
                "manifest_id": "manifest-system-2",
                "artifact_path": str(tmp_path / "system.img"),
                "artifact_sha256": "a" * 64,
                "staged_at": "2026-01-01T00:00:00+00:00",
                "status": "staged",
            }
        ),
        encoding="utf-8",
    )
    update_state = tmp_path / "update_state.json"
    update_state.write_text(
        json.dumps(
            {
                "pending_boot_health": {
                    "deployment_id": "dep-system-2",
                    "git_tag": "v2.0.0",
                    "artifact_sha256": "a" * 64,
                    "origin_session_id": agent_main.PROCESS_SESSION_ID,
                    "deadline_s": 10.0,
                    "rollback_manifest_id": "v1.9.9",
                }
            }
        ),
        encoding="utf-8",
    )
    reports: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        agent_main,
        "_report_update_state_best_effort",
        lambda **kwargs: reports.append((str(kwargs.get("state", "")), kwargs.get("reason_code"))),
    )
    agent_main._maybe_complete_pending_boot_health(
        session=SimpleNamespace(),
        api_url="http://localhost:8082",
        token="tok",
        update_state_path=update_state,
        now_s=20.0,
    )
    latest = json.loads((stage_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["status"] == "rollback_requested"
    assert ("failed", "boot_health_timeout") in reports
    assert ("rolled_back", "boot_health_timeout") in reports
