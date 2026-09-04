from __future__ import annotations

import json
import hashlib
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pytest

from agent.camera_satellite_runner import (
    CameraSatelliteRunner,
    SatelliteConfig,
    SatelliteConfigError,
    SatelliteRunError,
)
from agent.inference.bundle import InstalledModelBundle, ModelBundleManifest
from agent.inference.policy import FusionPolicy, ShadowAlertGate
from agent.inference.preprocess import PreprocessedInputs, PreprocessingError
from agent.inference.runtime import EquipmentInferenceRuntime
from agent.media.evidence import CapturedEventEvidence, CapturedInferenceSample, LocalEvidenceStore
from agent.media.rtsp import RtspStreamInfo


class _Classifier:
    def __init__(self, *, kind: str) -> None:
        self.kind = kind

    @property
    def input_shape(self) -> tuple[int, ...]:
        return (1, 1)

    @property
    def input_dtype(self) -> str:
        return "int8"

    @property
    def input_quantization(self) -> tuple[float, int]:
        return (0.1, 0)

    def predict_quantized(self, values: Iterable[int]) -> dict[str, float]:
        assert tuple(values) == (1,)
        if self.kind == "vision":
            return {"running": 0.01, "stopped": 0.01, "fault": 0.96, "unknown": 0.02}
        return {"normal": 0.03, "anomaly": 0.97}


class _Manager:
    def __init__(self, bundle: InstalledModelBundle) -> None:
        self.bundle = bundle

    def load_active(self) -> InstalledModelBundle:
        return self.bundle


class _Camera:
    def is_supported(self) -> bool:
        return True

    def probe(self, *, camera_id: str, timeout_s: float | None = None) -> RtspStreamInfo:
        assert camera_id == "cam1"
        assert timeout_s is not None
        return RtspStreamInfo(video_codec="h264", audio_codec="aac")

    def capture_event(self, *, camera_id: str, timeout_s: float | None = None) -> CapturedEventEvidence:
        assert camera_id == "cam1"
        assert timeout_s is not None
        return CapturedEventEvidence(b"event-jpeg", b"event-wav", b"event-matroska")

    def capture_sample(self, *, camera_id: str, timeout_s: float | None = None) -> CapturedInferenceSample:
        assert camera_id == "cam1"
        assert timeout_s is not None
        return CapturedInferenceSample(b"daily-jpeg", b"transient-wav")


class _Preprocessor:
    def validate_specs(self, **_kwargs: Any) -> None:
        return None

    def preprocess(self, **_kwargs: Any) -> PreprocessedInputs:
        return PreprocessedInputs(vision=(1,), audio=(1,), visual_change=0.9)


class _BrokenPreprocessor(_Preprocessor):
    def validate_specs(self, **_kwargs: Any) -> None:
        raise PreprocessingError("shape drift")


def _bundle(tmp_path: Path) -> InstalledModelBundle:
    manifest = ModelBundleManifest(
        version="model-1",
        signature_key_id="models-prod",
        hardware_models=("raspberry-pi-zero-2",),
        minimum_litert_version="2.1.6",
        files={},
        signature=b"signature",
        raw_payload={"schema_version": 1, "version": "model-1"},
    )
    return InstalledModelBundle(
        root=tmp_path / "model-1",
        manifest=manifest,
        labels={},
        preprocessing={"vision": {}, "audio": {}},
        thresholds={},
        known_answer_cases=(),
    )


def _config(tmp_path: Path, *, inference_mode: str = "shadow") -> SatelliteConfig:
    promotion = tmp_path / "promotion.json"
    if inference_mode == "live":
        promotion.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "held_out_alert_precision": 0.95,
                    "false_alert_count": 1,
                    "device_days": 10,
                }
            ),
            encoding="utf-8",
        )
        promotion.chmod(0o600)
    application_release = tmp_path / "applications" / "release-1"
    application_release.mkdir(parents=True, exist_ok=True)
    application_current = tmp_path / "applications" / "current"
    if not application_current.exists() and not application_current.is_symlink():
        application_current.symlink_to(application_release)
    return SatelliteConfig(
        device_id="satellite-001",
        camera_id="cam1",
        rtsp_endpoint="rtsp://192.0.2.10/substream",
        rtsp_credentials_path=tmp_path / "camera.json",
        model_releases_root=tmp_path / "models" / "releases",
        model_current_symlink=tmp_path / "models" / "current",
        model_keyring_dir=tmp_path / "model-keys",
        application_releases_root=tmp_path / "applications",
        application_current_symlink=application_current,
        hardware_model="raspberry-pi-zero-2",
        litert_version="2.1.6",
        evidence_dir=tmp_path / "evidence",
        evidence_max_bytes=32 * 1024 * 1024,
        result_path=tmp_path / "state" / "result.json",
        ready_path=tmp_path / "state" / "ready.json",
        gate_state_path=tmp_path / "state" / "gate.json",
        lock_path=tmp_path / "run" / "runner.lock",
        poweroff_request_path=tmp_path / "run" / "poweroff.request",
        inference_mode=inference_mode,  # type: ignore[arg-type]
        promotion_file=promotion if inference_mode == "live" else None,
        event_reason="sentinel_event",
        capture_timeout_s=30.0,
        event_duration_s=10.0,
        preprocess_timeout_s=20.0,
        readiness_ttl_s=300,
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
    )


