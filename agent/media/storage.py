from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

_ALLOWED_REASONS = frozenset({"scheduled", "alert_transition", "manual"})
_MIME_TO_EXTENSION = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


class MediaStorageError(RuntimeError):
    """Raised when media assets cannot be persisted safely."""


@dataclass(frozen=True)
class MediaAssetMetadata:
    device_id: str
    camera_id: str
    captured_at: str
    reason: str
    sha256: str
    bytes: int
    mime_type: str


@dataclass(frozen=True)
class StoredMediaAsset:
    asset_path: Path
    sidecar_path: Path
    metadata: MediaAssetMetadata

    @property
    def total_bytes(self) -> int:
        return int(self.asset_path.stat().st_size) + int(self.sidecar_path.stat().st_size)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def parse_iso_utc(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_reason(reason: str) -> str:
    normalized = reason.strip()
    if normalized not in _ALLOWED_REASONS:
        allowed = ", ".join(sorted(_ALLOWED_REASONS))
        raise ValueError(f"invalid reason '{reason}' (allowed: {allowed})")
    return normalized


def _extension_for_mime(mime_type: str) -> str:
    normalized = mime_type.strip().lower()
    return _MIME_TO_EXTENSION.get(normalized, ".bin")


def _asset_filename(*, captured_at: datetime, mime_type: str) -> str:
    ts = captured_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    suffix = uuid.uuid4().hex[:12]
    ext = _extension_for_mime(mime_type)
    return f"{ts}-{suffix}{ext}"


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        return
    finally:
        os.close(fd)


def _atomic_write(path: Path, payload: bytes) -> None:
    temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temp_path.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


def _safe_rmdir(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        return


class MediaRingBuffer:
    """Filesystem-backed ring buffer for captured media bytes + JSON sidecars."""

    def __init__(self, root_dir: str | Path, *, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be >= 1")
        self.root_dir = Path(root_dir).expanduser()
        self.max_bytes = int(max_bytes)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def store_photo(
        self,
        *,
        device_id: str,
        camera_id: str,
        photo_bytes: bytes,
        reason: str,
        mime_type: str = "image/jpeg",
        captured_at: datetime | None = None,
    ) -> StoredMediaAsset:
        if not device_id.strip():
            raise ValueError("device_id must be non-empty")
        if not camera_id.strip():
            raise ValueError("camera_id must be non-empty")
        reason_normalized = _normalize_reason(reason)

        capture_time = (captured_at or now_utc()).astimezone(timezone.utc)
        payload_bytes = bytes(photo_bytes)
        sha256 = hashlib.sha256(payload_bytes).hexdigest()

        folder = self.root_dir / device_id.strip() / camera_id.strip() / capture_time.strftime("%Y-%m-%d")
        filename = _asset_filename(captured_at=capture_time, mime_type=mime_type)
        asset_path = folder / filename
        sidecar_path = Path(f"{asset_path}.json")

        metadata = MediaAssetMetadata(
            device_id=device_id.strip(),
            camera_id=camera_id.strip(),
            captured_at=to_iso_utc(capture_time),
            reason=reason_normalized,
            sha256=sha256,
            bytes=len(payload_bytes),
            mime_type=mime_type.strip().lower(),
        )

        _atomic_write(asset_path, payload_bytes)
        try:
            payload = json.dumps(asdict(metadata), sort_keys=True).encode("utf-8") + b"\n"
            _atomic_write(sidecar_path, payload)
        except Exception:
            _safe_unlink(asset_path)
            raise

        self.enforce_max_bytes()
        if not asset_path.exists() or not sidecar_path.exists():
            raise MediaStorageError(
                f"captured media evicted immediately; increase MEDIA_RING_MAX_BYTES above {len(payload_bytes)}"
            )

        return StoredMediaAsset(asset_path=asset_path, sidecar_path=sidecar_path, metadata=metadata)

    def list_assets_oldest_first(self) -> list[StoredMediaAsset]:
        return sorted(
            self._iter_assets(clean_orphans=True),
            key=lambda item: (item.metadata.captured_at, str(item.asset_path)),
        )

    def total_bytes(self) -> int:
        return sum(asset.total_bytes for asset in self._iter_assets(clean_orphans=True))

    def enforce_max_bytes(self) -> list[StoredMediaAsset]:
        self._remove_temp_files()
        assets = self.list_assets_oldest_first()
        total = sum(item.total_bytes for item in assets)

        evicted: list[StoredMediaAsset] = []
        for asset in assets:
            if total <= self.max_bytes:
                break
            total -= asset.total_bytes
            self._delete_asset(asset)
            evicted.append(asset)

        return evicted

    def _iter_assets(self, *, clean_orphans: bool) -> Iterable[StoredMediaAsset]:
        if not self.root_dir.exists():
            return

        for sidecar_path in self.root_dir.rglob("*.json"):
            if sidecar_path.name.endswith(".tmp"):
                continue
            asset_path = Path(str(sidecar_path)[: -len(".json")])
            if not asset_path.exists():
                if clean_orphans:
                    _safe_unlink(sidecar_path)
                continue

            metadata = self._load_metadata(sidecar_path)
            if metadata is None:
                if clean_orphans:
                    _safe_unlink(sidecar_path)
                    _safe_unlink(asset_path)
                continue

            yield StoredMediaAsset(
                asset_path=asset_path,
                sidecar_path=sidecar_path,
                metadata=metadata,
            )

    def _load_metadata(self, sidecar_path: Path) -> MediaAssetMetadata | None:
        try:
            raw = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(raw, dict):
            return None

        device_id = raw.get("device_id")
        camera_id = raw.get("camera_id")
        captured_at = raw.get("captured_at")
        reason = raw.get("reason")
        sha256 = raw.get("sha256")
        bytes_raw = raw.get("bytes")
        mime_type = raw.get("mime_type")

        if not isinstance(device_id, str) or not device_id.strip():
            return None
        if not isinstance(camera_id, str) or not camera_id.strip():
            return None
        if not isinstance(captured_at, str) or not captured_at.strip():
            return None
        if not isinstance(reason, str):
            return None
        if not isinstance(sha256, str) or len(sha256.strip()) != 64:
            return None
        if isinstance(bytes_raw, bool) or not isinstance(bytes_raw, (int, float)):
            return None
        if not isinstance(mime_type, str) or not mime_type.strip():
            return None

        try:
            normalized_capture = to_iso_utc(parse_iso_utc(captured_at))
            normalized_reason = _normalize_reason(reason)
        except (ValueError, TypeError):
            return None

        return MediaAssetMetadata(
            device_id=device_id.strip(),
            camera_id=camera_id.strip(),
            captured_at=normalized_capture,
            reason=normalized_reason,
            sha256=sha256.strip(),
            bytes=max(0, int(bytes_raw)),
            mime_type=mime_type.strip().lower(),
        )

    def _remove_temp_files(self) -> None:
        for temp_path in self.root_dir.rglob("*.tmp"):
            _safe_unlink(temp_path)

    def _delete_asset(self, asset: StoredMediaAsset) -> None:
        _safe_unlink(asset.sidecar_path)
        _safe_unlink(asset.asset_path)

        for parent in (asset.sidecar_path.parent, asset.sidecar_path.parent.parent):
            if parent == self.root_dir or parent == self.root_dir.parent:
                continue
            _safe_rmdir(parent)
