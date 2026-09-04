from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

_ALLOWED_REASONS = frozenset(
    {
        "scheduled",
        "alert_transition",
        "manual",
        "daily_health",
        "sentinel_event",
        "model_event",
    }
)
_ALLOWED_ASSET_KINDS = frozenset({"photo", "daily_still", "event_still", "event_audio", "event_clip"})
_MIME_TO_EXTENSION = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "video/x-matroska": ".mkv",
}
_ATTRIBUTE_KEY = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

MediaScalar = str | int | float | bool


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
    asset_kind: str | None = None
    local_only: bool = False
    attributes: dict[str, MediaScalar] | None = None


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
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
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


def _normalize_asset_kind(asset_kind: str | None) -> str | None:
    if asset_kind is None:
        return None
    normalized = asset_kind.strip().lower()
    if normalized not in _ALLOWED_ASSET_KINDS:
        allowed = ", ".join(sorted(_ALLOWED_ASSET_KINDS))
        raise ValueError(f"invalid asset_kind '{asset_kind}' (allowed: {allowed})")
    return normalized


def _normalize_attributes(
    attributes: Mapping[str, MediaScalar] | None,
) -> dict[str, MediaScalar] | None:
    if attributes is None:
        return None
    if len(attributes) > 32:
        raise ValueError("media attributes cannot contain more than 32 fields")

    normalized: dict[str, MediaScalar] = {}
    for raw_key, raw_value in attributes.items():
        if not isinstance(raw_key, str) or _ATTRIBUTE_KEY.fullmatch(raw_key) is None:
            raise ValueError("media attribute keys must be lowercase safe identifiers")
        if isinstance(raw_value, str):
            if len(raw_value) > 256 or any(ord(char) < 32 for char in raw_value):
                raise ValueError(f"media attribute '{raw_key}' contains an invalid string")
            value: MediaScalar = raw_value
        elif isinstance(raw_value, bool):
            value = raw_value
        elif isinstance(raw_value, int):
            value = raw_value
        elif isinstance(raw_value, float) and math.isfinite(raw_value):
            value = raw_value
        else:
            raise ValueError(f"media attribute '{raw_key}' must be a finite JSON scalar")
        normalized[raw_key] = value
    return normalized


