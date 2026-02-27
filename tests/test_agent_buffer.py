from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from agent.buffer import SqliteBuffer


def _entry(idx: int, *, pad_bytes: int = 0) -> tuple[str, dict[str, Any], str]:
    message_id = f"m-{idx}"
    ts = f"2026-01-01T00:{idx % 60:02d}:00+00:00"
    payload: dict[str, Any] = {
        "message_id": message_id,
        "ts": ts,
        "metrics": {
            "value": idx,
            "pad": "x" * pad_bytes,
        },
    }
    return message_id, payload, ts


def test_buffer_applies_sqlite_pragmas(tmp_path: Path) -> None:
    buf = SqliteBuffer(
        str(tmp_path / "buffer.sqlite"),
        journal_mode="wal",
        synchronous="normal",
        temp_store="memory",
    )

    with buf._conn() as conn:  # noqa: SLF001 - test verifies configured pragmas
        (journal_mode,) = conn.execute("PRAGMA journal_mode").fetchone()
        (synchronous,) = conn.execute("PRAGMA synchronous").fetchone()
        (temp_store,) = conn.execute("PRAGMA temp_store").fetchone()

    assert str(journal_mode).lower() == "wal"
    assert int(synchronous) == 1
    assert int(temp_store) == 2


def test_buffer_enforces_quota_and_reports_metrics(tmp_path: Path) -> None:
    path = tmp_path / "buffer.sqlite"
    probe = SqliteBuffer(str(path))
    baseline = probe.db_bytes()

    limit = baseline + 12_288
    buf = SqliteBuffer(str(path), max_db_bytes=limit, eviction_batch_size=1)

    for idx in range(48):
        message_id, payload, ts = _entry(idx, pad_bytes=1400)
        assert buf.enqueue(message_id, payload, ts) is True

    with buf._conn() as conn:  # noqa: SLF001 - test needs sqlite page size to compute envelope
        (page_size,) = conn.execute("PRAGMA page_size").fetchone()

    # SQLite file/WAL accounting grows in page increments and includes small WAL
    # bookkeeping overhead, so quota enforcement may exceed the configured cap by
    # about one page plus header bytes on some platforms.
    allowed_bytes = limit + int(page_size) + 512
    assert buf.db_bytes() <= allowed_bytes
    assert buf.evictions_total > 0

    metrics = buf.metrics()
    assert metrics["buffer_db_bytes"] <= allowed_bytes
    assert metrics["buffer_queue_depth"] == buf.count()
    assert metrics["buffer_evictions_total"] == buf.evictions_total


def test_enqueue_disk_full_evicts_oldest_and_retries(monkeypatch, tmp_path: Path) -> None:
    buf = SqliteBuffer(str(tmp_path / "buffer.sqlite"), eviction_batch_size=1)

    m1, p1, ts1 = _entry(1)
    m2, p2, ts2 = _entry(2)
    assert buf.enqueue(m1, p1, ts1) is True
    assert buf.enqueue(m2, p2, ts2) is True

    original_insert = buf._insert_message  # noqa: SLF001 - controlled disk-full simulation in test
    attempts = {"n": 0}

    def _flaky_insert(
        conn: sqlite3.Connection,
        *,
        message_id: str,
        payload_json: str,
        created_at: str,
    ) -> None:
        if attempts["n"] == 0:
            attempts["n"] += 1
            raise sqlite3.OperationalError("database or disk is full")
        original_insert(
            conn,
            message_id=message_id,
            payload_json=payload_json,
            created_at=created_at,
        )

    monkeypatch.setattr(buf, "_insert_message", _flaky_insert)

    m3, p3, ts3 = _entry(3)
    assert buf.enqueue(m3, p3, ts3) is True

    queued_ids = [row.message_id for row in buf.dequeue_batch(limit=10)]
    assert queued_ids == [m2, m3]
    assert buf.evictions_total == 1


def test_enqueue_disk_full_with_empty_queue_drops_point(monkeypatch, tmp_path: Path) -> None:
    buf = SqliteBuffer(str(tmp_path / "buffer.sqlite"), eviction_batch_size=1)

    def _always_fail(
        conn: sqlite3.Connection,
        *,
        message_id: str,
        payload_json: str,
        created_at: str,
    ) -> None:
        _ = (conn, message_id, payload_json, created_at)
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(buf, "_insert_message", _always_fail)

    message_id, payload, ts = _entry(1)
    assert buf.enqueue(message_id, payload, ts) is False
    assert buf.count() == 0


def test_buffer_recovers_from_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "buffer.sqlite"
    path.write_bytes(b"not-a-sqlite-db")

    buf = SqliteBuffer(str(path), recover_corruption=True)
    backups = list(tmp_path.glob("buffer.sqlite.corrupt-*"))
    assert backups
    assert path.exists()

    message_id, payload, ts = _entry(1)
    assert buf.enqueue(message_id, payload, ts) is True
    assert buf.count() == 1


def test_prune_deletes_oldest_when_over_max_messages(tmp_path: Path) -> None:
    buf = SqliteBuffer(str(tmp_path / "buffer.sqlite"))

    for idx in range(4):
        message_id, payload, ts = _entry(idx)
        assert buf.enqueue(message_id, payload, ts) is True

    deleted = buf.prune(max_messages=2, max_age_s=10 * 365 * 24 * 3600)

    assert deleted == 2
    assert [row.message_id for row in buf.dequeue_batch(limit=10)] == ["m-2", "m-3"]
