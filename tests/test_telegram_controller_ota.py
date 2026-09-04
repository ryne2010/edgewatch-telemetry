from __future__ import annotations

import base64

import pytest

from agent.local_ota import OtaError, ReleaseCatalog, ReleaseManifest
from telegram_controller.ota import OtaOrchestrator


def _catalog() -> ReleaseCatalog:
    manifest = ReleaseManifest.from_payload(
        {
            "version": "1.0.0",
            "tag": "v1.0.0",
            "commit": "a" * 40,
            "type": "application_bundle",
            "uri": "https://releases.example/app.tar",
            "size": 100,
            "sha256": "b" * 64,
            "signature": base64.b64encode(b"signed").decode(),
            "signature_scheme": "openssl_rsa_sha256",
            "key_id": "prod",
            "runtime_dependency_sha256": "c" * 64,
            "compatibility": {
                "schema_version": 1,
                "hardware_models": ["raspberry-pi-4"],
                "release_channel": "stable",
                "minimum_python_version": "3.11.0",
                "minimum_runtime_schema": 1,
                "minimum_ota_schema": 1,
                "requires_stable_power": True,
                "requires_apply_enabled": True,
                "minimum_free_bytes": 0,
            },
            "manifest_signature": base64.b64encode(b"manifest-signed").decode(),
        }
    )
    return ReleaseCatalog({"release-1": manifest}, {"stable": "release-1"})


def _record_staged(orchestrator: OtaOrchestrator) -> None:
    for device_id in orchestrator.snapshot()["targets"]:
        orchestrator.record_result(device_id, "staged")


def test_manual_canary_and_one_tranche_per_promote() -> None:
    orchestrator = OtaOrchestrator(_catalog(), canary_device_ids=["device-1"], rollout_percentages=(50, 100))
    staged = orchestrator.stage("stable", ["device-1", "device-2", "device-3", "device-4"])
    assert {command.action for command in staged} == {"ota_stage"}
    assert len(staged) == 4
    assert all(command.command_type == "ota_stage" for command in staged)
    assert staged[0].arguments["manifest"] == _catalog().resolve("stable").to_command_payload()
    with pytest.raises(OtaError, match="terminal staging"):
        orchestrator.canary()
    _record_staged(orchestrator)
    deployment_id = orchestrator.snapshot()["deployment_id"]
    assert orchestrator.preview_canary_device_ids() == ("device-1",)
    canary = orchestrator.canary(deployment_id, expected_device_ids=["device-1"])
    assert [command.device_id for command in canary] == ["device-1"]
    assert canary[0].arguments["release_alias"] == "stable"
    assert canary[0].arguments["manifest"] == _catalog().resolve("stable").to_command_payload()
    with pytest.raises(OtaError, match="terminal result"):
        orchestrator.promote()
    first = orchestrator.promote(results={"device-1": "healthy"})
    assert len(first) == 1
    assert first[0].device_id == "device-2"
    second = orchestrator.promote(results={"device-2": "healthy"})
    assert {command.device_id for command in second} == {"device-3", "device-4"}
    orchestrator.record_result("device-3", "healthy")
    assert orchestrator.snapshot()["status"] == "rollout"
    orchestrator.record_result("device-4", "healthy")
    assert orchestrator.snapshot()["status"] == "complete"
    assert orchestrator.snapshot()["enabled"] == ["device-3", "device-4"]


def test_failure_and_defer_gates_halt_promotion() -> None:
    failure = OtaOrchestrator(_catalog(), canary_device_ids=["device-1"])
    failure.stage("stable", ["device-1", "device-2"])
    _record_staged(failure)
    failure.canary()
    with pytest.raises(OtaError, match="failure rate"):
        failure.promote(results={"device-1": "failed"})
    assert failure.snapshot()["status"] == "halted"

    deferred = OtaOrchestrator(_catalog(), canary_device_ids=["device-1"])
    deferred.stage("stable", ["device-1", "device-2"])
    _record_staged(deferred)
    deferred.canary()
    with pytest.raises(OtaError, match="defer rate"):
        deferred.promote(results={"device-1": "deferred"})
    assert deferred.snapshot()["status"] == "halted"


