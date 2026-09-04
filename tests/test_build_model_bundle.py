from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from agent.inference.bundle import ModelBundleManager
from agent.local_ota import ReleaseCatalog
from scripts import apply_model_bundle
from scripts.apply_model_bundle import _activation_source, _readiness
from scripts.build_model_bundle import build_model_release


def _json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "models"
    source.mkdir()
    (source / "vision.tflite").write_bytes(b"fully-quantized-vision")
    (source / "audio.tflite").write_bytes(b"fully-quantized-audio")
    _json(
        source / "labels.json",
        {
            "schema_version": 1,
            "vision": ["running", "stopped", "fault", "unknown"],
            "audio": ["normal", "anomaly"],
        },
    )
    _json(
        source / "preprocessing.json",
        {
            "schema_version": 1,
            "vision": {
                "schema_version": 1,
                "layout": "nhwc",
                "width": 96,
                "height": 96,
                "channels": 3,
                "resize_filter": "bilinear",
                "value_scale": 1 / 255,
                "value_offset": 0.0,
            },
            "audio": {
                "schema_version": 1,
                "layout": "nhwc",
                "feature": "log_mel",
                "sample_rate_hz": 16000,
                "sample_count": 16000,
                "window_samples": 512,
                "hop_samples": 256,
                "fft_size": 512,
                "mel_bins": 32,
                "lower_hz": 80.0,
                "upper_hz": 7600.0,
                "log_floor": 1e-10,
                "window": "hann",
                "log_base": "e",
            },
        },
    )
    _json(
        source / "thresholds.json",
        {
            "schema_version": 1,
            "minimum_state_confidence": 0.8,
            "minimum_state_margin": 0.15,
            "fault_audio_threshold": 0.85,
            "fault_visual_threshold": 0.85,
            "minimum_alert_confidence": 0.9,
            "consecutive_required": 2,
        },
    )
    _json(
        source / "known_answer.json",
        {
            "schema_version": 1,
            "cases": [
                {
                    "model": "vision",
                    "input": [1],
                    "expected_label": "running",
                    "minimum_score": 0.8,
                },
                {
                    "model": "audio",
                    "input": [2],
                    "expected_label": "normal",
                    "minimum_score": 0.8,
                },
            ],
        },
    )
    return source


def _keys(tmp_path: Path) -> tuple[Path, Path]:
    private = tmp_path / "models.pem"
    public = tmp_path / "models.pub.pem"
    subprocess.run(
        ["openssl", "genrsa", "-out", str(private), "2048"],
        check=True,
        capture_output=True,
    )
    private.chmod(0o600)
    subprocess.run(
        ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
        check=True,
        capture_output=True,
    )
    return private, public


def test_build_model_release_is_reproducible_and_controller_compatible(tmp_path: Path) -> None:
    source = _source(tmp_path)
    private, public = _keys(tmp_path)
    outputs = []
    for index in range(2):
        outputs.append(
            build_model_release(
                source_dir=source,
                output_dir=tmp_path / f"out-{index}",
                private_key=private,
                key_id="models-prod",
                artifact_uri="https://releases.example/edgewatch-model_1.0.0.tar.gz",
                version="1.0.0",
            )
        )

    first_artifact, _signature, first_catalog = outputs[0]
    second_artifact, _signature2, second_catalog = outputs[1]
    assert first_artifact.read_bytes() == second_artifact.read_bytes()
    assert first_catalog.read_bytes() == second_catalog.read_bytes()

    catalog = ReleaseCatalog.load(first_catalog)
    release = catalog.resolve("model-1.0.0")
    assert release.update_type == "asset_bundle"
    assert release.compatibility["hardware_models"] == ["raspberry-pi-zero-2"]
    assert release.artifact_sha256 == hashlib.sha256(first_artifact.read_bytes()).hexdigest()

    extracted = tmp_path / "extracted"
    with tarfile.open(first_artifact) as archive:
        archive.extractall(extracted, filter="data")
    keyring = tmp_path / "keyring"
    keyring.mkdir()
    installed_key = keyring / "models-prod.pem"
    installed_key.write_bytes(public.read_bytes())
    installed_key.chmod(0o644)
    bundle = ModelBundleManager(
        releases_root=tmp_path / "releases",
        current_symlink=tmp_path / "current",
        keyring_dir=keyring,
        hardware_model="raspberry-pi-zero-2",
    ).validate(extracted)
    assert bundle.manifest.version == "1.0.0"


