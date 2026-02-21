from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

from .storage import MediaRingBuffer, StoredMediaAsset


class CameraCaptureError(RuntimeError):
    """Raised when the camera backend cannot capture a snapshot."""


class CaptureBusyError(RuntimeError):
    """Raised when another capture is already active."""


@dataclass(frozen=True)
class CapturedPhoto:
    payload: bytes
    mime_type: str = "image/jpeg"


class CameraBackend(Protocol):
    def capture_photo(self, *, camera_id: str, timeout_s: float) -> CapturedPhoto:
        raise NotImplementedError


def parse_camera_id(camera_id: str) -> int:
    raw = camera_id.strip().lower()
    if not raw.startswith("cam"):
        raise ValueError(f"invalid camera id '{camera_id}'")
    suffix = raw[3:]
    if not suffix.isdigit():
        raise ValueError(f"invalid camera id '{camera_id}'")
    index = int(suffix)
    if index < 1:
        raise ValueError(f"invalid camera id '{camera_id}'")
    return index - 1


class LibcameraStillBackend:
    """Photo capture backend backed by libcamera-still CLI."""

    def __init__(
        self,
        *,
        binary: str = "libcamera-still",
        extra_args: tuple[str, ...] = (),
    ) -> None:
        self.binary = binary
        self.extra_args = extra_args

    def is_supported(self) -> bool:
        return shutil.which(self.binary) is not None

    def capture_photo(self, *, camera_id: str, timeout_s: float) -> CapturedPhoto:
        binary_path = shutil.which(self.binary)
        if binary_path is None:
            raise CameraCaptureError(
                f"{self.binary} not found on PATH; install libcamera tools or disable MEDIA_ENABLED"
            )

        camera_index = parse_camera_id(camera_id)
        with tempfile.NamedTemporaryFile(prefix="edgewatch-capture-", suffix=".jpg", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            cmd = [
                binary_path,
                "--camera",
                str(camera_index),
                "--nopreview",
                "--immediate",
                "--encoding",
                "jpg",
                "--output",
                str(tmp_path),
                *self.extra_args,
            ]
            completed = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=max(1.0, float(timeout_s)),
            )
            if completed.returncode != 0:
                stderr = (completed.stderr or completed.stdout or "").strip()
                raise CameraCaptureError(
                    f"libcamera capture failed for {camera_id}: {stderr[:200] or 'unknown error'}"
                )
            payload = tmp_path.read_bytes()
            if not payload:
                raise CameraCaptureError(f"libcamera produced an empty image for {camera_id}")
            return CapturedPhoto(payload=payload, mime_type="image/jpeg")
        except subprocess.TimeoutExpired as exc:
            raise CameraCaptureError(f"libcamera capture timed out for {camera_id}") from exc
        finally:
            tmp_path.unlink(missing_ok=True)


class CaptureLock:
    """In-process mutex for camera selection + capture."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    @contextmanager
    def hold(self, *, timeout_s: float) -> Iterator[None]:
        acquired = self._lock.acquire(timeout=max(0.0, float(timeout_s)))
        if not acquired:
            raise CaptureBusyError("capture is already in progress")
        try:
            yield
        finally:
            self._lock.release()


class MediaCaptureService:
    def __init__(
        self,
        *,
        device_id: str,
        backend: CameraBackend,
        ring_buffer: MediaRingBuffer,
        lock: CaptureLock | None = None,
        capture_timeout_s: float = 15.0,
        lock_timeout_s: float = 5.0,
    ) -> None:
        self.device_id = device_id
        self.backend = backend
        self.ring_buffer = ring_buffer
        self.lock = lock or CaptureLock()
        self.capture_timeout_s = float(capture_timeout_s)
        self.lock_timeout_s = float(lock_timeout_s)

    def capture_snapshot(self, *, camera_id: str, reason: str) -> StoredMediaAsset:
        with self.lock.hold(timeout_s=self.lock_timeout_s):
            captured = self.backend.capture_photo(
                camera_id=camera_id,
                timeout_s=self.capture_timeout_s,
            )

        return self.ring_buffer.store_photo(
            device_id=self.device_id,
            camera_id=camera_id,
            photo_bytes=captured.payload,
            mime_type=captured.mime_type,
            reason=reason,
        )
