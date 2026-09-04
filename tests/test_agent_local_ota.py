from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import subprocess
import tarfile
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from agent.local_ota import (
    LocalOtaManager,
    OtaError,
    ReleaseCatalog,
    ReleaseManifest,
    RetryableOtaError,
    canonical_manifest_bytes,
)


def _keys(tmp_path: Path) -> tuple[Path, Path]:
    private_key = tmp_path / "private.pem"
    keyring = tmp_path / "keys"
    keyring.mkdir()
    public_key = keyring / "release.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", private_key],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "pkey", "-in", private_key, "-pubout", "-out", public_key],
        check=True,
        capture_output=True,
    )
    return private_key, keyring


def _sign_manifest(payload: dict[str, object], private_key: Path, tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    signature = tmp_path / "manifest.sig"
    manifest.write_bytes(canonical_manifest_bytes(payload))
    subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", private_key, "-out", signature, manifest],
        check=True,
        capture_output=True,
    )
    payload["manifest_signature"] = base64.b64encode(signature.read_bytes()).decode()


def _artifact(tmp_path: Path, private_key: Path, *, traversal: bool = False) -> dict[str, object]:
    artifact = tmp_path / ("traversal.tar" if traversal else "app.tar")
    with tarfile.open(artifact, "w") as archive:
        contents = b"edgewatch\n"
        info = tarfile.TarInfo("../../escape" if traversal else "edgewatch/version.txt")
        info.size = len(contents)
        archive.addfile(info, io.BytesIO(contents))
    signature = tmp_path / f"{artifact.name}.sig"
    subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", private_key, "-out", signature, artifact],
        check=True,
        capture_output=True,
    )
    payload: dict[str, object] = {
        "version": "1.2.3",
        "git_tag": "v1.2.3",
        "commit_sha": "a" * 40,
        "update_type": "application_bundle",
        "artifact_uri": artifact.as_uri(),
        "artifact_size": artifact.stat().st_size,
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "artifact_signature": base64.b64encode(signature.read_bytes()).decode(),
        "artifact_signature_scheme": "openssl_rsa_sha256",
        "signature_key_id": "release",
        "runtime_dependency_sha256": hashlib.sha256(b"requests==2.32.4\n").hexdigest(),
        "compatibility": {
            "schema_version": 1,
            "hardware_models": ["test-hardware"],
            "release_channel": "stable",
            "minimum_python_version": "3.11.0",
            "minimum_runtime_schema": 1,
            "minimum_ota_schema": 1,
            "requires_stable_power": True,
            "requires_apply_enabled": True,
            "minimum_free_bytes": 0,
        },
    }
    _sign_manifest(payload, private_key, tmp_path)
    return payload


class _AgentRuntime:
    def __init__(self) -> None:
        self.pid = 100
        self.restarts = 0

    def run(self, command: list[str], **_kwargs: object) -> SimpleNamespace:
        if command[:2] == ["systemctl", "restart"]:
            self.restarts += 1
            self.pid += 1
        if command == ["vcgencmd", "get_throttled"]:
            return SimpleNamespace(returncode=0, stdout="throttled=0x0\n")
        return SimpleNamespace(returncode=0, stdout="")

    def ready(self) -> tuple[int, str]:
        return self.pid, f"session-{self.pid}"


class _CameraRuntime:
    def __init__(self, manager: LocalOtaManager, ready_path: Path, *, fail_call: int | None = None) -> None:
        self.manager = manager
        self.ready_path = ready_path
        self.fail_call = fail_call
        self.commands: list[list[str]] = []

    def write_ready(self) -> None:
        self.ready_path.parent.mkdir(parents=True, exist_ok=True)
        self.ready_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "ready",
                    "device_id": self.manager.device_id,
                    "pid": 123,
                    "boot_id": "boot-1",
                    "issued_at": "1970-01-01T00:15:00+00:00",
                    "valid_until": "1970-01-01T00:20:00+00:00",
                    "application_target": self.manager._current_target(),
                    "known_answers_valid": True,
                    "preprocessing_valid": True,
                    "local_media_only": True,
                }
            ),
            encoding="utf-8",
        )
        self.ready_path.chmod(0o600)

    def run(self, command: list[str], **_kwargs: object) -> SimpleNamespace:
        self.commands.append(command)
        if command == ["vcgencmd", "get_throttled"]:
            return SimpleNamespace(returncode=0, stdout="throttled=0x0\n")
        if command == ["/usr/bin/systemctl", "start", "edgewatch-camera-satellite@check.service"]:
            check_calls = self.commands.count(command)
            if check_calls == self.fail_call:
                return SimpleNamespace(returncode=1, stdout="")
            self.write_ready()
            return SimpleNamespace(returncode=0, stdout="")
        return SimpleNamespace(returncode=1, stdout="")


