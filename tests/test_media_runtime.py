from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import pytest

from agent.media.runtime import (
    MediaConfigError,
    MediaRuntime,
    MediaUploadError,
    build_media_message_id,
    build_media_runtime_from_env,
)
from agent.media.storage import MediaAssetMetadata, MediaRingBuffer, StoredMediaAsset


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


class _FakeResponse:
    def __init__(self, *, status_code: int, text: str = "", body: object | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self._body = body if body is not None else {}

    def json(self) -> object:
        return self._body


class _FakeHttpSession:
    def __init__(
        self,
        *,
        post_statuses: list[int] | None = None,
        put_statuses: list[int] | None = None,
    ) -> None:
        self.post_statuses = list(post_statuses or [200])
        self.put_statuses = list(put_statuses or [200])
        self.post_calls: list[dict[str, object]] = []
        self.put_calls: list[dict[str, object]] = []

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: float,
    ) -> _FakeResponse:
        self.post_calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        status = self.post_statuses.pop(0) if self.post_statuses else 200
        if status >= 400:
            return _FakeResponse(status_code=status, text="post failed")
        media_id = "media-123"
        return _FakeResponse(
            status_code=200,
            body={"media": {"id": media_id}, "upload": {"url": f"/api/v1/media/{media_id}/upload"}},
        )

    def put(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        data: bytes,
        timeout: float,
    ) -> _FakeResponse:
        self.put_calls.append({"url": url, "headers": headers, "data": data, "timeout": timeout})
        status = self.put_statuses.pop(0) if self.put_statuses else 200
        if status >= 400:
            return _FakeResponse(status_code=status, text="put failed")
        return _FakeResponse(status_code=200, body={"ok": True})


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


def test_media_runtime_alert_transition_capture_is_rate_limited() -> None:
    capture = _FakeCaptureService()
    runtime = MediaRuntime(
        device_id="demo-well-001",
        camera_ids=("cam1", "cam2"),
        snapshot_interval_s=60.0,
        capture_retry_s=5.0,
        alert_transition_min_interval_s=30.0,
        capture_service=capture,
    )

    assert runtime.maybe_capture_alert_transition(now_s=0.0) is not None
    assert runtime.maybe_capture_alert_transition(now_s=10.0) is None
    assert runtime.maybe_capture_alert_transition(now_s=30.0) is not None

    assert capture.calls == [
        ("cam1", "alert_transition"),
        ("cam2", "alert_transition"),
    ]


def test_media_runtime_uploads_oldest_asset_and_removes_it(tmp_path: Path) -> None:
    ring = MediaRingBuffer(tmp_path / "media", max_bytes=5_000_000)
    ts1 = datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 2, 21, 12, 0, 1, tzinfo=timezone.utc)
    oldest = ring.store_photo(
        device_id="demo-well-001",
        camera_id="cam1",
        photo_bytes=b"oldest-bytes",
        reason="scheduled",
        captured_at=ts1,
    )
    newest = ring.store_photo(
        device_id="demo-well-001",
        camera_id="cam2",
        photo_bytes=b"newest-bytes",
        reason="manual",
        captured_at=ts2,
    )

    runtime = MediaRuntime(
        device_id="demo-well-001",
        camera_ids=("cam1", "cam2"),
        snapshot_interval_s=60.0,
        capture_retry_s=5.0,
        capture_service=_FakeCaptureService(),
        ring_buffer=ring,
        upload_retry_initial_s=5.0,
        upload_retry_max_s=60.0,
    )
    session = _FakeHttpSession()

    uploaded = runtime.maybe_upload_pending(
        session=session,
        api_url="http://localhost:8082",
        token="tok",
        now_s=0.0,
    )
    assert uploaded is not None
    assert uploaded.metadata.captured_at == oldest.metadata.captured_at
    assert not oldest.asset_path.exists()
    assert newest.asset_path.exists()

    assert len(session.post_calls) == 1
    post_payload = session.post_calls[0]["json"]
    assert isinstance(post_payload, dict)
    assert post_payload["message_id"] == build_media_message_id(oldest.metadata)
    assert len(session.put_calls) == 1
    assert session.put_calls[0]["url"] == "http://localhost:8082/api/v1/media/media-123/upload"


def test_media_runtime_upload_uses_backoff_after_failure(tmp_path: Path) -> None:
    ring = MediaRingBuffer(tmp_path / "media", max_bytes=5_000_000)
    ring.store_photo(
        device_id="demo-well-001",
        camera_id="cam1",
        photo_bytes=b"payload",
        reason="manual",
        captured_at=datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc),
    )

    runtime = MediaRuntime(
        device_id="demo-well-001",
        camera_ids=("cam1",),
        snapshot_interval_s=60.0,
        capture_retry_s=5.0,
        capture_service=_FakeCaptureService(),
        ring_buffer=ring,
        upload_retry_initial_s=5.0,
        upload_retry_max_s=60.0,
    )
    session = _FakeHttpSession(post_statuses=[500, 200], put_statuses=[200])

    with pytest.raises(MediaUploadError):
        runtime.maybe_upload_pending(
            session=session,
            api_url="http://localhost:8082",
            token="tok",
            now_s=0.0,
        )

    # Still in backoff window; no extra call yet.
    assert (
        runtime.maybe_upload_pending(
            session=session,
            api_url="http://localhost:8082",
            token="tok",
            now_s=4.9,
        )
        is None
    )
    assert len(session.post_calls) == 1

    # Backoff elapsed; retry succeeds and asset is removed.
    assert (
        runtime.maybe_upload_pending(
            session=session,
            api_url="http://localhost:8082",
            token="tok",
            now_s=5.0,
        )
        is not None
    )
    assert len(session.post_calls) == 2
    assert ring.list_assets_oldest_first() == []