def test_build_model_release_rejects_extra_files_and_loose_private_key(tmp_path: Path) -> None:
    source = _source(tmp_path)
    private, _public = _keys(tmp_path)
    (source / "notes.txt").write_text("not signed", encoding="utf-8")

    with pytest.raises(ValueError, match="exactly"):
        build_model_release(
            source_dir=source,
            output_dir=tmp_path / "out",
            private_key=private,
            key_id="models-prod",
            artifact_uri="https://releases.example/model.tar.gz",
            version="1.0.0",
        )

    (source / "notes.txt").unlink()
    private.chmod(0o640)
    with pytest.raises(ValueError, match="0600"):
        build_model_release(
            source_dir=source,
            output_dir=tmp_path / "out",
            private_key=private,
            key_id="models-prod",
            artifact_uri="https://releases.example/model.tar.gz",
            version="1.0.0",
        )


def test_outer_asset_stage_marker_is_excluded_but_other_unsigned_files_fail(tmp_path: Path) -> None:
    source = _source(tmp_path)
    private, public = _keys(tmp_path)
    artifact, _signature, _catalog = build_model_release(
        source_dir=source,
        output_dir=tmp_path / "out",
        private_key=private,
        key_id="models-prod",
        artifact_uri="https://releases.example/model.tar.gz",
        version="1.0.0",
    )
    extracted = tmp_path / "outer-asset-stage"
    with tarfile.open(artifact) as archive:
        archive.extractall(extracted, filter="data")
    (extracted / ".edgewatch-release.json").write_text(
        json.dumps({"artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}),
        encoding="utf-8",
    )
    keyring = tmp_path / "keyring"
    keyring.mkdir()
    (keyring / "models-prod.pem").write_bytes(public.read_bytes())
    manager = ModelBundleManager(
        releases_root=tmp_path / "releases",
        current_symlink=tmp_path / "current",
        keyring_dir=keyring,
        hardware_model="raspberry-pi-zero-2",
    )

    with _activation_source(extracted) as clean:
        staged = manager.stage(clean)
    activated = manager.activate(
        staged.manifest.version,
        known_answer_runner=lambda _bundle: True,
        readiness_probe=lambda _bundle: True,
    )
    assert activated.version == "1.0.0"
    assert manager.load_active().manifest.version == "1.0.0"

    (extracted / "unsigned-note.txt").write_text("must fail", encoding="utf-8")
    with _activation_source(extracted) as clean, pytest.raises(Exception, match="inventory"):
        manager.validate(clean)


def test_model_readiness_runs_supervised_check_and_validates_private_result(tmp_path: Path) -> None:
    identity = "a" * 64
    result_path = tmp_path / "result.json"
    seen: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        result_path.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "mode": "check",
                    "manifest_identity": identity,
                    "poweroff_requested": False,
                }
            ),
            encoding="utf-8",
        )
        os.chmod(result_path, 0o600)
        return subprocess.CompletedProcess(command, 0, "", "")

    assert _readiness(identity, run_command=run, result_path=result_path)
    assert seen == [["/usr/bin/systemctl", "start", "edgewatch-camera-satellite@check.service"]]


def test_recover_only_resolves_activation_before_camera_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Manager:
        def recover_interrupted_activation(self) -> bool:
            return True

    monkeypatch.setattr(apply_model_bundle, "_manager", Manager)
    monkeypatch.setattr(apply_model_bundle, "_ACTIVATION_LOCK", tmp_path / "activation.lock")

    assert apply_model_bundle.main(["--recover-only"]) == 0
    assert json.loads(capsys.readouterr().out) == {"recovered": True, "status": "ok"}


def test_recover_only_defers_while_live_activation_holds_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lock_path = tmp_path / "activation.lock"
    monkeypatch.setattr(apply_model_bundle, "_ACTIVATION_LOCK", lock_path)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert apply_model_bundle.main(["--recover-only"]) == 0
    finally:
        os.close(descriptor)
    assert json.loads(capsys.readouterr().out) == {"recovered": False, "status": "deferred"}


def test_model_readiness_rejects_stale_wrong_or_public_result(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"

    def wrong(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        result_path.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "mode": "check",
                    "manifest_identity": "b" * 64,
                    "poweroff_requested": False,
                }
            ),
            encoding="utf-8",
        )
        os.chmod(result_path, 0o600)
        return subprocess.CompletedProcess(command, 0, "", "")

    assert not _readiness("a" * 64, run_command=wrong, result_path=result_path)

    def public(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        result_path.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "mode": "check",
                    "manifest_identity": "a" * 64,
                    "poweroff_requested": False,
                }
            ),
            encoding="utf-8",
        )
        os.chmod(result_path, 0o644)
        return subprocess.CompletedProcess(command, 0, "", "")

    assert not _readiness("a" * 64, run_command=public, result_path=result_path)