def _manager(tmp_path: Path, keyring: Path, runtime: _AgentRuntime | None = None) -> LocalOtaManager:
    runtime = runtime or _AgentRuntime()
    dependency_path = tmp_path / "installed" / "agent" / "requirements.txt"
    dependency_path.parent.mkdir(parents=True, exist_ok=True)
    dependency_path.write_text("requests==2.32.4\n", encoding="utf-8")
    return LocalOtaManager(
        state_path=tmp_path / "state.json",
        cache_dir=tmp_path / "cache",
        keyring_dir=keyring,
        releases_root=tmp_path / "releases",
        current_symlink=tmp_path / "current",
        assets_root=tmp_path / "assets",
        apply_enabled=True,
        allow_local_file_artifacts=True,
        hardware_model="test-hardware",
        runtime_dependency_path=dependency_path,
        run_command=runtime.run,
        readiness_probe=runtime.ready,
        sleep=lambda _seconds: None,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("artifact_signature", ""),
        ("artifact_signature", "not-base64"),
        ("artifact_signature_scheme", "none"),
        ("artifact_uri", "http://example.invalid/app.tar"),
    ],
)
def test_manifest_rejects_unsigned_or_unsafe_artifacts(tmp_path: Path, field: str, value: object) -> None:
    private_key, _ = _keys(tmp_path)
    payload = _artifact(tmp_path, private_key)
    payload[field] = value
    with pytest.raises(OtaError):
        ReleaseManifest.from_payload(payload, allow_local_file_artifacts=True)


def test_manifest_requires_exact_compatibility_schema_and_https_by_default(tmp_path: Path) -> None:
    private_key, _ = _keys(tmp_path)
    payload = _artifact(tmp_path, private_key)
    with pytest.raises(OtaError, match="https"):
        ReleaseManifest.from_payload(payload)

    missing = dict(payload)
    compatibility = dict(cast(dict[str, object], payload["compatibility"]))
    compatibility.pop("minimum_runtime_schema")
    missing["compatibility"] = compatibility
    with pytest.raises(OtaError, match="missing compatibility fields"):
        ReleaseManifest.from_payload(missing, allow_local_file_artifacts=True)

    unknown = dict(payload)
    compatibility = dict(cast(dict[str, object], payload["compatibility"]))
    compatibility["future_bypass"] = True
    unknown["compatibility"] = compatibility
    with pytest.raises(OtaError, match="unknown compatibility fields"):
        ReleaseManifest.from_payload(unknown, allow_local_file_artifacts=True)

    missing_dependency = dict(payload)
    missing_dependency.pop("runtime_dependency_sha256")
    with pytest.raises(OtaError, match="runtime_dependency_sha256"):
        ReleaseManifest.from_payload(missing_dependency, allow_local_file_artifacts=True)


def test_satellite_uses_only_the_private_gateway_cache_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key, keyring = _keys(tmp_path)
    payload = _artifact(tmp_path, private_key)
    artifact_uri = str(payload["artifact_uri"])
    artifact = Path(urllib.request.url2pathname(artifact_uri[len("file://") :])).read_bytes()
    manifest = ReleaseManifest.from_payload(payload, allow_local_file_artifacts=True)
    manager = _manager(tmp_path, keyring)
    manager.gateway_cache_base_url = "http://10.42.0.1:8091"
    requests: list[str] = []

    class Response(io.BytesIO):
        status = 200

    def cached_open(request: object, **_kwargs: object) -> Response:
        requests.append(cast(urllib.request.Request, request).full_url)
        return Response(artifact)

    monkeypatch.setattr("agent.local_ota.urllib.request.urlopen", cached_open)
    destination = tmp_path / "cached.tar"
    manager._download(manifest, destination)

    assert destination.read_bytes() == artifact
    assert requests == [f"http://10.42.0.1:8091/artifacts/{manifest.artifact_sha256}"]


def test_satellite_redownloads_exact_size_corrupt_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key, keyring = _keys(tmp_path)
    payload = _artifact(tmp_path, private_key)
    artifact_uri = str(payload["artifact_uri"])
    artifact = Path(urllib.request.url2pathname(artifact_uri[len("file://") :])).read_bytes()
    manifest = ReleaseManifest.from_payload(payload, allow_local_file_artifacts=True)
    manager = _manager(tmp_path, keyring)
    manager.gateway_cache_base_url = "http://10.42.0.1:8091"
    destination = tmp_path / "cached.tar"
    destination.write_bytes(b"x" * len(artifact))

    class Response(io.BytesIO):
        status = 200

    monkeypatch.setattr(
        "agent.local_ota.urllib.request.urlopen",
        lambda *_a, **_k: Response(artifact),
    )
    manager._download(manifest, destination)

    assert destination.read_bytes() == artifact


