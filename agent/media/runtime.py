from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from .capture import LibcameraStillBackend, MediaCaptureService, parse_camera_id
from .storage import MediaAssetMetadata, MediaRingBuffer, StoredMediaAsset


class MediaConfigError(ValueError):
    """Invalid media configuration."""


class MediaUploadError(RuntimeError):
    """Raised when media upload to the API fails."""


@dataclass(frozen=True)
class MediaConfig:
    enabled: bool
    camera_ids: tuple[str, ...]
    snapshot_interval_s: float
    capture_retry_s: float
    upload_retry_initial_s: float
    upload_retry_max_s: float
    alert_transition_min_interval_s: float
    upload_timeout_s: float
    ring_dir: str
    ring_max_bytes: int
    backend: str
    capture_timeout_s: float
    lock_timeout_s: float


class CaptureService(Protocol):
    def capture_snapshot(self, *, camera_id: str, reason: str) -> StoredMediaAsset:
        raise NotImplementedError


class HTTPSession(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: float,
    ) -> Any:
        raise NotImplementedError

    def put(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        data: bytes,
        timeout: float,
    ) -> Any:
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
        ring_buffer: MediaRingBuffer | None = None,
        upload_retry_initial_s: float = 30.0,
        upload_retry_max_s: float = 300.0,
        alert_transition_min_interval_s: float = 30.0,
        upload_timeout_s: float = 20.0,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self.device_id = device_id
        self.camera_ids = camera_ids
        self.snapshot_interval_s = float(snapshot_interval_s)
        self.capture_retry_s = float(capture_retry_s)
        self.capture_service = capture_service
        self.ring_buffer = ring_buffer
        self.upload_retry_initial_s = float(upload_retry_initial_s)
        self.upload_retry_max_s = float(upload_retry_max_s)
        self.alert_transition_min_interval_s = float(alert_transition_min_interval_s)
        self.upload_timeout_s = float(upload_timeout_s)
        self._now_fn = now_fn
        self._next_due_by_camera = {camera_id: 0.0 for camera_id in camera_ids}
        self._cursor = 0
        self._next_alert_capture_at = 0.0
        self._upload_next_attempt_by_asset: dict[str, float] = {}
        self._upload_failures_by_asset: dict[str, int] = {}

        if self.upload_retry_initial_s <= 0:
            raise ValueError("upload_retry_initial_s must be > 0")
        if self.upload_retry_max_s < self.upload_retry_initial_s:
            raise ValueError("upload_retry_max_s must be >= upload_retry_initial_s")
        if self.alert_transition_min_interval_s <= 0:
            raise ValueError("alert_transition_min_interval_s must be > 0")
        if self.upload_timeout_s <= 0:
            raise ValueError("upload_timeout_s must be > 0")

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

    def maybe_capture_alert_transition(self, *, now_s: float | None = None) -> StoredMediaAsset | None:
        if not self.camera_ids:
            return None
        now = self._now_fn() if now_s is None else float(now_s)
        if now < self._next_alert_capture_at:
            return None

        camera_id = self._next_camera_round_robin()
        try:
            asset = self.capture_service.capture_snapshot(
                camera_id=camera_id,
                reason="alert_transition",
            )
        except Exception:
            self._next_alert_capture_at = now + self.capture_retry_s
            raise

        # Avoid immediately re-capturing the same camera as a scheduled snapshot.
        self._next_due_by_camera[camera_id] = max(
            self._next_due_by_camera.get(camera_id, 0.0),
            now + self.snapshot_interval_s,
        )
        self._next_alert_capture_at = now + self.alert_transition_min_interval_s
        return asset

    def maybe_upload_pending(
        self,
        *,
        session: HTTPSession,
        api_url: str,
        token: str,
        now_s: float | None = None,
    ) -> StoredMediaAsset | None:
        if self.ring_buffer is None:
            return None
        now = self._now_fn() if now_s is None else float(now_s)
        asset = self._next_upload_candidate(now_s=now)
        if asset is None:
            return None

        key = self._asset_key(asset)
        try:
            self._upload_asset(
                session=session,
                api_url=api_url,
                token=token,
                asset=asset,
            )
        except Exception as exc:
            failures = self._upload_failures_by_asset.get(key, 0) + 1
            self._upload_failures_by_asset[key] = failures
            backoff_s = self._upload_backoff_s(failures)
            self._upload_next_attempt_by_asset[key] = now + backoff_s
            raise MediaUploadError(
                f"media upload failed for {asset.asset_path.name}; retry in {backoff_s:.1f}s"
            ) from exc

        self._upload_failures_by_asset.pop(key, None)
        self._upload_next_attempt_by_asset.pop(key, None)
        self.ring_buffer.delete_asset(asset)
        return asset

    def _next_upload_candidate(self, *, now_s: float) -> StoredMediaAsset | None:
        if self.ring_buffer is None:
            return None
        assets = self.ring_buffer.list_assets_oldest_first()
        live_keys = {self._asset_key(asset) for asset in assets}

        for key in list(self._upload_next_attempt_by_asset):
            if key not in live_keys:
                self._upload_next_attempt_by_asset.pop(key, None)
                self._upload_failures_by_asset.pop(key, None)

        for asset in assets:
            key = self._asset_key(asset)
            if now_s >= self._upload_next_attempt_by_asset.get(key, 0.0):
                return asset
        return None

    def _upload_asset(
        self,
        *,
        session: HTTPSession,
        api_url: str,
        token: str,
        asset: StoredMediaAsset,
    ) -> None:
        metadata = asset.metadata
        message_id = build_media_message_id(metadata)
        create_payload = {
            "message_id": message_id,
            "camera_id": metadata.camera_id,
            "captured_at": metadata.captured_at,
            "reason": metadata.reason,
            "sha256": metadata.sha256,
            "bytes": int(metadata.bytes),
            "mime_type": metadata.mime_type,
        }

        create_resp = session.post(
            f"{api_url.rstrip('/')}/api/v1/media",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=create_payload,
            timeout=self.upload_timeout_s,
        )
        if not (200 <= int(create_resp.status_code) < 300):
            raise MediaUploadError(
                f"metadata create failed: {create_resp.status_code} {create_resp.text[:200]}"
            )

        try:
            create_body = create_resp.json()
            if not isinstance(create_body, dict):
                raise ValueError("response body is not an object")
            media_obj = create_body.get("media")
            upload_obj = create_body.get("upload")
            if not isinstance(media_obj, dict) or not isinstance(upload_obj, dict):
                raise ValueError("response body is missing media/upload")
            media_id_value = media_obj.get("id")
            upload_url_value = upload_obj.get("url")
            if media_id_value is None or upload_url_value is None:
                raise ValueError("response body is missing media.id/upload.url")
            media_id = str(media_id_value)
            upload_url_raw = str(upload_url_value)
        except Exception as exc:
            raise MediaUploadError("metadata create response is missing upload instructions") from exc

        if upload_url_raw.startswith("/"):
            upload_url = f"{api_url.rstrip('/')}{upload_url_raw}"
        elif upload_url_raw.startswith("http://") or upload_url_raw.startswith("https://"):
            upload_url = upload_url_raw
        else:
            upload_url = f"{api_url.rstrip('/')}/{upload_url_raw.lstrip('/')}"

        upload_resp = session.put(
            upload_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": metadata.mime_type,
            },
            data=asset.asset_path.read_bytes(),
            timeout=self.upload_timeout_s,
        )
        if not (200 <= int(upload_resp.status_code) < 300):
            raise MediaUploadError(
                f"media upload failed for id={media_id}: {upload_resp.status_code} {upload_resp.text[:200]}"
            )

    def _upload_backoff_s(self, failures: int) -> float:
        exponent = min(max(0, failures - 1), 8)
        return min(self.upload_retry_max_s, self.upload_retry_initial_s * (2**exponent))

    @staticmethod
    def _asset_key(asset: StoredMediaAsset) -> str:
        return str(asset.sidecar_path)

    def _next_camera_round_robin(self) -> str:
        if not self.camera_ids:
            raise RuntimeError("no camera ids configured")
        idx = self._cursor % len(self.camera_ids)
        camera_id = self.camera_ids[idx]
        self._cursor = (idx + 1) % len(self.camera_ids)
        return camera_id

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
            upload_retry_initial_s=30.0,
            upload_retry_max_s=300.0,
            alert_transition_min_interval_s=30.0,
            upload_timeout_s=20.0,
            ring_dir="./edgewatch_media",
            ring_max_bytes=500 * 1024 * 1024,
            backend="libcamera",
            capture_timeout_s=15.0,
            lock_timeout_s=5.0,
        )

    camera_ids = _parse_camera_ids(os.getenv("CAMERA_IDS"))
    snapshot_interval_s = _parse_float_env("MEDIA_SNAPSHOT_INTERVAL_S", default=300.0)
    capture_retry_s = _parse_float_env("MEDIA_CAPTURE_RETRY_S", default=min(60.0, snapshot_interval_s))
    upload_retry_initial_s = _parse_float_env(
        "MEDIA_UPLOAD_RETRY_S",
        default=min(60.0, snapshot_interval_s),
    )
    upload_retry_max_s = _parse_float_env("MEDIA_UPLOAD_BACKOFF_MAX_S", default=300.0)
    if upload_retry_max_s < upload_retry_initial_s:
        raise MediaConfigError("MEDIA_UPLOAD_BACKOFF_MAX_S must be >= MEDIA_UPLOAD_RETRY_S")
    alert_transition_min_interval_s = _parse_float_env(
        "MEDIA_ALERT_TRANSITION_MIN_INTERVAL_S",
        default=30.0,
    )
    upload_timeout_s = _parse_float_env("MEDIA_UPLOAD_TIMEOUT_S", default=20.0)
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
        upload_retry_initial_s=upload_retry_initial_s,
        upload_retry_max_s=upload_retry_max_s,
        alert_transition_min_interval_s=alert_transition_min_interval_s,
        upload_timeout_s=upload_timeout_s,
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
        ring_buffer=ring_buffer,
        upload_retry_initial_s=config.upload_retry_initial_s,
        upload_retry_max_s=config.upload_retry_max_s,
        alert_transition_min_interval_s=config.alert_transition_min_interval_s,
        upload_timeout_s=config.upload_timeout_s,
    )


def build_media_message_id(metadata: MediaAssetMetadata) -> str:
    """Deterministic message id so upload retries remain idempotent."""
    seed = "|".join(
        [
            metadata.device_id,
            metadata.camera_id,
            metadata.captured_at,
            metadata.reason,
            metadata.sha256,
            str(int(metadata.bytes)),
            metadata.mime_type,
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"media-{digest[:32]}"