def _runtime() -> EquipmentInferenceRuntime:
    return EquipmentInferenceRuntime(
        model_version="model-1",
        vision_classifier=_Classifier(kind="vision"),
        audio_classifier=_Classifier(kind="audio"),
        fusion_policy=FusionPolicy(),
        alert_gate=ShadowAlertGate(shadow_mode=True, consecutive_required=2),
    )


def _runner(
    tmp_path: Path,
    *,
    inference_mode: str = "shadow",
    preprocessor: _Preprocessor | None = None,
) -> tuple[CameraSatelliteRunner, SatelliteConfig]:
    config = _config(tmp_path, inference_mode=inference_mode)
    bundle = _bundle(tmp_path)
    runner = CameraSatelliteRunner(
        config,
        manager_factory=lambda _config: _Manager(bundle),  # type: ignore[arg-type,return-value]
        inference_factory=lambda _bundle: _runtime(),
        camera_factory=lambda _config: _Camera(),
        preprocessor_factory=lambda _bundle, _config: preprocessor or _Preprocessor(),
        store_factory=lambda selected: LocalEvidenceStore(
            str(selected.evidence_dir),
            max_bytes=selected.evidence_max_bytes,
        ),
        known_answer_validator=lambda _bundle, _classifiers: True,
        clock=lambda: datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
        boot_id_source=lambda: "boot-123",
    )
    return runner, config