@pytest.mark.parametrize(
    "url",
    [
        "https://10.42.0.1:8091",
        "http://127.0.0.1:8091",
        "http://10.42.0.1",
        "http://gateway.local:8091",
        "http://10.42.0.1:8091/path",
    ],
)
def test_satellite_rejects_unsafe_gateway_cache_urls(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("EDGEWATCH_OTA_GATEWAY_CACHE_URL", url)
    with pytest.raises(OtaError, match="GATEWAY_CACHE_URL"):
        LocalOtaManager.from_env("camera-1")


def test_manifest_signature_binds_uri_hash_identity_key_and_compatibility(tmp_path: Path) -> None:
    private_key, keyring = _keys(tmp_path)
    manager = _manager(tmp_path, keyring)
    payload = _artifact(tmp_path, private_key)
    for field, replacement in (
        ("artifact_uri", "file:///tmp/attacker.tar"),
        ("artifact_sha256", "0" * 64),
        ("git_tag", "v9.9.9"),
        ("signature_key_id", "attacker"),
        ("runtime_dependency_sha256", "0" * 64),
    ):
        tampered = dict(payload)
        tampered[field] = replacement
        result = manager.execute("stage", tampered, f"tamper-{field}")
        assert result["ok"] is False
        assert "signature" in result["reason"] or result["reason"] == "signature key is not installed"
    tampered = dict(payload)
    compatibility = dict(cast(dict[str, object], payload["compatibility"]))
    compatibility["release_channel"] = "attacker"
    tampered["compatibility"] = compatibility
    result = manager.execute("stage", tampered, "tamper-compatibility")
    assert result["ok"] is False
    assert result["reason"] == "manifest signature verification failed"


def test_signature_key_symlink_and_unsafe_release_identifiers_fail_closed(tmp_path: Path) -> None:
    private_key, keyring = _keys(tmp_path)
    payload = _artifact(tmp_path, private_key)
    real_key = keyring / "release.pem"
    moved_key = tmp_path / "moved-public.pem"
    real_key.replace(moved_key)
    real_key.symlink_to(moved_key)
    manager = _manager(tmp_path, keyring)
    result = manager.execute("stage", payload, "symlink-key")
    assert result["ok"] is False
    assert "symbolic link" in result["reason"]

    unsafe = dict(payload)
    unsafe["git_tag"] = "../escape"
    with pytest.raises(OtaError, match="safe identifier"):
        ReleaseManifest.from_payload(unsafe, allow_local_file_artifacts=True)


def test_catalog_is_strict_and_resolves_alias(tmp_path: Path) -> None:
    private_key, _ = _keys(tmp_path)
    payload = _artifact(tmp_path, private_key)
    import yaml

    catalog_path = tmp_path / "catalog.yaml"
    catalog_path.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "releases": {"release-1": payload}, "aliases": {"stable": "release-1"}}
        ),
        encoding="utf-8",
    )
    assert (
        ReleaseCatalog.load(catalog_path, allow_local_file_artifacts=True).resolve("stable").git_tag
        == "v1.2.3"
    )
    catalog_path.write_text("schema_version: 1\nreleases: {}\nunexpected: true\n", encoding="utf-8")
    with pytest.raises(OtaError, match="unknown release catalog"):
        ReleaseCatalog.load(catalog_path)


def test_stage_verify_apply_rollback_and_replay(tmp_path: Path) -> None:
    private_key, keyring = _keys(tmp_path)
    payload = _artifact(tmp_path, private_key)
    manager = _manager(tmp_path, keyring)

    staged = manager.execute("stage", payload, "command-stage")
    assert staged["status"] == "staged"
    assert manager.execute("stage", payload, "command-stage") == staged
    assert stat_mode(manager.state_path) == 0o600

    applied = manager.execute("apply", payload, "command-apply")
    assert applied["status"] == "applied"
    assert manager.current_symlink.is_symlink()

    other = manager.releases_root / "old"
    other.mkdir()
    manager.current_symlink.unlink()
    manager.current_symlink.symlink_to(other)
    second_payload = dict(payload)
    second_payload["version"] = "1.2.4"
    second_payload["git_tag"] = "v1.2.4"
    _sign_manifest(second_payload, private_key, tmp_path)
    manager.execute("stage", second_payload, "second-stage")
    manager.execute("apply", second_payload, "second-apply")
    rolled_back = manager.execute("rollback", None, "rollback")
    assert rolled_back["status"] == "rolled_back"
    assert manager.current_symlink.resolve() == other

    changed = dict(payload)
    changed["version"] = "9.9.9"
    with pytest.raises(OtaError, match="different input"):
        manager.execute("stage", changed, "command-stage")


def test_bad_hash_signature_and_traversal_fail_closed(tmp_path: Path) -> None:
    private_key, keyring = _keys(tmp_path)
    manager = _manager(tmp_path, keyring)
    payload = _artifact(tmp_path, private_key)
    bad_hash = dict(payload)
    bad_hash["artifact_sha256"] = "0" * 64
    assert manager.execute("stage", bad_hash, "bad-hash")["ok"] is False

    bad_signature = dict(payload)
    bad_signature["artifact_signature"] = base64.b64encode(b"invalid").decode()
    assert manager.execute("stage", bad_signature, "bad-signature")["ok"] is False

    traversal_payload = _artifact(tmp_path, private_key, traversal=True)
    traversal_result = manager.execute("stage", traversal_payload, "traversal")
    assert traversal_result["ok"] is False
    assert not (tmp_path / "escape").exists()


