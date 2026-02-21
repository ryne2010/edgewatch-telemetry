from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..config import settings
from ..models import MediaObject

_REASON_VALUES = frozenset({"scheduled", "alert_transition", "manual"})
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
}


class MediaError(RuntimeError):
    """Base class for media service failures."""


class MediaConfigError(MediaError):
    """Invalid media configuration or backend availability."""


class MediaConflictError(MediaError):
    """Metadata conflict for an idempotency key."""


class MediaValidationError(MediaError):
    """Upload payload failed integrity checks."""


class MediaNotUploadedError(MediaError):
    """Media object exists but bytes are not uploaded yet."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_segment(value: str, *, field: str) -> str:
    v = value.strip()
    if not _SAFE_SEGMENT_RE.fullmatch(v):
        raise MediaValidationError(f"{field} contains unsupported characters")
    return v


def _normalize_reason(value: str) -> str:
    v = value.strip()
    if v not in _REASON_VALUES:
        allowed = ", ".join(sorted(_REASON_VALUES))
        raise MediaValidationError(f"reason must be one of: {allowed}")
    return v


def _normalize_mime_type(value: str) -> str:
    v = value.strip().lower()
    if not v:
        raise MediaValidationError("mime_type is required")
    return v


def _extension_for_mime_type(mime_type: str) -> str:
    return _MIME_EXTENSIONS.get(mime_type, ".bin")


def build_object_path(
    *,
    device_id: str,
    camera_id: str,
    captured_at: datetime,
    message_id: str,
    mime_type: str,
) -> str:
    safe_device = _safe_segment(device_id, field="device_id")
    safe_camera = _safe_segment(camera_id, field="camera_id")
    safe_message = _safe_segment(message_id, field="message_id")
    day = normalize_utc(captured_at).strftime("%Y-%m-%d")
    extension = _extension_for_mime_type(_normalize_mime_type(mime_type))
    return f"{safe_device}/{safe_camera}/{day}/{safe_message}{extension}"


@dataclass(frozen=True)
class MediaCreateInput:
    message_id: str
    camera_id: str
    captured_at: datetime
    reason: str
    sha256: str
    bytes: int
    mime_type: str


class MediaBinaryStore(Protocol):
    def resolve_pointer(self, *, object_path: str) -> tuple[str | None, str | None]:
        raise NotImplementedError

    def put_bytes(self, *, object_path: str, payload: bytes, mime_type: str) -> None:
        raise NotImplementedError

    def read_bytes(self, *, object_path: str) -> bytes:
        raise NotImplementedError


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


class LocalMediaStore:
    def __init__(self, *, root_dir: str) -> None:
        self.root_dir = Path(root_dir).expanduser().resolve()

    def resolve_pointer(self, *, object_path: str) -> tuple[str | None, str | None]:
        abs_path = self._absolute_path(object_path)
        return str(abs_path), None

    def put_bytes(self, *, object_path: str, payload: bytes, mime_type: str) -> None:
        del mime_type
        target = self._absolute_path(object_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with tmp.open("wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
            _fsync_directory(target.parent)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    def read_bytes(self, *, object_path: str) -> bytes:
        return self._absolute_path(object_path).read_bytes()

    def _absolute_path(self, object_path: str) -> Path:
        rel = Path(object_path)
        if rel.is_absolute() or ".." in rel.parts:
            raise MediaValidationError("invalid object path")
        abs_path = (self.root_dir / rel).resolve()
        try:
            abs_path.relative_to(self.root_dir)
        except ValueError as exc:
            raise MediaValidationError("invalid object path") from exc
        return abs_path


class GCSMediaStore:
    def __init__(self, *, bucket: str, prefix: str, project_id: str | None) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip().strip("/")
        self.project_id = project_id

    def resolve_pointer(self, *, object_path: str) -> tuple[str | None, str | None]:
        key = self._object_key(object_path)
        return None, f"gs://{self.bucket}/{key}"

    def put_bytes(self, *, object_path: str, payload: bytes, mime_type: str) -> None:
        blob = self._blob(object_path)
        blob.upload_from_string(payload, content_type=mime_type)

    def read_bytes(self, *, object_path: str) -> bytes:
        return self._blob(object_path).download_as_bytes()

    def _blob(self, object_path: str):
        try:
            from google.cloud import storage  # type: ignore[import-not-found]
        except ImportError as exc:
            raise MediaConfigError("google-cloud-storage is required for MEDIA_STORAGE_BACKEND=gcs") from exc
        client = storage.Client(project=self.project_id)
        return client.bucket(self.bucket).blob(self._object_key(object_path))

    def _object_key(self, object_path: str) -> str:
        rel = Path(object_path)
        if rel.is_absolute() or ".." in rel.parts:
            raise MediaValidationError("invalid object path")
        rel_key = rel.as_posix().lstrip("/")
        if self.prefix:
            return f"{self.prefix}/{rel_key}"
        return rel_key


def build_media_store() -> MediaBinaryStore:
    if settings.media_storage_backend == "local":
        return LocalMediaStore(root_dir=settings.media_local_root)
    if not settings.media_gcs_bucket:
        raise MediaConfigError("MEDIA_GCS_BUCKET is required when MEDIA_STORAGE_BACKEND=gcs")
    return GCSMediaStore(
        bucket=settings.media_gcs_bucket,
        prefix=settings.media_gcs_prefix,
        project_id=settings.gcp_project_id,
    )


def create_or_get_media_object(
    session: Session,
    *,
    device_id: str,
    create: MediaCreateInput,
    store: MediaBinaryStore,
) -> tuple[MediaObject, bool]:
    captured_at = normalize_utc(create.captured_at)
    reason = _normalize_reason(create.reason)
    mime_type = _normalize_mime_type(create.mime_type)
    message_id = _safe_segment(create.message_id, field="message_id")
    camera_id = _safe_segment(create.camera_id, field="camera_id")

    if create.bytes <= 0:
        raise MediaValidationError("bytes must be greater than zero")
    if create.bytes > settings.media_max_upload_bytes:
        raise MediaValidationError(
            f"bytes exceeds MEDIA_MAX_UPLOAD_BYTES ({settings.media_max_upload_bytes})"
        )

    sha256 = create.sha256.strip().lower()
    if not re.fullmatch(r"[a-f0-9]{64}", sha256):
        raise MediaValidationError("sha256 must be 64 lowercase hex characters")

    object_path = build_object_path(
        device_id=device_id,
        camera_id=camera_id,
        captured_at=captured_at,
        message_id=message_id,
        mime_type=mime_type,
    )
    local_path, gcs_uri = store.resolve_pointer(object_path=object_path)

    existing = (
        session.query(MediaObject)
        .filter(
            MediaObject.device_id == device_id,
            MediaObject.message_id == message_id,
            MediaObject.camera_id == camera_id,
        )
        .one_or_none()
    )
    if existing is not None:
        if not _same_metadata(
            existing=existing,
            captured_at=captured_at,
            reason=reason,
            sha256=sha256,
            size_bytes=create.bytes,
            mime_type=mime_type,
            object_path=object_path,
        ):
            raise MediaConflictError("media metadata conflict for existing idempotency key")
        return existing, False

    media = MediaObject(
        device_id=device_id,
        camera_id=camera_id,
        message_id=message_id,
        captured_at=captured_at,
        reason=reason,
        sha256=sha256,
        bytes=int(create.bytes),
        mime_type=mime_type,
        object_path=object_path,
        gcs_uri=gcs_uri,
        local_path=local_path,
    )
    session.add(media)
    session.flush()
    return media, True


def _same_metadata(
    *,
    existing: MediaObject,
    captured_at: datetime,
    reason: str,
    sha256: str,
    size_bytes: int,
    mime_type: str,
    object_path: str,
) -> bool:
    return (
        normalize_utc(existing.captured_at) == captured_at
        and existing.reason == reason
        and existing.sha256 == sha256
        and int(existing.bytes) == int(size_bytes)
        and existing.mime_type == mime_type
        and existing.object_path == object_path
    )


def upload_media_payload(
    session: Session,
    *,
    media: MediaObject,
    payload: bytes,
    content_type: str | None,
    store: MediaBinaryStore,
) -> MediaObject:
    normalized_content_type = _normalize_content_type(content_type)
    if normalized_content_type and normalized_content_type != media.mime_type:
        raise MediaValidationError("content type mismatch")

    if len(payload) > settings.media_max_upload_bytes:
        raise MediaValidationError(
            f"payload exceeds MEDIA_MAX_UPLOAD_BYTES ({settings.media_max_upload_bytes})"
        )
    if len(payload) != int(media.bytes):
        raise MediaValidationError("payload length does not match declared bytes")

    digest = hashlib.sha256(payload).hexdigest()
    if digest != media.sha256:
        raise MediaValidationError("payload sha256 does not match declared sha256")

    if media.uploaded_at is None:
        store.put_bytes(object_path=media.object_path, payload=payload, mime_type=media.mime_type)
        media.uploaded_at = utcnow()
        session.add(media)
        session.flush()

    return media


def _normalize_content_type(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip().lower()
    if not raw:
        return None
    return raw.split(";", 1)[0].strip()


def list_device_media(
    session: Session,
    *,
    device_id: str,
    limit: int,
) -> list[MediaObject]:
    return (
        session.query(MediaObject)
        .filter(MediaObject.device_id == device_id, MediaObject.uploaded_at.is_not(None))
        .order_by(desc(MediaObject.captured_at), desc(MediaObject.created_at))
        .limit(limit)
        .all()
    )


def get_media_for_device(
    session: Session,
    *,
    media_id: str,
    device_id: str,
) -> MediaObject | None:
    return (
        session.query(MediaObject)
        .filter(MediaObject.id == media_id, MediaObject.device_id == device_id)
        .one_or_none()
    )


def read_media_payload(*, media: MediaObject, store: MediaBinaryStore) -> bytes:
    if media.uploaded_at is None:
        raise MediaNotUploadedError("media bytes not uploaded yet")
    return store.read_bytes(object_path=media.object_path)
