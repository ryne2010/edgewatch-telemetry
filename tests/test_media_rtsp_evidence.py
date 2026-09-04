from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from agent.media.capture import CameraCaptureError
from agent.media.evidence import CapturedEventEvidence, LocalEvidenceStore
from agent.media.qualification import CameraQualificationEvidence, evaluate_camera_qualification
from agent.media.rtsp import (
    FFmpegRtspBackend,
    RtspCameraConfig,
    RtspCaptureLimits,
    RtspConfigurationError,
)
from agent.media.runtime import MediaConfigError, MediaRuntime, build_media_runtime_from_env


def _write_secret(path: Path, *, username: str = "operator", password: str = "top secret") -> None:
    path.write_text(json.dumps({"username": username, "password": password}), encoding="utf-8")
    path.chmod(0o600)


class _RecordingRunner:
    def __init__(self, *, probe_audio: str = "aac", returncode: int = 0) -> None:
        self.probe_audio = probe_audio
        self.returncode = returncode
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        self.calls.append((list(command), dict(kwargs)))
        if command[0].endswith("ffprobe"):
            body = {
                "streams": [
                    {"codec_type": "video", "codec_name": "h264"},
                    {"codec_type": "audio", "codec_name": self.probe_audio},
                ]
            }
            return subprocess.CompletedProcess(command, self.returncode, json.dumps(body).encode(), b"")

        for item in command:
            path = Path(item)
            if item.endswith(".jpg"):
                path.write_bytes(b"jpeg")
            elif item.endswith(".wav"):
                path.write_bytes(b"wave")
            elif item.endswith(".mkv"):
                path.write_bytes(b"matroska")
        return subprocess.CompletedProcess(command, self.returncode, b"", b"")


def _backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: _RecordingRunner,
) -> FFmpegRtspBackend:
    secret = tmp_path / "camera.json"
    _write_secret(secret)
    monkeypatch.setattr("agent.media.rtsp.shutil.which", lambda binary: f"/usr/bin/{binary}")
    return FFmpegRtspBackend(
        {
            "cam1": RtspCameraConfig(
                endpoint="rtsp://192.0.2.10:554/h264Preview_01_sub",
                credentials_path=secret,
            )
        },
        limits=RtspCaptureLimits(
            connect_timeout_s=5.0,
            event_duration_s=2.0,
            max_photo_bytes=1024,
            max_audio_bytes=1024,
            max_clip_bytes=1024,
        ),
        run_command=runner,
    )


def test_rtsp_event_capture_keeps_credentials_out_of_process_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _RecordingRunner()
    backend = _backend(tmp_path, monkeypatch, runner)
    monkeypatch.setenv("FFREPORT", f"file={tmp_path / 'unsafe-report.log'}")

    captured = backend.capture_event(camera_id="cam1", timeout_s=6.0)

    assert captured.still_jpeg == b"jpeg"
    assert captured.audio_wav == b"wave"
    assert captured.clip_matroska == b"matroska"
    assert len(runner.calls) == 2
    for command, kwargs in runner.calls:
        rendered = " ".join(command)
        assert "operator" not in rendered
        assert "top secret" not in rendered
        assert "192.0.2.10" not in rendered
        assert "FFREPORT" not in kwargs["env"]
        assert "operator" not in " ".join(kwargs["env"].values())
        assert "top secret" not in " ".join(kwargs["env"].values())
        secret_input = kwargs["input"]
        assert isinstance(secret_input, bytes)
        assert b"operator:top%20secret@192.0.2.10" in secret_input
        whitelist = command[command.index("-protocol_whitelist") + 1]
        assert whitelist == "pipe,rtsp,tcp,udp,rtp"
        assert "http" not in whitelist


def test_rtsp_daily_sample_extracts_still_and_wav_without_clip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _RecordingRunner()
    backend = _backend(tmp_path, monkeypatch, runner)

    captured = backend.capture_sample(camera_id="cam1", timeout_s=6.0)

    assert captured.still_jpeg == b"jpeg"
    assert captured.audio_wav == b"wave"
    ffmpeg_command = runner.calls[-1][0]
    assert any(value.endswith(".jpg") for value in ffmpeg_command)
    assert any(value.endswith(".wav") for value in ffmpeg_command)
    assert not any(value.endswith(".mkv") for value in ffmpeg_command)


def test_rtsp_capture_failure_does_not_expose_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _RecordingRunner(returncode=1)
    backend = _backend(tmp_path, monkeypatch, runner)

    with pytest.raises(CameraCaptureError) as exc:
        backend.capture_photo(camera_id="cam1", timeout_s=2.0)

    assert "operator" not in str(exc.value)
    assert "top secret" not in str(exc.value)