def test_application_dependency_fingerprint_must_match_installed_runtime(tmp_path: Path) -> None:
    private_key, keyring = _keys(tmp_path)
    payload = _artifact(tmp_path, private_key)
    manager = _manager(tmp_path, keyring)
    assert manager.execute("stage", payload, "dependency-match")["status"] == "staged"

    assert manager.runtime_dependency_path is not None
    manager.runtime_dependency_path.write_text("requests==9.9.9\n", encoding="utf-8")
    result = manager.execute("stage", payload, "dependency-mismatch")
    assert result == {
        "ok": False,
        "action": "stage",
        "status": "failed",
        "reason": "runtime_dependency_incompatible",
    }

    manager.runtime_dependency_path.write_text("requests==2.32.4\n", encoding="utf-8")
    assert manager.execute("stage", payload, "dependency-apply-stage")["status"] == "staged"
    manager.runtime_dependency_path.write_text("requests==9.9.9\n", encoding="utf-8")
    applied = manager.execute("apply", payload, "dependency-apply")
    assert applied["reason"] == "runtime_dependency_incompatible"
    assert not manager.current_symlink.exists()


def test_power_guard_and_system_image_apply_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    private_key, keyring = _keys(tmp_path)
    manager = _manager(tmp_path, keyring)
    payload = _artifact(tmp_path, private_key)
    compatibility = dict(cast(dict[str, object], payload["compatibility"]))
    compatibility["requires_stable_power"] = True
    payload["compatibility"] = compatibility
    _sign_manifest(payload, private_key, tmp_path)
    monkeypatch.setenv("EDGEWATCH_POWER_UNSUSTAINABLE", "1")
    result = manager.execute("stage", payload, "power")
    assert result["ok"] is False
    assert result["reason"] == "power_incompatible"

    monkeypatch.delenv("EDGEWATCH_POWER_UNSUSTAINABLE")
    system_payload = dict(payload)
    system_payload["update_type"] = "system_image"
    system_payload["artifact_uri"] = Path(str(payload["artifact_uri"])[7:]).as_uri()
    _sign_manifest(system_payload, private_key, tmp_path)
    staged = manager.execute("stage", system_payload, "system-stage")
    assert staged["status"] == "staged"
    applied = manager.execute("apply", system_payload, "system-apply")
    assert applied["ok"] is False
    assert "hardware qualification" in applied["reason"]


def test_pi_power_guard_requires_fresh_healthy_durable_evidence(tmp_path: Path) -> None:
    private_key, keyring = _keys(tmp_path)
    payload = _artifact(tmp_path, private_key)
    compatibility = dict(cast(dict[str, object], payload["compatibility"]))
    compatibility["hardware_models"] = ["raspberry-pi-5"]
    payload["compatibility"] = compatibility
    _sign_manifest(payload, private_key, tmp_path)
    manager = _manager(tmp_path, keyring)
    manager.hardware_model = "raspberry-pi-5"
    manager.power_state_path = tmp_path / "power-state.json"
    manager.wall_time = lambda: 1_000.0

    missing = manager.execute("stage", payload, "power-missing")
    assert missing["reason"] == "power_incompatible: live power evidence is unavailable"

    manager.power_state_path.write_text(
        json.dumps(
            {
                "last_evaluation": {
                    "ts": 500.0,
                    "evidence": "input_voltage",
                    "power_input_out_of_range": False,
                    "power_unsustainable": False,
                    "power_saver_active": False,
                }
            }
        ),
        encoding="utf-8",
    )
    stale = manager.execute("stage", payload, "power-stale")
    assert stale["reason"] == "power_incompatible: live power evidence is stale"

    power_state = json.loads(manager.power_state_path.read_text(encoding="utf-8"))
    power_state["last_evaluation"]["ts"] = 999.0
    power_state["last_evaluation"]["power_unsustainable"] = True
    manager.power_state_path.write_text(json.dumps(power_state), encoding="utf-8")
    unhealthy = manager.execute("stage", payload, "power-unhealthy")
    assert unhealthy["reason"] == "power_incompatible"

    power_state["last_evaluation"]["power_unsustainable"] = False
    manager.power_state_path.write_text(json.dumps(power_state), encoding="utf-8")
    assert manager.execute("stage", payload, "power-healthy")["status"] == "staged"


