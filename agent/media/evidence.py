from __future__ import annotations

import hashlib
import os
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

from .storage import MediaRingBuffer, MediaScalar, MediaStorageError, StoredMediaAsset


@dataclass(frozen=True)
class CapturedEventEvidence:
    """Bounded media produced for one local sentinel/model event."""

    still_jpeg: bytes
    audio_wav: bytes
    clip_matroska: bytes


@dataclass(frozen=True)
class CapturedInferenceSample:
    """Bounded still and audio sample used for daily local inference."""

    still_jpeg: bytes
    audio_wav: bytes


@dataclass(frozen=True)
class StoredEventEvidence:
    capture_id: str
    still: StoredMediaAsset
    audio: StoredMediaAsset
    clip: StoredMediaAsset


class LocalEvidenceStore:
    """Local-only 30-day evidence ring.

    This wrapper deliberately has no upload method. Every asset is marked
    ``local_only`` so sharing the underlying ring with the legacy media runtime
    still cannot enqueue these captures for routine API upload.
    """

    def __init__(
        self,
        root_dir: str,
        *,
        max_bytes: int,
        retention_days: float = 30.0,
    ) -> None:
        root = Path(root_dir).expanduser()
        if root.is_symlink():
            raise MediaStorageError("local evidence root must not be a symbolic link")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            metadata = root.stat()
            if not stat.S_ISDIR(metadata.st_mode):
                raise MediaStorageError("local evidence root must be a directory")
            if metadata.st_uid not in {0, os.geteuid()}:
                raise MediaStorageError("local evidence root must be owned by root or the service user")
            root.chmod(0o700)
        except OSError as exc:
            raise MediaStorageError("local evidence root cannot be secured") from exc
        self.ring = MediaRingBuffer(
            root,
            max_bytes=max_bytes,
            max_age_days=retention_days,
        )

    def store_event(
        self,
        *,
        device_id: str,
        camera_id: str,
        evidence: CapturedEventEvidence,
        inference: Mapping[str, MediaScalar],
        captured_at: datetime | None = None,
        reason: str = "sentinel_event",
    ) -> StoredEventEvidence:
        capture_id = uuid.uuid4().hex
        attributes = {**dict(inference), "capture_id": capture_id}
        stored: list[StoredMediaAsset] = []
        try:
            still = self.ring.store_asset(
                device_id=device_id,
                camera_id=camera_id,
                asset_bytes=evidence.still_jpeg,
                reason=reason,
                mime_type="image/jpeg",
                captured_at=captured_at,
                asset_kind="event_still",
                local_only=True,
                attributes=attributes,
            )
            stored.append(still)
            audio = self.ring.store_asset(
                device_id=device_id,
                camera_id=camera_id,
                asset_bytes=evidence.audio_wav,
                reason=reason,
                mime_type="audio/wav",
                captured_at=captured_at,
                asset_kind="event_audio",
                local_only=True,
                attributes=attributes,
            )
            stored.append(audio)
            clip = self.ring.store_asset(
                device_id=device_id,
                camera_id=camera_id,
                asset_bytes=evidence.clip_matroska,
                reason=reason,
                mime_type="video/x-matroska",
                captured_at=captured_at,
                asset_kind="event_clip",
                local_only=True,
                attributes=attributes,
            )
            stored.append(clip)
            if any(not asset.asset_path.exists() or not asset.sidecar_path.exists() for asset in stored):
                raise MediaStorageError("complete event evidence does not fit in the local ring")
        except Exception:
            for asset in stored:
                self.ring.delete_asset(asset)
            raise

        return StoredEventEvidence(
            capture_id=capture_id,
            still=still,
            audio=audio,
            clip=clip,
        )

    def store_daily_still(
        self,
        *,
        device_id: str,
        camera_id: str,
        still_jpeg: bytes,
        inference: Mapping[str, MediaScalar],
        captured_at: datetime | None = None,
    ) -> StoredMediaAsset:
        return self.ring.store_asset(
            device_id=device_id,
            camera_id=camera_id,
            asset_bytes=still_jpeg,
            reason="daily_health",
            mime_type="image/jpeg",
            captured_at=captured_at,
            asset_kind="daily_still",
            local_only=True,
            attributes=inference,
        )

    def prune(self, *, now: datetime | None = None) -> list[StoredMediaAsset]:
        expired = self.ring.enforce_retention(now=now)
        self.ring.enforce_max_bytes()
        return expired

    def latest_still_bytes(
        self,
        *,
        device_id: str,
        camera_id: str,
        maximum_bytes: int = 5 * 1024 * 1024,
    ) -> bytes | None:
        """Read the newest retained still only after sidecar integrity checks."""

        candidates = [
            asset
            for asset in self.ring.list_assets_oldest_first()
            if asset.metadata.device_id == device_id
            and asset.metadata.camera_id == camera_id
            and asset.metadata.asset_kind in {"event_still", "daily_still"}
        ]
        if not candidates:
            return None
        latest = candidates[-1]
        if latest.metadata.bytes <= 0 or latest.metadata.bytes > maximum_bytes:
            raise MediaStorageError("retained still size is outside the allowed range")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(latest.asset_path, flags)
        except OSError as exc:
            raise MediaStorageError("retained still cannot be opened safely") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != latest.metadata.bytes:
                raise MediaStorageError("retained still does not match its sidecar")
            payload = os.read(descriptor, maximum_bytes + 1)
        finally:
            os.close(descriptor)
        if len(payload) != latest.metadata.bytes:
            raise MediaStorageError("retained still read was incomplete")
        if hashlib.sha256(payload).hexdigest() != latest.metadata.sha256:
            raise MediaStorageError("retained still digest does not match its sidecar")
        return payload
