from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from .capture import LibcameraStillBackend, MediaCaptureService, parse_camera_id
from .storage import MediaRingBuffer, StoredMediaAsset


class MediaConfigError(ValueError):
    """Invalid media configuration."""


@dataclass(frozen=True)
class MediaConfig:
    enabled: bool
    camera_ids: tuple[str, ...]
    snapshot_interval_s: float
    capture_retry_s: float
    ring_dir: str
    ring_max_bytes: int
    backend: str
    capture_timeout_s: float
    lock_timeout_s: float


class CaptureService(Protocol):
    def capture_snapshot(self, *, camera_id: str, reason: str) -> StoredMediaAsset:
        raise NotImplementedError


class MediaRuntime:
    def __init__(
        self,
        *,
        device_id: str,
        camera_ids: tuple[str, ...],
        snapshot_interval_s: float,
        capture_retry_s: float,
        capture_service: CaptureService,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self.device_id = device_id
        self.camera_ids = camera_ids
        self.snapshot_interval_s = float(snapshot_interval_s)
        self.capture_retry_s = float(capture_retry_s)
        self.capture_service = capture_service
        self._now_fn = now_fn
        self._next_due_by_camera = {camera_id: 0.0 for camera_id in camera_ids}
        self._cursor = 0

    def maybe_capture_scheduled(self, *, now_s: float | None = None) -> StoredMediaAsset | None:
        if not self.camera_ids:
            return None
        now = self._now_fn() if now_s is None else float(now_s)
        due_camera = self._pop_due_camera(now)
        if due_camera is None:
            return None

        try:
            asset = self.capture_service.capture_snapshot(
                camera_id=due_camera,
                reason="scheduled",
            )
        except Exception:
            self._next_due_by_camera[due_camera] = now + self.capture_retry_s
            raise

        self._next_due_by_camera[due_camera] = now + self.snapshot_interval_s
        return asset

    def _pop_due_camera(self, now_s: float) -> str | None:
        total = len(self.camera_ids)
        for offset in range(total):
            index = (self._cursor + offset) % total
            camera_id = self.camera_ids[index]
            if now_s >= self._next_due_by_camera[camera_id]:
                self._cursor = (index + 1) % total
                return camera_id
        return None


def _parse_bool(raw: str | None, *, default: bool = False) -> bool:
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise MediaConfigError(f"invalid boolean value '{raw}'")


def _parse_float_env(name: str, *, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = float(default)
    else:
        try:
            value = float(raw)
        except ValueError as exc:
            raise MediaConfigError(f"{name} must be numeric") from exc
    if value <= 0:
        raise MediaConfigError(f"{name} must be > 0")
    return value


def _parse_int_env(name: str, *, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = int(default)
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise MediaConfigError(f"{name} must be an integer") from exc
    if value <= 0:
        raise MediaConfigError(f"{name} must be > 0")
    return value


def _parse_camera_ids(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        raise MediaConfigError("CAMERA_IDS is required when MEDIA_ENABLED=true")

    values: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        value = item.strip().lower()
        if not value:
            continue
        parse_camera_id(value)
        if value in seen:
            raise MediaConfigError(f"duplicate camera id '{value}' in CAMERA_IDS")
        values.append(value)
        seen.add(value)

    if not values:
        raise MediaConfigError("CAMERA_IDS must include at least one camera id (for example: cam1,cam2)")
    return tuple(values)


def load_media_config_from_env() -> MediaConfig:
    enabled = _parse_bool(os.getenv("MEDIA_ENABLED"), default=False)
    if not enabled:
        return MediaConfig(
            enabled=False,
            camera_ids=(),
            snapshot_interval_s=300.0,
            capture_retry_s=60.0,
            ring_dir="./edgewatch_media",
            ring_max_bytes=500 * 1024 * 1024,
            backend="libcamera",
            capture_timeout_s=15.0,
            lock_timeout_s=5.0,
        )

    camera_ids = _parse_camera_ids(os.getenv("CAMERA_IDS"))
    snapshot_interval_s = _parse_float_env("MEDIA_SNAPSHOT_INTERVAL_S", default=300.0)
    capture_retry_s = _parse_float_env("MEDIA_CAPTURE_RETRY_S", default=min(60.0, snapshot_interval_s))
    ring_max_bytes = _parse_int_env("MEDIA_RING_MAX_BYTES", default=500 * 1024 * 1024)
    capture_timeout_s = _parse_float_env("MEDIA_CAPTURE_TIMEOUT_S", default=15.0)
    lock_timeout_s = _parse_float_env("MEDIA_CAPTURE_LOCK_TIMEOUT_S", default=5.0)
    ring_dir = os.getenv("MEDIA_RING_DIR", "./edgewatch_media").strip()
    if not ring_dir:
        raise MediaConfigError("MEDIA_RING_DIR must be non-empty")
    backend = os.getenv("MEDIA_BACKEND", "libcamera").strip().lower()
    if backend not in {"libcamera"}:
        raise MediaConfigError("MEDIA_BACKEND must be 'libcamera' for this stage")

    return MediaConfig(
        enabled=True,
        camera_ids=camera_ids,
        snapshot_interval_s=snapshot_interval_s,
        capture_retry_s=capture_retry_s,
        ring_dir=ring_dir,
        ring_max_bytes=ring_max_bytes,
        backend=backend,
        capture_timeout_s=capture_timeout_s,
        lock_timeout_s=lock_timeout_s,
    )


def build_media_runtime_from_env(*, device_id: str) -> MediaRuntime | None:
    config = load_media_config_from_env()
    if not config.enabled:
        return None

    ring_buffer = MediaRingBuffer(config.ring_dir, max_bytes=config.ring_max_bytes)
    backend = LibcameraStillBackend()
    if not backend.is_supported():
        raise MediaConfigError(
            "libcamera-still not found on PATH; install libcamera tools or set MEDIA_ENABLED=false"
        )
    capture_service = MediaCaptureService(
        device_id=device_id,
        backend=backend,
        ring_buffer=ring_buffer,
        capture_timeout_s=config.capture_timeout_s,
        lock_timeout_s=config.lock_timeout_s,
    )
    return MediaRuntime(
        device_id=device_id,
        camera_ids=config.camera_ids,
        snapshot_interval_s=config.snapshot_interval_s,
        capture_retry_s=config.capture_retry_s,
        capture_service=capture_service,
    )