def test_rtsp_secret_requires_mode_0600(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _RecordingRunner()
    backend = _backend(tmp_path, monkeypatch, runner)
    (tmp_path / "camera.json").chmod(0o644)

    with pytest.raises(RtspConfigurationError, match="mode 0600"):
        backend.capture_photo(camera_id="cam1", timeout_s=2.0)


def test_rtsp_secret_rejects_duplicate_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _backend(tmp_path, monkeypatch, _RecordingRunner())
    secret = tmp_path / "camera.json"
    secret.write_text(
        '{"username":"operator","password":"first","password":"second"}',
        encoding="utf-8",
    )
    secret.chmod(0o600)

    with pytest.raises(RtspConfigurationError, match="duplicate keys"):
        backend.capture_photo(camera_id="cam1", timeout_s=2.0)


@pytest.mark.parametrize(
    "endpoint",
    (
        "rtsp://192.0.2.10/path with-space",
        "rtsp://192.0.2.10/path\x7f",
        "rtsp://[malformed/path",
    ),
)
def test_rtsp_endpoint_rejects_unsafe_concat_input(endpoint: str, tmp_path: Path) -> None:
    secret = tmp_path / "camera.json"
    _write_secret(secret)

    with pytest.raises(RtspConfigurationError):
        FFmpegRtspBackend({"cam1": RtspCameraConfig(endpoint=endpoint, credentials_path=secret)})


def test_rtsp_probe_rejects_camera_without_supported_audio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend(tmp_path, monkeypatch, _RecordingRunner(probe_audio="opus"))

    with pytest.raises(CameraCaptureError, match="AAC or G.711"):
        backend.probe(camera_id="cam1")


def test_media_runtime_builds_managed_rtsp_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEDIA_ENABLED", "true")
    monkeypatch.setenv("CAMERA_IDS", "cam1")
    monkeypatch.setenv("MEDIA_BACKEND", "rtsp")
    monkeypatch.setenv("MEDIA_RTSP_CAM1_URL", "rtsp://192.0.2.10/substream")
    monkeypatch.setenv("MEDIA_RTSP_CAM1_CREDENTIALS_FILE", str(tmp_path / "camera.json"))
    monkeypatch.setenv("MEDIA_RING_DIR", str(tmp_path / "ring"))
    monkeypatch.setattr("agent.media.rtsp.shutil.which", lambda binary: f"/usr/bin/{binary}")

    runtime = build_media_runtime_from_env(device_id="satellite-001")

    assert runtime is not None
    assert isinstance(getattr(runtime.capture_service, "backend"), FFmpegRtspBackend)


def test_media_runtime_rtsp_config_requires_secret_file_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEDIA_ENABLED", "true")
    monkeypatch.setenv("CAMERA_IDS", "cam1")
    monkeypatch.setenv("MEDIA_BACKEND", "rtsp")
    monkeypatch.setenv("MEDIA_RTSP_CAM1_URL", "rtsp://192.0.2.10/substream")
    monkeypatch.delenv("MEDIA_RTSP_CAM1_CREDENTIALS_FILE", raising=False)

    with pytest.raises(MediaConfigError, match="MEDIA_RTSP_CAM1_CREDENTIALS_FILE"):
        build_media_runtime_from_env(device_id="satellite-001")


class _NeverCapture:
    def capture_snapshot(self, *, camera_id: str, reason: str) -> Any:
        raise AssertionError((camera_id, reason))


class _NeverUpload:
    def post(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError((args, kwargs))

    def put(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError((args, kwargs))


def test_local_evidence_is_scalar_annotated_retained_and_not_uploaded(tmp_path: Path) -> None:
    captured_at = datetime.now(timezone.utc)
    store = LocalEvidenceStore(str(tmp_path / "evidence"), max_bytes=1_000_000)
    evidence = store.store_event(
        device_id="satellite-001",
        camera_id="cam1",
        evidence=CapturedEventEvidence(b"jpeg", b"wave", b"matroska"),
        inference={
            "equipment_state": "fault",
            "state_confidence": 0.97,
            "audio_anomaly_score": 0.91,
            "visual_change": 0.88,
            "model_version": "model-1",
        },
        captured_at=captured_at,
    )

    assets = store.ring.list_assets_oldest_first()
    assert len(assets) == 3
    assert {asset.metadata.asset_kind for asset in assets} == {
        "event_still",
        "event_audio",
        "event_clip",
    }
    assert all(asset.metadata.local_only for asset in assets)
    for asset in assets:
        assert asset.metadata.attributes is not None
        assert asset.metadata.attributes["capture_id"] == evidence.capture_id

    runtime = MediaRuntime(
        device_id="satellite-001",
        camera_ids=("cam1",),
        snapshot_interval_s=86_400,
        capture_retry_s=60,
        capture_service=_NeverCapture(),
        ring_buffer=store.ring,
    )
    assert (
        runtime.maybe_upload_pending(
            session=_NeverUpload(),
            api_url="https://unused.invalid",
            token="unused",
            now_s=0.0,
        )
        is None
    )

    expired = store.prune(now=captured_at + timedelta(days=31))
    assert len(expired) == 3
    assert store.ring.list_assets_oldest_first() == []


def test_local_evidence_rolls_back_partial_event(tmp_path: Path) -> None:
    store = LocalEvidenceStore(str(tmp_path / "evidence"), max_bytes=1_000_000)

    with pytest.raises(ValueError, match="asset_bytes"):
        store.store_event(
            device_id="satellite-001",
            camera_id="cam1",
            evidence=CapturedEventEvidence(b"jpeg", b"wave", b""),
            inference={"equipment_state": "unknown"},
        )

    assert store.ring.list_assets_oldest_first() == []


def test_camera_qualification_requires_full_pilot_evidence() -> None:
    evidence = CameraQualificationEvidence(
        works_without_internet=True,
        works_without_cloud_account=True,
        local_credentials_supported=True,
        video_codec="h264",
        audio_codec="pcm_alaw",
        ingress_rating="IP67",
        power_interface="poe",
        first_media_seconds=(12.0, 13.0, 11.5),
        successful_power_cycles=99,
        attempted_power_cycles=100,
        automatic_stream_recovery=True,
        recovery_observation_hours=24.0,
        satellite_electronics_cost_usd=199.99,
    )
    result = evaluate_camera_qualification(evidence)

    assert result.qualified is True
    assert result.failures == ()

    assert evaluate_camera_qualification(replace(evidence, ingress_rating="IP66")).qualified is False
    assert (
        evaluate_camera_qualification(
            replace(evidence, satellite_electronics_cost_usd=float("nan"))
        ).qualified
        is False
    )
