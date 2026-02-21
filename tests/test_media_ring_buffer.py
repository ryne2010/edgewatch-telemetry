from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.media.capture import CaptureBusyError, CaptureLock
from agent.media.storage import MediaRingBuffer


def test_ring_buffer_store_writes_asset_and_sidecar(tmp_path: Path) -> None:
    ring = MediaRingBuffer(tmp_path / "media", max_bytes=5_000_000)
    captured_at = datetime(2026, 2, 21, 12, 0, 0, tzinfo=timezone.utc)

    stored = ring.store_photo(
        device_id="demo-well-001",
        camera_id="cam1",
        photo_bytes=b"\xff\xd8\xff\xdbjpeg",
        reason="manual",
        mime_type="image/jpeg",
        captured_at=captured_at,
    )

    assert stored.asset_path.exists()
    assert stored.sidecar_path.exists()

    payload = json.loads(stored.sidecar_path.read_text(encoding="utf-8"))
    assert payload == {
        "bytes": 8,
        "camera_id": "cam1",
        "captured_at": "2026-02-21T12:00:00+00:00",
        "device_id": "demo-well-001",
        "mime_type": "image/jpeg",
        "reason": "manual",
        "sha256": stored.metadata.sha256,
    }


def test_ring_buffer_evicts_oldest_assets_fifo(tmp_path: Path) -> None:
    ring = MediaRingBuffer(tmp_path / "media", max_bytes=5_000_000)
    base = datetime(2026, 2, 21, 12, 0, 0, tzinfo=timezone.utc)

    first = ring.store_photo(
        device_id="demo-well-001",
        camera_id="cam1",
        photo_bytes=b"a" * 128,
        reason="scheduled",
        captured_at=base,
    )
    second = ring.store_photo(
        device_id="demo-well-001",
        camera_id="cam1",
        photo_bytes=b"b" * 128,
        reason="scheduled",
        captured_at=base + timedelta(seconds=1),
    )
    third = ring.store_photo(
        device_id="demo-well-001",
        camera_id="cam1",
        photo_bytes=b"c" * 128,
        reason="scheduled",
        captured_at=base + timedelta(seconds=2),
    )

    ring.max_bytes = second.total_bytes + third.total_bytes
    evicted = ring.enforce_max_bytes()

    assert [item.metadata.captured_at for item in evicted] == [first.metadata.captured_at]
    remaining = ring.list_assets_oldest_first()
    assert [item.metadata.captured_at for item in remaining] == [
        second.metadata.captured_at,
        third.metadata.captured_at,
    ]


def test_ring_buffer_removes_orphan_sidecars(tmp_path: Path) -> None:
    root = tmp_path / "media"
    orphan_sidecar = root / "demo-well-001" / "cam1" / "2026-02-21" / "x.jpg.json"
    orphan_sidecar.parent.mkdir(parents=True, exist_ok=True)
    orphan_sidecar.write_text("{}", encoding="utf-8")

    ring = MediaRingBuffer(root, max_bytes=1024)
    assert ring.list_assets_oldest_first() == []
    assert not orphan_sidecar.exists()


def test_capture_lock_rejects_reentrant_acquire() -> None:
    lock = CaptureLock()
    with lock.hold(timeout_s=0.1):
        with pytest.raises(CaptureBusyError):
            with lock.hold(timeout_s=0.01):
                pass
