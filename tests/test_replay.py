from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agent.replay import _iter_replay_points, _parse_dt


def _setup_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE queue (
                message_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def test_iter_replay_points_filters_by_range_and_preserves_message_id(tmp_path: Path) -> None:
    db_path = tmp_path / "buffer.sqlite"
    _setup_db(db_path)

    payload_1 = {"message_id": "m-1", "ts": "2026-01-01T00:00:00+00:00", "metrics": {"x": 1}}
    payload_2 = {"message_id": "m-2", "ts": "2026-01-01T00:10:00+00:00", "metrics": {"x": 2}}
    payload_3 = {"message_id": "wrong", "ts": "2026-01-01T00:20:00+00:00", "metrics": {"x": 3}}

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO queue(message_id, payload_json, created_at) VALUES (?, ?, ?)",
            ("m-1", json.dumps(payload_1), payload_1["ts"]),
        )
        conn.execute(
            "INSERT INTO queue(message_id, payload_json, created_at) VALUES (?, ?, ?)",
            ("m-2", json.dumps(payload_2), payload_2["ts"]),
        )
        conn.execute(
            "INSERT INTO queue(message_id, payload_json, created_at) VALUES (?, ?, ?)",
            ("m-3", json.dumps(payload_3), payload_3["ts"]),
        )
        conn.commit()

    points = _iter_replay_points(
        db_path=str(db_path),
        since=_parse_dt("2026-01-01T00:05:00+00:00"),
        until=_parse_dt("2026-01-01T00:30:00+00:00"),
        max_points=None,
    )

    assert [p["message_id"] for p in points] == ["m-2", "m-3"]


def test_iter_replay_points_honors_max_points(tmp_path: Path) -> None:
    db_path = tmp_path / "buffer.sqlite"
    _setup_db(db_path)

    with sqlite3.connect(db_path) as conn:
        for i in range(5):
            ts = f"2026-01-01T00:0{i}:00+00:00"
            payload = {"message_id": f"m-{i}", "ts": ts, "metrics": {"x": i}}
            conn.execute(
                "INSERT INTO queue(message_id, payload_json, created_at) VALUES (?, ?, ?)",
                (f"m-{i}", json.dumps(payload), ts),
            )
        conn.commit()

    points = _iter_replay_points(
        db_path=str(db_path),
        since=_parse_dt("2026-01-01T00:00:00+00:00"),
        until=None,
        max_points=2,
    )

    assert len(points) == 2
    assert [p["message_id"] for p in points] == ["m-0", "m-1"]