@pytest.mark.parametrize(
    ("returncode", "stdout", "reason"),
    [
        (0, "throttled=0x0\n", None),
        (0, "throttled=0x50000\n", "power_incompatible"),
        (1, "", "power_incompatible: live Pi power evidence is invalid"),
        (0, "unexpected\n", "power_incompatible: live Pi power evidence is invalid"),
    ],
)
def test_pi_power_guard_uses_vcgencmd_when_snapshot_has_no_sensor_evidence(
    tmp_path: Path, returncode: int, stdout: str, reason: str | None
) -> None:
    private_key, keyring = _keys(tmp_path)
    payload = _artifact(tmp_path, private_key)
    compatibility = dict(cast(dict[str, object], payload["compatibility"]))
    compatibility["hardware_models"] = ["raspberry-pi-5"]
    payload["compatibility"] = compatibility
    _sign_manifest(payload, private_key, tmp_path)
    manager = _manager(tmp_path, keyring)
    manager.hardware_model = "raspberry-pi-5"
    manager.power_state_path = tmp_path / "power-state.json"
    manager.power_state_path.write_text(
        json.dumps(
            {
                "last_evaluation": {
                    "ts": 999.0,
                    "evidence": "none",
                    "power_input_out_of_range": False,
                    "power_unsustainable": False,
                    "power_saver_active": False,
                }
            }
        ),
        encoding="utf-8",
    )
    manager.wall_time = lambda: 1_000.0
    manager.run_command = lambda *_args, **_kwargs: SimpleNamespace(returncode=returncode, stdout=stdout)

    result = manager.execute("stage", payload, f"vcgencmd-{returncode}-{stdout}")
    if reason is None:
        assert result["status"] == "staged"
    else:
        assert result["reason"] == reason


def test_stage_fsyncs_release_tree_and_parent_around_atomic_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key, keyring = _keys(tmp_path)
    payload = _artifact(tmp_path, private_key)
    manager = _manager(tmp_path, keyring)
    fsync_calls: list[int] = []
    real_fsync = os.fsync

    def record_fsync(fd: int) -> None:
        fsync_calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", record_fsync)
    assert manager.execute("stage", payload, "durable-stage")["status"] == "staged"
    assert len(fsync_calls) >= 5


def test_application_apply_flag_defaults_disabled_but_stage_remains_allowed(
    tmp_path: Path,
) -> None:
    private_key, keyring = _keys(tmp_path)
    runtime = _AgentRuntime()
    manager = _manager(tmp_path, keyring, runtime)
    manager.apply_enabled = False
    payload = _artifact(tmp_path, private_key)

    assert manager.execute("stage", payload, "disabled-stage")["status"] == "staged"
    applied = manager.execute("apply", payload, "disabled-apply")
    assert applied["ok"] is False
    assert applied["reason"] == "OTA apply is disabled by EDGEWATCH_ENABLE_OTA_APPLY"
    assert not manager.current_symlink.exists()
    assert runtime.restarts == 0


def test_from_env_reads_explicit_apply_enablement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EDGEWATCH_ENABLE_OTA_APPLY", raising=False)
    assert LocalOtaManager.from_env().apply_enabled is False
    monkeypatch.setenv("EDGEWATCH_ENABLE_OTA_APPLY", "1")
    assert LocalOtaManager.from_env().apply_enabled is True


def test_typed_local_control_adapter_resolves_only_catalog_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key, keyring = _keys(tmp_path)
    payload = _artifact(tmp_path, private_key)
    import yaml

    catalog_path = tmp_path / "catalog.yaml"
    catalog_path.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "releases": {"release-1": payload}, "aliases": {"stable": "release-1"}}
        ),
        encoding="utf-8",
    )
    manager = _manager(tmp_path, keyring)
    monkeypatch.setenv("EDGEWATCH_OTA_RELEASE_CATALOG", str(catalog_path))
    result = manager.handle_command(
        command_type="ota_stage",
        args={"release_alias": "stable", "manifest": payload},
        command_id="typed-stage",
    )
    assert result["status"] == "staged"
    mismatched = dict(payload)
    mismatched["version"] = "9.9.9"
    with pytest.raises(OtaError, match="exactly match"):
        manager.handle_command(
            command_type="ota_stage",
            args={"release_alias": "stable", "manifest": mismatched},
            command_id="typed-mismatch",
        )
    assert (
        manager.handle_command(command_type="ota_abort", args={}, command_id="typed-abort")["status"]
        == "aborted"
    )
    with pytest.raises(OtaError, match="must not be a URL"):
        manager.handle_command(
            command_type="ota_stage",
            args={"release_alias": "https://evil.example/payload", "manifest": payload},
            command_id="typed-url",
        )


def test_typed_stage_accepts_controller_manifest_without_device_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key, keyring = _keys(tmp_path)
    payload = _artifact(tmp_path, private_key)
    manager = _manager(tmp_path, keyring)
    monkeypatch.delenv("EDGEWATCH_OTA_RELEASE_CATALOG", raising=False)
    result = manager.handle_command(
        command_type="ota_stage",
        args={"release_alias": "stable", "manifest": payload},
        command_id="controller-manifest",
    )
    assert result["status"] == "staged"