def test_event_run_persists_only_local_ring_and_scalar_handoff(tmp_path: Path) -> None:
    runner, config = _runner(tmp_path)

    result = runner.run(mode="event", invocation_id="lora-0001")

    assert result["status"] == "ok"
    assert result["equipment_state"] == "fault"
    assert result["alert_eligible"] is False
    assert result["alert_reason"] == "shadow_mode"
    assert result["evidence_capture_id"]
    assert len(result["evidence_sha256"]) == 64
    assert json.loads(config.result_path.read_text(encoding="utf-8")) == result
    assert stat.S_IMODE(config.result_path.stat().st_mode) == 0o600
    receipt = json.loads(config.ready_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "ready"
    assert receipt["known_answers_valid"] is True
    assert receipt["preprocessing_valid"] is True
    assert receipt["local_media_only"] is True
    assert receipt["application_target"] == str(config.application_current_symlink.resolve())
    assets = LocalEvidenceStore(
        str(config.evidence_dir), max_bytes=config.evidence_max_bytes
    ).ring.list_assets_oldest_first()
    assert len(assets) == 3
    assert all(asset.metadata.local_only for asset in assets)


def test_baked_image_application_target_is_the_only_non_release_bootstrap_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, config = _runner(tmp_path)
    baked = tmp_path / "baked-app"
    baked.mkdir()
    config.application_current_symlink.unlink()
    config.application_current_symlink.symlink_to(baked)
    monkeypatch.setattr("agent.camera_satellite_runner._BAKED_APPLICATION_TARGET", baked)

    assert runner._application_target() == baked.resolve()

    other = tmp_path / "unreviewed-app"
    other.mkdir()
    config.application_current_symlink.unlink()
    config.application_current_symlink.symlink_to(other)
    with pytest.raises(SatelliteRunError, match="application_release_invalid"):
        runner._application_target()


def test_daily_run_retains_still_but_discards_transient_audio(tmp_path: Path) -> None:
    runner, config = _runner(tmp_path)

    result = runner.run(mode="daily", invocation_id="daily-0001")

    assert result["equipment_state"] == "fault"
    assets = LocalEvidenceStore(
        str(config.evidence_dir), max_bytes=config.evidence_max_bytes
    ).ring.list_assets_oldest_first()
    assert len(assets) == 1
    assert assets[0].metadata.asset_kind == "daily_still"
    assert assets[0].asset_path.read_bytes() == b"daily-jpeg"


def test_wake_cycle_schedules_poweroff_only_after_atomic_result_commit(tmp_path: Path) -> None:
    runner, config = _runner(tmp_path)

    result = runner.run(
        mode="event",
        invocation_id="wake-0001",
        poweroff_on_success=True,
    )

    request = json.loads(config.poweroff_request_path.read_text(encoding="utf-8"))
    assert result["poweroff_requested"] is True
    assert config.result_path.exists()
    assert request["status"] == "poweroff_requested"
    assert request["mode"] == "event"
    assert request["invocation_id"] == "wake-0001"
    assert request["result_sha256"] == hashlib.sha256(config.result_path.read_bytes()).hexdigest()
    assert stat.S_IMODE(config.poweroff_request_path.stat().st_mode) == 0o600

    committed_result = config.result_path.read_bytes()
    with pytest.raises(SatelliteRunError, match="poweroff_pending"):
        runner.run(mode="check", invocation_id="late-check")
    assert config.result_path.read_bytes() == committed_result
    assert config.ready_path.exists()


def test_check_mode_can_validate_model_without_scheduling_poweroff(tmp_path: Path) -> None:
    runner, config = _runner(tmp_path)

    result = runner.run(mode="check", invocation_id="ota-readiness")

    assert result["status"] == "ok"
    assert result["poweroff_requested"] is False
    assert not config.poweroff_request_path.exists()

    with pytest.raises(SatelliteRunError, match="poweroff_not_allowed"):
        runner.run(
            mode="check",
            invocation_id="invalid-shutdown-check",
            poweroff_on_success=True,
        )
    assert not config.poweroff_request_path.exists()


def test_readiness_fails_closed_when_signed_preprocessing_and_model_disagree(
    tmp_path: Path,
) -> None:
    runner, config = _runner(tmp_path, preprocessor=_BrokenPreprocessor())
    config.ready_path.parent.mkdir(parents=True)
    config.ready_path.write_text("stale", encoding="utf-8")

    with pytest.raises(SatelliteRunError, match="model_not_ready"):
        runner.run(mode="check", invocation_id="check-0001")

    assert not config.ready_path.exists()
    failure = json.loads(config.result_path.read_text(encoding="utf-8"))
    assert failure["status"] == "failed"
    assert failure["error_code"] == "model_not_ready"


def test_live_alert_gate_persists_repeated_observation_across_oneshot_runs(
    tmp_path: Path,
) -> None:
    first_runner, config = _runner(tmp_path, inference_mode="live")
    first = first_runner.run(mode="event", invocation_id="event-0001")
    second_runner, _ = _runner(tmp_path, inference_mode="live")
    second = second_runner.run(mode="event", invocation_id="event-0002")

    assert first["alert_eligible"] is False
    assert first["alert_reason"] == "awaiting_repeated_agreement"
    assert second["alert_eligible"] is True
    assert second["repeated_observations"] == 2
    assert stat.S_IMODE(config.gate_state_path.stat().st_mode) == 0o600


def test_live_promotion_rejects_duplicate_json_keys_with_specific_failure(
    tmp_path: Path,
) -> None:
    runner, config = _runner(tmp_path, inference_mode="live")
    assert config.promotion_file is not None
    config.promotion_file.write_text(
        (
            '{"schema_version":1,"held_out_alert_precision":0.95,'
            '"held_out_alert_precision":0.99,"false_alert_count":0,"device_days":10}'
        ),
        encoding="utf-8",
    )
    config.promotion_file.chmod(0o600)

    with pytest.raises(SatelliteRunError, match="promotion_evidence_invalid"):
        runner.run(mode="check", invocation_id="promotion-check")

    failure = json.loads(config.result_path.read_text(encoding="utf-8"))
    assert failure["error_code"] == "promotion_evidence_invalid"


def test_environment_contract_requires_promotion_evidence_for_live_mode(tmp_path: Path) -> None:
    environment = {
        "EDGEWATCH_DEVICE_ID": "satellite-001",
        "MEDIA_RTSP_CAM1_URL": "rtsp://192.0.2.10/substream",
        "MEDIA_RTSP_CAM1_CREDENTIALS_FILE": str(tmp_path / "camera.json"),
        "EDGEWATCH_MODEL_RELEASES_ROOT": str(tmp_path / "releases"),
        "EDGEWATCH_MODEL_CURRENT_SYMLINK": str(tmp_path / "current"),
        "EDGEWATCH_MODEL_KEYRING_DIR": str(tmp_path / "keys"),
        "EDGEWATCH_SATELLITE_EVIDENCE_DIR": str(tmp_path / "evidence"),
        "EDGEWATCH_SATELLITE_RESULT_PATH": str(tmp_path / "result.json"),
        "EDGEWATCH_SATELLITE_READY_PATH": str(tmp_path / "ready.json"),
        "EDGEWATCH_SATELLITE_GATE_STATE_PATH": str(tmp_path / "gate.json"),
        "EDGEWATCH_SATELLITE_LOCK_PATH": str(tmp_path / "run.lock"),
        "EDGEWATCH_INFERENCE_MODE": "live",
    }

    with pytest.raises(SatelliteConfigError, match="PROMOTION_FILE"):
        SatelliteConfig.from_env(environment)

    environment["EDGEWATCH_INFERENCE_MODE"] = "shadow"
    environment["EDGEWATCH_SATELLITE_POWEROFF_REQUEST_PATH"] = (
        "/run/edgewatch-camera-satellite/not-watched.request"
    )
    with pytest.raises(SatelliteConfigError, match="fixed systemd watcher path"):
        SatelliteConfig.from_env(environment)
