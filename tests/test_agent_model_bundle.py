from __future__ import annotations

import base64
import hashlib
import json
import stat
from pathlib import Path
from typing import Any

import pytest

from agent.inference.bundle import (
    ModelActivationError,
    ModelBundleError,
    ModelBundleManager,
    canonical_model_manifest_bytes,
)


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _build_bundle(
    root: Path,
    *,
    version: str,
    hardware_model: str = "raspberry-pi-zero-2",
    known_answer_input: int = 1,
) -> Path:
    source = root / f"source-{version}"
    source.mkdir(parents=True)
    payloads = {
        "vision_model": ("models/vision.tflite", b"quantized-vision-model"),
        "audio_model": ("models/audio.tflite", b"quantized-audio-model"),
        "labels": (
            "config/labels.json",
            _json_bytes(
                {
                    "schema_version": 1,
                    "vision": ["running", "stopped", "fault", "unknown"],
                    "audio": ["normal", "anomaly"],
                }
            ),
        ),
        "preprocessing": (
            "config/preprocessing.json",
            _json_bytes(
                {
                    "schema_version": 1,
                    "vision": {
                        "schema_version": 1,
                        "layout": "nhwc",
                        "width": 96,
                        "height": 96,
                        "channels": 3,
                        "resize_filter": "bilinear",
                        "value_scale": 0.003921568627451,
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
                }
            ),
        ),
        "thresholds": (
            "config/thresholds.json",
            _json_bytes(
                {
                    "schema_version": 1,
                    "minimum_state_confidence": 0.8,
                    "minimum_state_margin": 0.15,
                    "fault_audio_threshold": 0.85,
                    "fault_visual_threshold": 0.85,
                    "minimum_alert_confidence": 0.9,
                    "consecutive_required": 2,
                }
            ),
        ),
        "known_answer": (
            "config/known_answer.json",
            _json_bytes(
                {
                    "schema_version": 1,
                    "cases": [
                        {
                            "model": "vision",
                            "input": [known_answer_input],
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
                }
            ),
        ),
    }
    files: dict[str, dict[str, str | int]] = {}
    for role, (relative, payload) in payloads.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        files[role] = {
            "path": relative,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "version": version,
        "signature_key_id": "models-prod",
        "compatibility": {
            "schema_version": 1,
            "hardware_models": [hardware_model],
            "minimum_litert_version": "2.1.6",
        },
        "files": files,
    }
    signature = hashlib.sha256(canonical_model_manifest_bytes(manifest)).digest()
    manifest["signature"] = base64.b64encode(signature).decode("ascii")
    (source / "manifest.json").write_bytes(_json_bytes(manifest))
    return source


def _manager(tmp_path: Path) -> ModelBundleManager:
    keyring = tmp_path / "keys"
    keyring.mkdir(exist_ok=True)
    (keyring / "models-prod.pem").write_text("test public key", encoding="utf-8")
    return ModelBundleManager(
        releases_root=tmp_path / "releases",
        current_symlink=tmp_path / "active-model",
        keyring_dir=keyring,
        hardware_model="raspberry-pi-zero-2",
        signature_verifier=lambda _key, payload, signature: hashlib.sha256(payload).digest() == signature,
    )


class SimulatedProcessDeath(BaseException):
    pass


def test_model_bundle_stage_validates_closed_signed_schema(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    source = _build_bundle(tmp_path, version="model-1")

    installed = manager.stage(source)

    assert installed.manifest.version == "model-1"
    assert installed.labels["vision"] == ("running", "stopped", "fault", "unknown")
    assert installed.preprocessing["audio"]["layout"] == "nhwc"
    assert installed.thresholds["consecutive_required"] == 2
    assert len(installed.known_answer_cases) == 2
    assert installed.root == (tmp_path / "releases" / "model-1").resolve()
    assert stat.S_IMODE(installed.root.stat().st_mode) == 0o555
    assert all(
        stat.S_IMODE(path.stat().st_mode) == (0o555 if path.is_dir() else 0o444)
        for path in installed.root.rglob("*")
    )

    installed.root.chmod(0o700)
    repaired = manager.stage(source)
    assert repaired.manifest.identity == installed.manifest.identity
    assert stat.S_IMODE(repaired.root.stat().st_mode) == 0o555


@pytest.mark.parametrize("invalid_value", [-129, 128])
def test_model_bundle_rejects_out_of_range_signed_int8_known_answer_values(
    tmp_path: Path,
    invalid_value: int,
) -> None:
    manager = _manager(tmp_path)
    source = _build_bundle(
        tmp_path,
        version="model-1",
        known_answer_input=invalid_value,
    )

    with pytest.raises(ModelBundleError, match="bounded signed int8 vector"):
        manager.stage(source)


def test_model_bundle_rejects_file_tampering_and_extra_files(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    source = _build_bundle(tmp_path, version="model-1")
    (source / "unexpected.txt").write_text("not signed", encoding="utf-8")

    with pytest.raises(ModelBundleError, match="inventory"):
        manager.stage(source)

    (source / "unexpected.txt").unlink()
    (source / "unsigned-empty-directory").mkdir()
    with pytest.raises(ModelBundleError, match="inventory"):
        manager.stage(source)

    (source / "unsigned-empty-directory").rmdir()
    (source / "models" / "vision.tflite").write_bytes(b"tampered")
    with pytest.raises(ModelBundleError, match="size does not match|digest does not match"):
        manager.stage(source)


def test_model_activation_rolls_back_atomic_symlink_on_readiness_failure(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.stage(_build_bundle(tmp_path, version="model-1"))
    manager.stage(_build_bundle(tmp_path, version="model-2"))
    first = manager.activate(
        "model-1",
        known_answer_runner=lambda _bundle: True,
        readiness_probe=lambda _bundle: True,
    )

    assert first.previous_target is None
    assert manager.load_active().manifest.version == "model-1"

    with pytest.raises(ModelActivationError, match="readiness"):
        manager.activate(
            "model-2",
            known_answer_runner=lambda _bundle: True,
            readiness_probe=lambda _bundle: False,
        )

    assert manager.load_active().manifest.version == "model-1"


def test_known_answer_failure_never_switches_active_model(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.stage(_build_bundle(tmp_path, version="model-1"))

    with pytest.raises(ModelActivationError, match="known-answer"):
        manager.activate("model-1", known_answer_runner=lambda _bundle: False)

    assert not (tmp_path / "active-model").exists()


def test_interrupted_symlink_switch_rolls_back_before_model_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    manager.stage(_build_bundle(tmp_path, version="model-1"))
    manager.stage(_build_bundle(tmp_path, version="model-2"))
    manager.activate("model-1", known_answer_runner=lambda _bundle: True)
    original_switch = manager._atomic_symlink

    def switch_then_die(target: Path) -> None:
        original_switch(target)
        raise SimulatedProcessDeath

    monkeypatch.setattr(manager, "_atomic_symlink", switch_then_die)
    with pytest.raises(SimulatedProcessDeath):
        manager.activate("model-2", known_answer_runner=lambda _bundle: True)
    assert (tmp_path / "active-model").resolve().name == "model-2"

    recovered = _manager(tmp_path)
    assert recovered.load_active().manifest.version == "model-1"
    assert not recovered.activation_journal_path.exists()


def test_interrupted_activation_after_readiness_but_before_state_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    manager.stage(_build_bundle(tmp_path, version="model-1"))
    manager.stage(_build_bundle(tmp_path, version="model-2"))
    manager.activate("model-1", known_answer_runner=lambda _bundle: True)

    def state_write_dies(_bundle: object) -> None:
        raise SimulatedProcessDeath

    monkeypatch.setattr(manager, "_write_activation_state", state_write_dies)
    with pytest.raises(SimulatedProcessDeath):
        manager.activate(
            "model-2",
            known_answer_runner=lambda _bundle: True,
            readiness_probe=lambda _bundle: True,
        )

    recovered = _manager(tmp_path)
    assert recovered.load_active().manifest.version == "model-1"


def test_interrupted_activation_after_committed_state_recovers_forward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    manager.stage(_build_bundle(tmp_path, version="model-1"))
    manager.stage(_build_bundle(tmp_path, version="model-2"))
    manager.activate("model-1", known_answer_runner=lambda _bundle: True)

    def journal_clear_dies() -> None:
        raise SimulatedProcessDeath

    monkeypatch.setattr(manager, "_clear_activation_journal", journal_clear_dies)
    with pytest.raises(SimulatedProcessDeath):
        manager.activate(
            "model-2",
            known_answer_runner=lambda _bundle: True,
            readiness_probe=lambda _bundle: True,
        )

    recovered = _manager(tmp_path)
    assert recovered.load_active().manifest.version == "model-2"
    assert not recovered.activation_journal_path.exists()


def test_interrupted_first_activation_removes_unverified_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    manager.stage(_build_bundle(tmp_path, version="model-1"))
    original_switch = manager._atomic_symlink

    def switch_then_die(target: Path) -> None:
        original_switch(target)
        raise SimulatedProcessDeath

    monkeypatch.setattr(manager, "_atomic_symlink", switch_then_die)
    with pytest.raises(SimulatedProcessDeath):
        manager.activate("model-1", known_answer_runner=lambda _bundle: True)

    recovered = _manager(tmp_path)
    with pytest.raises(ModelBundleError, match="no active"):
        recovered.load_active()
    assert not (tmp_path / "active-model").exists()


def test_malformed_activation_journal_fails_closed(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    manager.activation_journal_path.parent.mkdir(parents=True, exist_ok=True)
    manager.activation_journal_path.write_text('{"schema_version":1,"phase":"switched"}\n')
    manager.activation_journal_path.chmod(0o600)

    with pytest.raises(ModelActivationError, match="journal schema"):
        manager.load_active()
