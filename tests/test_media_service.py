from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from api.app.db import Base
from api.app.models import Device
from api.app.services.media import (
    LocalMediaStore,
    MediaConflictError,
    MediaCreateInput,
    MediaNotUploadedError,
    MediaValidationError,
    build_object_path,
    create_or_get_media_object,
    list_device_media,
    read_media_payload,
    upload_media_payload,
)


def _session_with_device(tmp_path: Path) -> Session:
    db_path = tmp_path / "media.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = maker()
    session.add(
        Device(
            device_id="demo-well-001",
            display_name="Demo",
            token_hash="hash",
            token_fingerprint="fingerprint",
            heartbeat_interval_s=300,
            offline_after_s=900,
            enabled=True,
        )
    )
    session.commit()
    return session


def test_build_object_path_is_deterministic() -> None:
    path = build_object_path(
        device_id="demo-well-001",
        camera_id="cam1",
        captured_at=datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc),
        message_id="msg-123",
        mime_type="image/jpeg",
    )
    assert path == "demo-well-001/cam1/2026-02-21/msg-123.jpg"


def test_create_metadata_is_idempotent_and_detects_conflict(tmp_path: Path) -> None:
    session = _session_with_device(tmp_path)
    try:
        store = LocalMediaStore(root_dir=str(tmp_path / "media"))
        created_at = datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc)
        payload = b"image-data"
        digest = hashlib.sha256(payload).hexdigest()

        first, first_created = create_or_get_media_object(
            session,
            device_id="demo-well-001",
            create=MediaCreateInput(
                message_id="msg-1",
                camera_id="cam1",
                captured_at=created_at,
                reason="manual",
                sha256=digest,
                bytes=len(payload),
                mime_type="image/jpeg",
            ),
            store=store,
        )
        session.commit()

        second, second_created = create_or_get_media_object(
            session,
            device_id="demo-well-001",
            create=MediaCreateInput(
                message_id="msg-1",
                camera_id="cam1",
                captured_at=created_at,
                reason="manual",
                sha256=digest,
                bytes=len(payload),
                mime_type="image/jpeg",
            ),
            store=store,
        )

        assert first_created is True
        assert second_created is False
        assert first.id == second.id

        with pytest.raises(MediaConflictError):
            create_or_get_media_object(
                session,
                device_id="demo-well-001",
                create=MediaCreateInput(
                    message_id="msg-1",
                    camera_id="cam1",
                    captured_at=created_at,
                    reason="manual",
                    sha256=digest,
                    bytes=len(payload) + 1,
                    mime_type="image/jpeg",
                ),
                store=store,
            )
    finally:
        session.close()


def test_upload_and_read_local_media(tmp_path: Path) -> None:
    session = _session_with_device(tmp_path)
    try:
        store = LocalMediaStore(root_dir=str(tmp_path / "media"))
        payload = b"\xff\xd8\xff\xdbjpeg"
        digest = hashlib.sha256(payload).hexdigest()

        media, _ = create_or_get_media_object(
            session,
            device_id="demo-well-001",
            create=MediaCreateInput(
                message_id="msg-upload",
                camera_id="cam1",
                captured_at=datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc),
                reason="scheduled",
                sha256=digest,
                bytes=len(payload),
                mime_type="image/jpeg",
            ),
            store=store,
        )
        session.commit()

        with pytest.raises(MediaNotUploadedError):
            read_media_payload(media=media, store=store)

        updated = upload_media_payload(
            session,
            media=media,
            payload=payload,
            content_type="image/jpeg",
            store=store,
        )
        session.commit()
        assert updated.uploaded_at is not None
        assert read_media_payload(media=updated, store=store) == payload

        listed = list_device_media(session, device_id="demo-well-001", limit=10)
        assert [row.id for row in listed] == [updated.id]

        with pytest.raises(MediaValidationError):
            upload_media_payload(
                session,
                media=updated,
                payload=b"bad",
                content_type="image/jpeg",
                store=store,
            )
    finally:
        session.close()