def test_abort_keeps_applied_truth_and_stops_new_dispatch() -> None:
    orchestrator = OtaOrchestrator(_catalog(), canary_device_ids=["device-1"])
    orchestrator.stage("stable", ["device-1", "device-2"])
    _record_staged(orchestrator)
    orchestrator.canary()
    assert orchestrator.abort() == []
    snapshot = orchestrator.snapshot()
    assert snapshot["status"] == "aborted"
    assert snapshot["undispatched_at_abort"] == ["device-2"]
    with pytest.raises(OtaError):
        orchestrator.promote(results={"device-1": "healthy"})


def test_requires_configured_canary_and_rejects_telegram_url() -> None:
    with pytest.raises(OtaError, match="canary"):
        OtaOrchestrator(_catalog(), canary_device_ids=[])
    orchestrator = OtaOrchestrator(_catalog(), canary_device_ids=["device-1"])
    with pytest.raises(OtaError, match="not a URL"):
        orchestrator.stage("https://evil.example/release", ["device-1"])
    with pytest.raises(OtaError, match="no configured canaries"):
        orchestrator.stage("stable", ["device-2"])


def test_snapshot_roundtrip_restores_frozen_rollout_state() -> None:
    original = OtaOrchestrator(_catalog(), canary_device_ids=["device-1"], rollout_percentages=(50, 100))
    original.stage("stable", ["device-1", "device-2", "device-3"])
    _record_staged(original)
    original.canary()
    original.record_result("device-1", "healthy")

    restored = OtaOrchestrator.from_snapshot(_catalog(), original.snapshot())
    assert restored.snapshot() == original.snapshot()
    deployment_id = restored.snapshot()["deployment_id"]
    assert restored.preview_promote_device_ids(deployment_id) == ("device-2",)
    with pytest.raises(OtaError, match="targets are stale"):
        restored.promote(deployment_id, expected_device_ids=["device-3"])
    promoted = restored.promote(deployment_id, expected_device_ids=["device-2"])
    assert [command.device_id for command in promoted] == ["device-2"]
    assert promoted[0].operation == "ota_promote"
    assert promoted[0].arguments == {}


def test_snapshot_rejects_tampering_and_catalog_drift() -> None:
    original = OtaOrchestrator(_catalog(), canary_device_ids=["device-1"])
    original.stage("stable", ["device-1", "device-2"])
    snapshot = original.snapshot()
    snapshot["targets"] = ["device-2"]
    with pytest.raises(OtaError, match="target hash"):
        OtaOrchestrator.from_snapshot(_catalog(), snapshot)

    snapshot = original.snapshot()
    snapshot["manifest"]["artifact_sha256"] = "c" * 64
    with pytest.raises(OtaError, match="manifest"):
        OtaOrchestrator.from_snapshot(_catalog(), snapshot)


def test_staging_failure_halts_canary_and_stale_confirmation_is_rejected() -> None:
    failed = OtaOrchestrator(_catalog(), canary_device_ids=["device-1"])
    failed.stage("stable", ["device-1", "device-2"])
    failed.record_result("device-1", "staged")
    failed.record_result("device-2", "failed")
    with pytest.raises(OtaError, match="stage successfully"):
        failed.canary()
    assert failed.snapshot()["status"] == "halted"

    stale = OtaOrchestrator(_catalog(), canary_device_ids=["device-1"])
    stale.stage("stable", ["device-1", "device-2"])
    _record_staged(stale)
    with pytest.raises(OtaError, match="targets are stale"):
        stale.canary(expected_device_ids=["device-2"])
    assert stale.snapshot()["status"] == "staging"


def test_promote_completes_without_empty_dispatch_when_all_targets_are_covered() -> None:
    orchestrator = OtaOrchestrator(
        _catalog(), canary_device_ids=["device-1", "device-2"], rollout_percentages=(10, 100)
    )
    orchestrator.stage("stable", ["device-1", "device-2"])
    _record_staged(orchestrator)
    orchestrator.canary()
    orchestrator.record_result("device-1", "healthy")
    orchestrator.record_result("device-2", "healthy")

    assert orchestrator.preview_promote_device_ids() == ()
    assert orchestrator.promote(expected_device_ids=[]) == []
    snapshot = orchestrator.snapshot()
    assert snapshot["status"] == "complete"
    assert snapshot["enabled"] == ["device-1", "device-2"]