def test_application_readiness_failure_restores_previous_release_and_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key, keyring = _keys(tmp_path)
    runtime = _AgentRuntime()
    manager = _manager(tmp_path, keyring, runtime)
    previous = tmp_path / "releases" / "previous"
    previous.mkdir(parents=True)
    manager.current_symlink.symlink_to(previous)
    payload = _artifact(tmp_path, private_key)
    assert manager.execute("stage", payload, "readiness-stage")["ok"] is True

    probe_calls = 0

    def fail_new_release_once() -> tuple[int, str]:
        nonlocal probe_calls
        probe_calls += 1
        # Initial snapshot succeeds.  Every probe after the first restart fails;
        # the rollback restart then receives a stable receipt.
        if runtime.restarts == 1:
            raise OtaError("new release never became ready")
        return runtime.ready()

    manager.readiness_probe = fail_new_release_once
    manager.monotonic = lambda: 0.0
    monkeypatch.setenv("EDGEWATCH_OTA_READY_TIMEOUT_S", "0")
    monkeypatch.setenv("EDGEWATCH_OTA_READY_STABILITY_S", "0")
    # Transient readiness failures escape uncached so the outer command ledger
    # can retry the same command_id after the host recovers.
    with pytest.raises(RetryableOtaError, match="previous release restored"):
        manager.execute("apply", payload, "readiness-apply")
    assert manager.current_symlink.resolve() == previous
    assert runtime.restarts == 2
    state = json.loads(manager.state_path.read_text(encoding="utf-8"))
    assert "readiness-apply" not in state["commands"]


def test_camera_application_activation_uses_fixed_check_receipt_and_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key, keyring = _keys(tmp_path)
    manager = _manager(tmp_path, keyring)
    manager.runtime_profile = "camera-satellite"
    manager.device_id = "camera-1"
    manager.camera_readiness_owner_uid = os.getuid()
    manager.wall_time = lambda: 1_000.0
    previous = manager.releases_root / "previous"
    previous.mkdir(parents=True)
    manager.current_symlink.symlink_to(previous)
    ready_path = tmp_path / "camera-ready.json"
    monkeypatch.setattr("agent.local_ota._CAMERA_READY_PATH", ready_path)
    runtime = _CameraRuntime(manager, ready_path, fail_call=2)
    manager.run_command = runtime.run
    runtime.write_ready()
    payload = _artifact(tmp_path, private_key)
    assert manager.execute("stage", payload, "camera-stage")["status"] == "staged"
    monkeypatch.setenv("EDGEWATCH_AGENT_SYSTEMD_SERVICE", "attacker.service")
    monkeypatch.setenv("EDGEWATCH_OTA_READY_STABILITY_S", "0")

    with pytest.raises(RetryableOtaError, match="previous release restored"):
        manager.execute("apply", payload, "camera-apply")

    assert manager.current_symlink.resolve() == previous
    assert (
        runtime.commands.count(["/usr/bin/systemctl", "start", "edgewatch-camera-satellite@check.service"])
        == 3
    )
    assert all("attacker.service" not in command for command in runtime.commands)
    applied = manager.execute("apply", payload, "camera-apply")
    assert applied["status"] == "applied"
    assert json.loads(ready_path.read_text(encoding="utf-8"))["application_target"] == str(
        manager.current_symlink.resolve()
    )
    rolled_back = manager.execute("rollback", None, "camera-rollback")
    assert rolled_back["status"] == "rolled_back"
    assert manager.current_symlink.resolve() == previous
    assert json.loads(ready_path.read_text(encoding="utf-8"))["application_target"] == str(previous.resolve())


class _SimulatedProcessDeath(BaseException):
    pass


def test_apply_recovery_rolls_back_crash_after_symlink_swap_before_phase_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key, keyring = _keys(tmp_path)
    runtime = _AgentRuntime()
    manager = _manager(tmp_path, keyring, runtime)
    previous = tmp_path / "releases" / "previous"
    previous.mkdir(parents=True)
    manager.current_symlink.symlink_to(previous)
    payload = _artifact(tmp_path, private_key)
    assert manager.execute("stage", payload, "crash-swap-stage")["status"] == "staged"

    real_write = manager._write_apply_journal

    def die_before_switched_journal(journal: object) -> None:
        if isinstance(journal, dict) and journal.get("phase") == "switched":
            raise _SimulatedProcessDeath
        real_write(cast(dict[str, object], journal))

    monkeypatch.setattr(manager, "_write_apply_journal", die_before_switched_journal)
    with pytest.raises(_SimulatedProcessDeath):
        manager.execute("apply", payload, "crash-swap-apply")
    assert manager.current_symlink.resolve() != previous

    recovered = _manager(tmp_path, keyring, runtime)
    status = recovered.execute("status", None, "status-after-swap-crash")
    assert status["status"] == "ok"
    assert recovered.current_symlink.resolve() == previous
    assert not recovered._apply_journal_path.exists()

    applied = recovered.execute("apply", payload, "crash-swap-apply")
    assert applied["status"] == "applied"
    assert json.loads(recovered.state_path.read_text(encoding="utf-8"))["previous_target"] == str(
        previous.resolve()
    )
    rolled_back = recovered.execute("rollback", None, "rollback-after-recovery")
    assert rolled_back["status"] == "rolled_back"
    assert recovered.current_symlink.resolve() == previous