def _metadata_payload(metadata: MediaAssetMetadata) -> dict[str, object]:
    payload: dict[str, object] = asdict(metadata)
    if metadata.asset_kind is None:
        payload.pop("asset_kind", None)
    if not metadata.local_only:
        payload.pop("local_only", None)
    if metadata.attributes is None:
        payload.pop("attributes", None)
    return payload


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

    def __init__(
        self,
        root_dir: str | Path,
        *,
        max_bytes: int,
        max_age_days: float | None = None,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be >= 1")
        if max_age_days is not None and max_age_days <= 0:
            raise ValueError("max_age_days must be > 0 when configured")
        self.root_dir = Path(root_dir).expanduser()
        self.max_bytes = int(max_bytes)
        self.max_age_days = float(max_age_days) if max_age_days is not None else None
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
        return self.store_asset(
            device_id=device_id,
            camera_id=camera_id,
            asset_bytes=photo_bytes,
            reason=reason,
            mime_type=mime_type,
            captured_at=captured_at,
        )

    def store_asset(
        self,
        *,
        device_id: str,
        camera_id: str,
        asset_bytes: bytes,
        reason: str,
        mime_type: str,
        captured_at: datetime | None = None,
        asset_kind: str | None = None,
        local_only: bool = False,
        attributes: Mapping[str, MediaScalar] | None = None,
    ) -> StoredMediaAsset:
        if not device_id.strip():
            raise ValueError("device_id must be non-empty")
        if not camera_id.strip():
            raise ValueError("camera_id must be non-empty")
        reason_normalized = _normalize_reason(reason)
        mime_type_normalized = mime_type.strip().lower()
        if not mime_type_normalized:
            raise ValueError("mime_type must be non-empty")
        asset_kind_normalized = _normalize_asset_kind(asset_kind)
        attributes_normalized = _normalize_attributes(attributes)

        capture_time = captured_at or now_utc()
        if capture_time.tzinfo is None:
            capture_time = capture_time.replace(tzinfo=timezone.utc)
        else:
            capture_time = capture_time.astimezone(timezone.utc)
        payload_bytes = bytes(asset_bytes)
        if not payload_bytes:
            raise ValueError("asset_bytes must be non-empty")
        sha256 = hashlib.sha256(payload_bytes).hexdigest()

        folder = self.root_dir / device_id.strip() / camera_id.strip() / capture_time.strftime("%Y-%m-%d")
        filename = _asset_filename(captured_at=capture_time, mime_type=mime_type_normalized)
        asset_path = folder / filename
        sidecar_path = Path(f"{asset_path}.json")

        metadata = MediaAssetMetadata(
            device_id=device_id.strip(),
            camera_id=camera_id.strip(),
            captured_at=to_iso_utc(capture_time),
            reason=reason_normalized,
            sha256=sha256,
            bytes=len(payload_bytes),
            mime_type=mime_type_normalized,
            asset_kind=asset_kind_normalized,
            local_only=bool(local_only),
            attributes=attributes_normalized,
        )

        _atomic_write(asset_path, payload_bytes)
        try:
            payload = json.dumps(_metadata_payload(metadata), sort_keys=True).encode("utf-8") + b"\n"
            _atomic_write(sidecar_path, payload)
        except Exception:
            _safe_unlink(asset_path)
            raise

        self.enforce_retention()
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

    def enforce_retention(self, *, now: datetime | None = None) -> list[StoredMediaAsset]:
        """Delete assets older than the configured age limit.

        Age pruning is intentionally independent of the byte quota: evidence can
        never live forever merely because the disk has spare capacity.
        """

        if self.max_age_days is None:
            return []
        current = now or now_utc()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        else:
            current = current.astimezone(timezone.utc)
        cutoff = current - timedelta(days=self.max_age_days)
        expired: list[StoredMediaAsset] = []
        for asset in self.list_assets_oldest_first():
            captured_at = parse_iso_utc(asset.metadata.captured_at)
            if captured_at >= cutoff:
                continue
            self._delete_asset(asset)
            expired.append(asset)
        return expired

    def delete_asset(self, asset: StoredMediaAsset) -> None:
        """Remove an asset + sidecar from the ring buffer."""
        self._delete_asset(asset)

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
        asset_kind = raw.get("asset_kind")
        local_only = raw.get("local_only", False)
        attributes = raw.get("attributes")

        if not isinstance(device_id, str) or not device_id.strip():
            return None
        if not isinstance(camera_id, str) or not camera_id.strip():
            return None
        if not isinstance(captured_at, str) or not captured_at.strip():
            return None
        if not isinstance(reason, str):
            return None
        if not isinstance(sha256, str) or _SHA256.fullmatch(sha256.strip()) is None:
            return None
        if isinstance(bytes_raw, bool) or not isinstance(bytes_raw, int) or bytes_raw <= 0:
            return None
        if not isinstance(mime_type, str) or not mime_type.strip():
            return None
        if asset_kind is not None and not isinstance(asset_kind, str):
            return None
        if not isinstance(local_only, bool):
            return None
        if attributes is not None and not isinstance(attributes, Mapping):
            return None

        try:
            normalized_capture = to_iso_utc(parse_iso_utc(captured_at))
            normalized_reason = _normalize_reason(reason)
            normalized_asset_kind = _normalize_asset_kind(asset_kind)
            normalized_attributes = _normalize_attributes(attributes)
        except (ValueError, TypeError, OverflowError):
            return None

        return MediaAssetMetadata(
            device_id=device_id.strip(),
            camera_id=camera_id.strip(),
            captured_at=normalized_capture,
            reason=normalized_reason,
            sha256=sha256.strip(),
            bytes=bytes_raw,
            mime_type=mime_type.strip().lower(),
            asset_kind=normalized_asset_kind,
            local_only=local_only,
            attributes=normalized_attributes,
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
