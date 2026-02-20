from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS queue (
  message_id TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


@dataclass
class BufferedMessage:
    message_id: str
    payload: Dict[str, Any]
    created_at: str


class SqliteBuffer:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path))

    def _init_db(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(SCHEMA_SQL)
            conn.commit()

    def enqueue(self, message_id: str, payload: Dict[str, Any], created_at: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO queue(message_id, payload_json, created_at) VALUES(?,?,?)",
                (message_id, json.dumps(payload, separators=(",", ":")), created_at),
            )
            conn.commit()

    def dequeue_batch(self, limit: int = 50) -> List[BufferedMessage]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT message_id, payload_json, created_at FROM queue ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        out: List[BufferedMessage] = []
        for message_id, payload_json, created_at in rows:
            out.append(
                BufferedMessage(
                    message_id=message_id, payload=json.loads(payload_json), created_at=created_at
                )
            )
        return out

    def delete(self, message_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM queue WHERE message_id = ?", (message_id,))
            conn.commit()

    def count(self) -> int:
        with self._conn() as conn:
            (n,) = conn.execute("SELECT COUNT(*) FROM queue").fetchone()
        return int(n)

    def prune(self, *, max_messages: int, max_age_s: int) -> int:
        """Prune the queue to protect device storage.

        This agent runs on constrained hardware; we never want an unbounded buffer.

        Strategy
        - Delete messages older than `max_age_s`.
        - If still above `max_messages`, delete oldest until under the limit.

        Returns the number of rows deleted.
        """

        deleted = 0
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - float(max_age_s)

        def _to_ts(created_at: str) -> float | None:
            try:
                dt = datetime.fromisoformat(created_at)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except Exception:
                return None

        with self._conn() as conn:
            rows = conn.execute(
                "SELECT message_id, created_at FROM queue ORDER BY created_at ASC"
            ).fetchall()

            # 1) Age-based pruning
            for message_id, created_at in rows:
                ts = _to_ts(created_at)
                if ts is not None and ts < cutoff:
                    conn.execute("DELETE FROM queue WHERE message_id = ?", (message_id,))
                    deleted += 1

            # 2) Size-based pruning
            (n,) = conn.execute("SELECT COUNT(*) FROM queue").fetchone()
            n_int = int(n)
            if n_int > max_messages:
                to_drop = n_int - max_messages
                drop_ids = conn.execute(
                    "SELECT message_id FROM queue ORDER BY created_at ASC LIMIT ?",
                    (to_drop,),
                ).fetchall()
                for (mid,) in drop_ids:
                    conn.execute("DELETE FROM queue WHERE message_id = ?", (mid,))
                    deleted += 1

            conn.commit()

        return deleted
