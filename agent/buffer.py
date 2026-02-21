from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, TypeVar


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS queue (
  message_id TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""

_T = TypeVar("_T")

_CORRUPTION_MARKERS = (
    "database disk image is malformed",
    "malformed database schema",
    "file is not a database",
    "not a database",
    "database corrupt",
)
_DISK_FULL_MARKERS = ("database or disk is full",)

_ALLOWED_JOURNAL_MODES = {"DELETE", "TRUNCATE", "PERSIST", "MEMORY", "WAL", "OFF"}
_ALLOWED_SYNCHRONOUS = {"OFF", "NORMAL", "FULL", "EXTRA"}
_ALLOWED_TEMP_STORE = {"DEFAULT", "FILE", "MEMORY"}


@dataclass
class BufferedMessage:
    message_id: str
    payload: Dict[str, Any]
    created_at: str


class SqliteBuffer:
    def __init__(
        self,
        path: str,
        *,
        max_db_bytes: int | None = None,
        journal_mode: str = "WAL",
        synchronous: str = "NORMAL",
        temp_store: str = "MEMORY",
        eviction_batch_size: int = 100,
        recover_corruption: bool = True,
    ) -> None:
        self.path = Path(path)
        self.max_db_bytes = max(0, int(max_db_bytes)) if max_db_bytes is not None else None
        if self.max_db_bytes == 0:
            self.max_db_bytes = None

        self.journal_mode = self._normalize_pragma(
            "journal_mode",
            journal_mode,
            allowed=_ALLOWED_JOURNAL_MODES,
            default="WAL",
        )
        self.synchronous = self._normalize_pragma(
            "synchronous",
            synchronous,
            allowed=_ALLOWED_SYNCHRONOUS,
            default="NORMAL",
        )
        self.temp_store = self._normalize_pragma(
            "temp_store",
            temp_store,
            allowed=_ALLOWED_TEMP_STORE,
            default="MEMORY",
        )
        self.eviction_batch_size = max(1, int(eviction_batch_size))
        self.recover_corruption = bool(recover_corruption)
        self.evictions_total = 0

        self._init_db(allow_recovery=True)
        self._checkpoint_with_new_connection(truncate=True)

        # sqlite files have a non-zero on-disk floor (page size + metadata).
        # If the configured quota is below that floor, strict enforcement would
        # permanently thrash the queue. Clamp to the practical minimum instead.
        minimum_bytes = self._db_bytes(include_wal=True)
        if self.max_db_bytes is not None and minimum_bytes > self.max_db_bytes:
            print(
                "[edgewatch-buffer] BUFFER_MAX_DB_BYTES too small (%s); using floor=%s"
                % (self.max_db_bytes, minimum_bytes)
            )
            self.max_db_bytes = minimum_bytes

    @staticmethod
    def _normalize_pragma(name: str, value: str, *, allowed: set[str], default: str) -> str:
        candidate = (value or "").strip().upper()
        if candidate in allowed:
            return candidate
        print(f"[edgewatch-buffer] invalid {name}={value!r}; using {default}")
        return default

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        self._apply_pragmas(conn)
        return conn

    def _apply_pragmas(self, conn: sqlite3.Connection) -> None:
        conn.execute(f"PRAGMA journal_mode={self.journal_mode}")
        conn.execute(f"PRAGMA synchronous={self.synchronous}")
        conn.execute(f"PRAGMA temp_store={self.temp_store}")

    def _init_db(self, *, allow_recovery: bool) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with self._conn() as conn:
                conn.execute(SCHEMA_SQL)
                conn.commit()
        except sqlite3.DatabaseError as exc:
            if allow_recovery and self._is_corruption_error(exc) and self._recover_from_corruption():
                with self._conn() as conn:
                    conn.execute(SCHEMA_SQL)
                    conn.commit()
                return
            raise

    @staticmethod
    def _error_text(exc: BaseException) -> str:
        return str(exc).strip().lower()

    def _is_corruption_error(self, exc: BaseException) -> bool:
        text = self._error_text(exc)
        return any(marker in text for marker in _CORRUPTION_MARKERS)

    @staticmethod
    def _is_disk_full_error(exc: BaseException) -> bool:
        text = SqliteBuffer._error_text(exc)
        return any(marker in text for marker in _DISK_FULL_MARKERS)

    def _corrupt_backup_path(self, source: Path, *, stamp: str) -> Path:
        base = source.with_name(f"{source.name}.corrupt-{stamp}")
        if not base.exists():
            return base
        idx = 1
        while True:
            candidate = source.with_name(f"{source.name}.corrupt-{stamp}-{idx}")
            if not candidate.exists():
                return candidate
            idx += 1

    def _recover_from_corruption(self) -> bool:
        if not self.recover_corruption:
            return False

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        moved: list[Path] = []
        candidates = [
            self.path,
            self.path.with_name(f"{self.path.name}-wal"),
            self.path.with_name(f"{self.path.name}-shm"),
        ]

        for source in candidates:
            if not source.exists():
                continue
            target = self._corrupt_backup_path(source, stamp=stamp)
            try:
                source.replace(target)
            except OSError as exc:
                print(f"[edgewatch-buffer] failed to move corrupt sqlite file {source}: {exc!r}")
                return False
            moved.append(target)

        if moved:
            print(
                "[edgewatch-buffer] detected sqlite corruption; moved files: %s"
                % ", ".join(str(p) for p in moved)
            )

        try:
            self._init_db(allow_recovery=False)
        except sqlite3.Error as exc:
            print(f"[edgewatch-buffer] failed to reinitialize sqlite buffer after corruption: {exc!r}")
            return False
        return True

    def _run_db(self, fn: Callable[[sqlite3.Connection], _T], *, fallback: _T) -> _T:
        try:
            with self._conn() as conn:
                return fn(conn)
        except sqlite3.DatabaseError as exc:
            if self._is_corruption_error(exc) and self._recover_from_corruption():
                try:
                    with self._conn() as conn:
                        return fn(conn)
                except sqlite3.Error as retry_exc:
                    print(f"[edgewatch-buffer] sqlite operation failed after recovery: {retry_exc!r}")
                    return fallback
            print(f"[edgewatch-buffer] sqlite database error: {exc!r}")
            return fallback
        except sqlite3.Error as exc:
            print(f"[edgewatch-buffer] sqlite error: {exc!r}")
            return fallback

    def _insert_message(
        self,
        conn: sqlite3.Connection,
        *,
        message_id: str,
        payload_json: str,
        created_at: str,
    ) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO queue(message_id, payload_json, created_at) VALUES(?,?,?)",
            (message_id, payload_json, created_at),
        )

    def _evict_oldest(self, conn: sqlite3.Connection, *, count: int) -> int:
        rows = conn.execute(
            "SELECT message_id FROM queue ORDER BY created_at ASC LIMIT ?",
            (max(1, int(count)),),
        ).fetchall()
        if not rows:
            return 0
        conn.executemany("DELETE FROM queue WHERE message_id = ?", rows)
        return len(rows)

    def _checkpoint(self, conn: sqlite3.Connection, *, truncate: bool) -> None:
        if self.journal_mode != "WAL":
            return
        mode = "TRUNCATE" if truncate else "PASSIVE"
        try:
            conn.execute(f"PRAGMA wal_checkpoint({mode})")
        except sqlite3.Error:
            return

    def _checkpoint_with_new_connection(self, *, truncate: bool) -> None:
        try:
            with self._conn() as conn:
                self._checkpoint(conn, truncate=truncate)
        except sqlite3.Error:
            return

    def _db_bytes(self, *, include_wal: bool) -> int:
        total = 0
        candidates: list[Path] = [self.path]
        if include_wal:
            candidates.append(self.path.with_name(f"{self.path.name}-wal"))

        for candidate in candidates:
            try:
                if candidate.exists():
                    total += int(candidate.stat().st_size)
            except OSError:
                continue
        return int(total)

    def _enforce_db_size_limit(self, conn: sqlite3.Connection) -> int:
        if self.max_db_bytes is None:
            return 0

        evicted = 0
        current_bytes = self._db_bytes(include_wal=True)
        while current_bytes > self.max_db_bytes:
            dropped = self._evict_oldest(conn, count=self.eviction_batch_size)
            if dropped <= 0:
                break
            evicted += dropped
            conn.commit()
            self._checkpoint(conn, truncate=True)
            current_bytes = self._db_bytes(include_wal=True)

        if evicted > 0:
            self._checkpoint(conn, truncate=True)
            if self._db_bytes(include_wal=True) > self.max_db_bytes:
                conn.execute("VACUUM")
                conn.commit()
                self._checkpoint(conn, truncate=True)

        return evicted

    def _record_evictions(self, conn: sqlite3.Connection, *, evicted: int) -> None:
        if evicted <= 0:
            return
        self.evictions_total += int(evicted)
        print(
            "[edgewatch-buffer] evicted %s queued points (queue=%s bytes=%s/%s)"
            % (
                evicted,
                self._safe_count(conn),
                self._db_bytes(include_wal=True),
                self.max_db_bytes if self.max_db_bytes is not None else "unbounded",
            )
        )

    def enqueue(self, message_id: str, payload: Dict[str, Any], created_at: str) -> bool:
        payload_json = json.dumps(payload, separators=(",", ":"))

        def _op(conn: sqlite3.Connection) -> bool:
            evicted = 0
            try:
                self._insert_message(
                    conn,
                    message_id=message_id,
                    payload_json=payload_json,
                    created_at=created_at,
                )
            except sqlite3.OperationalError as exc:
                if not self._is_disk_full_error(exc):
                    raise

                conn.rollback()
                evicted = self._evict_oldest(conn, count=self.eviction_batch_size)
                conn.commit()
                self._checkpoint(conn, truncate=True)
                if evicted <= 0:
                    print(
                        "[edgewatch-buffer] disk full and no queued rows to evict; dropping message_id=%s"
                        % message_id
                    )
                    return False

                try:
                    self._insert_message(
                        conn,
                        message_id=message_id,
                        payload_json=payload_json,
                        created_at=created_at,
                    )
                except sqlite3.OperationalError as retry_exc:
                    if self._is_disk_full_error(retry_exc):
                        print(
                            "[edgewatch-buffer] disk still full after evicting %s rows; dropping message_id=%s"
                            % (evicted, message_id)
                        )
                        return False
                    raise

            evicted += self._enforce_db_size_limit(conn)
            self._record_evictions(conn, evicted=evicted)
            conn.commit()
            return True

        return bool(self._run_db(_op, fallback=False))

    @staticmethod
    def _safe_count(conn: sqlite3.Connection) -> int:
        (n,) = conn.execute("SELECT COUNT(*) FROM queue").fetchone()
        return int(n)

    def dequeue_batch(self, limit: int = 50) -> List[BufferedMessage]:
        def _op(conn: sqlite3.Connection) -> List[BufferedMessage]:
            rows = conn.execute(
                "SELECT message_id, payload_json, created_at FROM queue ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
            out: List[BufferedMessage] = []
            for message_id, payload_json, created_at in rows:
                try:
                    payload_obj = json.loads(payload_json)
                except json.JSONDecodeError:
                    payload_obj = {}
                out.append(
                    BufferedMessage(
                        message_id=message_id,
                        payload=payload_obj if isinstance(payload_obj, dict) else {},
                        created_at=created_at,
                    )
                )
            return out

        return self._run_db(_op, fallback=[])

    def delete(self, message_id: str) -> None:
        def _op(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM queue WHERE message_id = ?", (message_id,))
            conn.commit()

        self._run_db(_op, fallback=None)

    def count(self) -> int:
        def _op(conn: sqlite3.Connection) -> int:
            (n,) = conn.execute("SELECT COUNT(*) FROM queue").fetchone()
            return int(n)

        return int(self._run_db(_op, fallback=0))

    def db_bytes(self) -> int:
        return self._db_bytes(include_wal=True)

    def metrics(self) -> Dict[str, int]:
        return {
            "buffer_db_bytes": int(self.db_bytes()),
            "buffer_queue_depth": int(self.count()),
            "buffer_evictions_total": int(self.evictions_total),
        }

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

        def _op(conn: sqlite3.Connection) -> int:
            deleted_local = 0
            rows = conn.execute("SELECT message_id, created_at FROM queue ORDER BY created_at ASC").fetchall()

            # 1) Age-based pruning
            for message_id, created_at in rows:
                ts = _to_ts(created_at)
                if ts is not None and ts < cutoff:
                    conn.execute("DELETE FROM queue WHERE message_id = ?", (message_id,))
                    deleted_local += 1

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
                    deleted_local += 1

            quota_evicted = self._enforce_db_size_limit(conn)
            if quota_evicted:
                deleted_local += quota_evicted
                self._record_evictions(conn, evicted=quota_evicted)

            conn.commit()
            return deleted_local

        deleted = int(self._run_db(_op, fallback=0))
        return deleted
