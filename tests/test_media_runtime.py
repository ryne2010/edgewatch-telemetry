from __future__ import annotations

from pathlib import Path

import pytest

from agent.media.runtime import MediaConfigError, MediaRuntime, build_media_runtime_from_env
from agent.media.storage import MediaAssetMetadata, StoredMediaAsset


class _FakeCaptureService:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self._fail_first = fail_first

    def capture_snapshot(self, *, camera_id: str, reason: str) -> StoredMediaAsset:
        self.calls.append((camera_id, reason))
        if self._fail_first:
            self._fail_first = False
            raise RuntimeError("capture failed")
        metadata = MediaAssetMetadata(
            device_id="demo-well-001",
            camera_id=camera_id,
            captured_at="2026-02-21T12:00:00+00:00",
            reason=reason,
            sha256="a" * 64,
            bytes=128,
            mime_type="image/jpeg",
        )
        return StoredMediaAsset(
            asset_path=Path("/tmp/x.jpg"), sidecar_path=Path("/tmp/x.jpg.json"), metadata=metadata
        )


def test_media_runtime_schedules_cameras_round_robin() -> None:
    capture = _FakeCaptureService()
    runtime = MediaRuntime(
        device_id="demo-well-001",
        camera_ids=("cam1", "cam2"),
        snapshot_interval_s=60.0,
        capture_retry_s=5.0,
        capture_service=capture,
    )

    assert runtime.maybe_capture_scheduled(now_s=0.0) is not None
    assert runtime.maybe_capture_scheduled(now_s=0.0) is not None
    assert runtime.maybe_capture_scheduled(now_s=0.0) is None
    assert runtime.maybe_capture_scheduled(now_s=60.0) is not None

    assert capture.calls == [
        ("cam1", "scheduled"),
        ("cam2", "scheduled"),
        ("cam1", "scheduled"),
    ]


def test_media_runtime_retries_after_capture_failure() -> None:
    capture = _FakeCaptureService(fail_first=True)
    runtime = MediaRuntime(
        device_id="demo-well-001",
        camera_ids=("cam1",),
        snapshot_interval_s=60.0,
        capture_retry_s=5.0,
        capture_service=capture,
    )

    with pytest.raises(RuntimeError):
        runtime.maybe_capture_scheduled(now_s=0.0)

    assert runtime.maybe_capture_scheduled(now_s=4.9) is None
    assert runtime.maybe_capture_scheduled(now_s=5.0) is not None
    assert capture.calls == [("cam1", "scheduled"), ("cam1", "scheduled")]


def test_build_media_runtime_fails_cleanly_when_libcamera_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEDIA_ENABLED", "true")
    monkeypatch.setenv("CAMERA_IDS", "cam1")
    monkeypatch.setattr("agent.media.capture.shutil.which", lambda _value: None)

    with pytest.raises(MediaConfigError) as exc:
        build_media_runtime_from_env(device_id="demo-well-001")

    assert "libcamera-still not found" in str(exc.value)


def test_build_media_runtime_returns_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDIA_ENABLED", "false")
    monkeypatch.delenv("CAMERA_IDS", raising=False)

    assert build_media_runtime_from_env(device_id="demo-well-001") is None