def test_camera_apply_recovery_restarts_and_verifies_prior_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key, keyring = _keys(tmp_path)
    manager = _manager(tmp_path, keyring)
    manager.runtime_profile = "camera-satellite"
    manager.device_id = "camera-1"
    manager.camera_readiness_owner_uid = os.getuid()
    manager.wall_time = lambda: 1_000.0
    previous = manager.releases_root / "previous"
    previous.mkdir(parents=True)
    manager.current_symlink.symlink_to(previous)
    ready_path = tmp_path / "camera-ready.json"
    monkeypatch.setattr("agent.local_ota._CAMERA_READY_PATH", ready_path)
    runtime = _CameraRuntime(manager, ready_path)
    manager.run_command = runtime.run
    runtime.write_ready()
    payload = _artifact(tmp_path, private_key)
    assert manager.execute("stage", payload, "camera-crash-stage")["status"] == "staged"
    monkeypatch.setenv("EDGEWATCH_OTA_READY_STABILITY_S", "0")
    real_write = manager._write_apply_journal

    def die_before_switched_journal(journal: object) -> None:
        if isinstance(journal, dict) and journal.get("phase") == "switched":
            raise _SimulatedProcessDeath
        real_write(cast(dict[str, object], journal))

    monkeypatch.setattr(manager, "_write_apply_journal", die_before_switched_journal)
    with pytest.raises(_SimulatedProcessDeath):
        manager.execute("apply", payload, "camera-crash-apply")

    recovered = _manager(tmp_path, keyring)
    recovered.runtime_profile = "camera-satellite"
    recovered.device_id = "camera-1"
    recovered.camera_readiness_owner_uid = os.getuid()
    recovered.wall_time = lambda: 1_000.0
    recovered.run_command = runtime.run
    assert recovered.execute("status", None, "camera-recovered")["status"] == "ok"
    assert recovered.current_symlink.resolve() == previous
    assert json.loads(ready_path.read_text(encoding="utf-8"))["application_target"] == str(previous.resolve())
    assert ["/usr/bin/systemctl", "start", "edgewatch-camera-satellite@check.service"] in runtime.commands
    assert not recovered._apply_journal_path.exists()


def test_apply_recovery_commits_verified_result_after_process_death_before_state_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key, keyring = _keys(tmp_path)
    runtime = _AgentRuntime()
    manager = _manager(tmp_path, keyring, runtime)
    previous = tmp_path / "releases" / "previous"
    previous.mkdir(parents=True)
    manager.current_symlink.symlink_to(previous)
    payload = _artifact(tmp_path, private_key)
    assert manager.execute("stage", payload, "crash-commit-stage")["status"] == "staged"

    real_save = manager._save_state
    save_calls = 0

    def die_before_final_state(state: object) -> None:
        nonlocal save_calls
        save_calls += 1
        if save_calls == 1:
            raise _SimulatedProcessDeath
        real_save(cast(dict[str, object], state))

    monkeypatch.setattr(manager, "_save_state", die_before_final_state)
    with pytest.raises(_SimulatedProcessDeath):
        manager.execute("apply", payload, "crash-commit-apply")
    assert runtime.restarts == 1
    journal = json.loads(manager._apply_journal_path.read_text(encoding="utf-8"))
    assert journal["phase"] == "verified"
    assert stat_mode(manager._apply_journal_path) == 0o600

    recovered = _manager(tmp_path, keyring, runtime)
    replay = recovered.execute("apply", payload, "crash-commit-apply")
    assert replay["status"] == "applied"
    assert runtime.restarts == 1
    state = json.loads(recovered.state_path.read_text(encoding="utf-8"))
    assert state["previous_target"] == str(previous.resolve())
    assert state["current_target"] == str(recovered.current_symlink.resolve())
    assert not recovered._apply_journal_path.exists()


def test_first_apply_recovery_finishes_safely_when_no_previous_release_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key, keyring = _keys(tmp_path)
    runtime = _AgentRuntime()
    manager = _manager(tmp_path, keyring, runtime)
    payload = _artifact(tmp_path, private_key)
    assert manager.execute("stage", payload, "first-crash-stage")["status"] == "staged"
    real_write = manager._write_apply_journal

    def die_after_first_switch(journal: object) -> None:
        if isinstance(journal, dict) and journal.get("phase") == "switched":
            raise _SimulatedProcessDeath
        real_write(cast(dict[str, object], journal))

    monkeypatch.setattr(manager, "_write_apply_journal", die_after_first_switch)
    with pytest.raises(_SimulatedProcessDeath):
        manager.execute("apply", payload, "first-crash-apply")
    assert runtime.restarts == 0

    recovered = _manager(tmp_path, keyring, runtime)
    replay = recovered.execute("apply", payload, "first-crash-apply")
    assert replay["status"] == "applied"
    assert runtime.restarts == 1
    state = json.loads(recovered.state_path.read_text(encoding="utf-8"))
    assert state["previous_target"] is None
    assert state["current_target"] == str(recovered.current_symlink.resolve())
    assert not recovered._apply_journal_path.exists()


def test_apply_recovery_is_idempotent_after_state_save_before_journal_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key, keyring = _keys(tmp_path)
    runtime = _AgentRuntime()
    manager = _manager(tmp_path, keyring, runtime)
    previous = tmp_path / "releases" / "previous"
    previous.mkdir(parents=True)
    manager.current_symlink.symlink_to(previous)
    payload = _artifact(tmp_path, private_key)
    assert manager.execute("stage", payload, "crash-clear-stage")["status"] == "staged"

    monkeypatch.setattr(
        manager,
        "_clear_apply_journal",
        lambda: (_ for _ in ()).throw(_SimulatedProcessDeath()),
    )
    with pytest.raises(_SimulatedProcessDeath):
        manager.execute("apply", payload, "crash-clear-apply")
    committed_before_recovery = manager.state_path.read_bytes()

    recovered = _manager(tmp_path, keyring, runtime)
    replay = recovered.execute("apply", payload, "crash-clear-apply")
    assert replay["status"] == "applied"
    assert runtime.restarts == 1
    assert recovered.state_path.read_bytes() == committed_before_recovery
    assert not recovered._apply_journal_path.exists()


@pytest.mark.parametrize(
    "journal",
    [
        b"not-json",
        json.dumps(
            {
                "schema_version": 1,
                "phase": "switched",
                "original_target": "/opt/edgewatch/releases/old",
                "current_target": "/tmp/outside-release-root",
                "command_id": "malformed",
                "fingerprint": "0" * 64,
            }
        ).encode(),
    ],
)
def test_apply_recovery_fails_closed_on_malformed_or_inconsistent_journal(
    tmp_path: Path, journal: bytes
) -> None:
    _, keyring = _keys(tmp_path)
    manager = _manager(tmp_path, keyring)
    manager._apply_journal_path.write_bytes(journal)
    manager._apply_journal_path.chmod(0o600)

    with pytest.raises(OtaError, match="invalid local OTA apply journal"):
        manager.execute("status", None, "journal-fail-closed")
    assert manager._apply_journal_path.exists()


def test_apply_recovery_fails_closed_when_verified_journal_disagrees_with_symlink(tmp_path: Path) -> None:
    private_key, keyring = _keys(tmp_path)
    manager = _manager(tmp_path, keyring)
    payload = _artifact(tmp_path, private_key)
    previous = manager.releases_root / "previous"
    target = manager.releases_root / "target"
    previous.mkdir(parents=True)
    target.mkdir()
    manager.current_symlink.symlink_to(previous)
    fingerprint = "0" * 64
    result = {"ok": True, "action": "apply", "status": "applied"}
    committed_state = {
        "schema_version": 1,
        "commands": {"inconsistent": {"fingerprint": fingerprint, "result": result}},
        "previous_target": str(previous.resolve()),
        "current_target": str(target.resolve()),
        "active": {"identity": "release"},
    }
    manager._write_apply_journal(
        {
            "schema_version": 1,
            "phase": "verified",
            "original_target": str(previous.resolve()),
            "current_target": str(target.resolve()),
            "command_id": "inconsistent",
            "fingerprint": fingerprint,
            "manifest": payload,
            "committed_state": committed_state,
        }
    )

    with pytest.raises(OtaError, match="does not match the current release target"):
        manager.execute("status", None, "inconsistent-status")
    assert manager.current_symlink.resolve() == previous
    assert manager._apply_journal_path.exists()


def test_transient_download_failure_is_retryable_and_not_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_key, keyring = _keys(tmp_path)
    payload = _artifact(tmp_path, private_key)
    payload["artifact_uri"] = "https://downloads.example.invalid/release.tar"
    _sign_manifest(payload, private_key, tmp_path)
    manager = _manager(tmp_path, keyring)
    manager.allow_local_file_artifacts = False

    def unavailable(*_args: object, **_kwargs: object) -> object:
        raise OSError("offline")

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    with pytest.raises(RetryableOtaError, match="download failed") as raised:
        manager.execute("stage", payload, "retry-download")
    assert raised.value.retryable is True
    assert raised.value.max_attempts == 3
    if manager.state_path.exists():
        state = json.loads(manager.state_path.read_text(encoding="utf-8"))
        assert "retry-download" not in state["commands"]


def stat_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777
