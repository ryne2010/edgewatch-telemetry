from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .chirpstack import ChirpStackUplink
from .protocol import WAKE_SIZE


_ACTIVE_WAKE_STATES = ("waiting_uplink", "publishing", "waiting_ready")
_WAKE_STATES = (*_ACTIVE_WAKE_STATES, "ready", "expired", "timed_out", "failed")
_ALERT_TRIGGER_STATES = ("pending", "processing", "completed")


class StoreConflictError(RuntimeError):
    """Raised when a stable identifier is replayed with different immutable data."""


@dataclass(frozen=True)
class OutboxItem:
    message_id: str
    device_id: str
    payload: dict[str, Any]
    attempts: int


@dataclass(frozen=True)
class AlertTrigger:
    message_id: str
    application_id: str
    dev_eui: str
    envelope_json: str
    attempts: int


@dataclass(frozen=True)
class WakeRecord:
    command_id: str
    command_token: bytes
    device_id: str
    dev_eui: str
    issued_at: int
    expires_at: int
    readiness_timeout_s: int
    nonce: int
    payload: bytes
    state: str
    attempts: int
    available_at: int
    uplink_seen_at: int | None
    downlink_sent_at: int | None
    ready_deadline: int | None
    ready_at: int | None
    failure_code: str | None


def _positive_int(value: int, *, where: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{where} must be from 1 through {maximum}")
    return value


def _timestamp(value: int | None) -> int:
    candidate = int(time.time()) if value is None else value
    if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate < 0:
        raise ValueError("timestamp must be a non-negative integer")
    return candidate


def _reason_code(value: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 80
        or any(not (char.isalnum() or char in "_.:-") for char in value)
    ):
        raise ValueError("failure code must use 1..80 safe identifier characters")
    return value


class GatewayStore:
    """SQLite durability boundary for uplink dedupe, delivery retry, and wake state."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self.path.chmod(0o600)

    @contextmanager
    def _connection(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with sqlite3.connect(str(self.path), timeout=10) as db:
            db.executescript(
                f"""
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                PRAGMA synchronous=FULL;
                CREATE TABLE IF NOT EXISTS lorawan_uplinks (
                    message_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    dev_eui TEXT NOT NULL,
                    application_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    frame BLOB NOT NULL,
                    envelope_json TEXT NOT NULL,
                    received_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lorawan_outbox (
                    message_id TEXT PRIMARY KEY REFERENCES lorawan_uplinks(message_id),
                    device_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'sending', 'delivered')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at INTEGER NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at INTEGER,
                    failure_code TEXT,
                    delivered_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS lorawan_outbox_ready
                    ON lorawan_outbox(status, available_at, message_id);
                CREATE TRIGGER IF NOT EXISTS lorawan_uplinks_immutable
                    BEFORE UPDATE ON lorawan_uplinks
                    BEGIN SELECT RAISE(ABORT, 'LoRaWAN uplinks are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS lorawan_outbox_payload_immutable
                    BEFORE UPDATE OF message_id, device_id, payload_json ON lorawan_outbox
                    BEGIN SELECT RAISE(ABORT, 'LoRaWAN outbox payload is immutable'); END;

                CREATE TABLE IF NOT EXISTS lorawan_alert_triggers (
                    message_id TEXT PRIMARY KEY REFERENCES lorawan_uplinks(message_id),
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN {repr(_ALERT_TRIGGER_STATES)}),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at INTEGER NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at INTEGER,
                    failure_code TEXT,
                    completed_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS lorawan_alert_triggers_ready
                    ON lorawan_alert_triggers(status, available_at, message_id);
                CREATE TRIGGER IF NOT EXISTS lorawan_alert_trigger_identity_immutable
                    BEFORE UPDATE OF message_id ON lorawan_alert_triggers
                    BEGIN SELECT RAISE(ABORT, 'LoRaWAN alert trigger identity is immutable'); END;

                CREATE TABLE IF NOT EXISTS maintenance_wakes (
                    command_id TEXT PRIMARY KEY,
                    command_token BLOB NOT NULL UNIQUE,
                    device_id TEXT NOT NULL,
                    dev_eui TEXT NOT NULL,
                    issued_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    readiness_timeout_s INTEGER NOT NULL,
                    nonce INTEGER NOT NULL,
                    payload BLOB NOT NULL,
                    state TEXT NOT NULL CHECK(state IN {repr(_WAKE_STATES)}),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at INTEGER NOT NULL,
                    lease_owner TEXT,
                    lease_expires_at INTEGER,
                    uplink_seen_at INTEGER,
                    downlink_sent_at INTEGER,
                    ready_deadline INTEGER,
                    ready_at INTEGER,
                    failure_code TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS maintenance_one_active_per_device
                    ON maintenance_wakes(device_id)
                    WHERE state IN ('waiting_uplink', 'publishing', 'waiting_ready');
                CREATE INDEX IF NOT EXISTS maintenance_wakes_pending
                    ON maintenance_wakes(dev_eui, state, available_at, expires_at);
                CREATE TRIGGER IF NOT EXISTS maintenance_wake_identity_immutable
                    BEFORE UPDATE OF command_id, command_token, device_id, dev_eui, issued_at,
                        expires_at, readiness_timeout_s, nonce, payload ON maintenance_wakes
                    BEGIN SELECT RAISE(ABORT, 'maintenance wake identity is immutable'); END;
                """
            )

    @staticmethod
    def _canonical_json(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def enqueue_uplink(self, uplink: ChirpStackUplink, *, received_at: int | None = None) -> bool:
        now = _timestamp(received_at)
        payload_json = self._canonical_json(uplink.canonical_point)
        with self._connection(immediate=True) as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO lorawan_uplinks("
                "message_id, device_id, dev_eui, application_id, sequence, frame, envelope_json, received_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    uplink.message_id,
                    uplink.device_id,
                    uplink.dev_eui,
                    uplink.application_id,
                    uplink.frame.sequence,
                    uplink.frame_bytes,
                    uplink.envelope_json,
                    now,
                ),
            )
            if cursor.rowcount == 0:
                row = db.execute(
                    "SELECT device_id, dev_eui, application_id, frame FROM lorawan_uplinks "
                    "WHERE message_id=?",
                    (uplink.message_id,),
                ).fetchone()
                if row is None or (
                    row["device_id"] != uplink.device_id
                    or row["dev_eui"] != uplink.dev_eui
                    or row["application_id"] != uplink.application_id
                    or bytes(row["frame"]) != uplink.frame_bytes
                ):
                    raise StoreConflictError("LoRaWAN message_id was reused with different immutable data")
                return False
            db.execute(
                "INSERT INTO lorawan_outbox(message_id, device_id, payload_json, available_at) "
                "VALUES (?, ?, ?, ?)",
                (uplink.message_id, uplink.device_id, payload_json, now),
            )
            if uplink.requires_immediate_alert:
                db.execute(
                    "INSERT INTO lorawan_alert_triggers(message_id, available_at) VALUES (?, ?)",
                    (uplink.message_id, now),
                )
            return True

    def claim_alert_triggers(
        self,
        owner: str,
        *,
        now: int | None = None,
        lease_s: int = 30,
        limit: int = 100,
    ) -> tuple[AlertTrigger, ...]:
        lease_owner = self._owner(owner)
        timestamp = _timestamp(now)
        lease = _positive_int(lease_s, where="lease_s", maximum=300)
        batch = _positive_int(limit, where="limit", maximum=100)
        with self._connection(immediate=True) as db:
            rows = db.execute(
                "SELECT message_id FROM lorawan_alert_triggers WHERE "
                "((status='pending' AND available_at<=?) OR "
                " (status='processing' AND lease_expires_at<=?)) "
                "ORDER BY available_at, message_id LIMIT ?",
                (timestamp, timestamp, batch),
            ).fetchall()
            message_ids = [str(row["message_id"]) for row in rows]
            for message_id in message_ids:
                db.execute(
                    "UPDATE lorawan_alert_triggers SET status='processing', attempts=attempts+1, "
                    "lease_owner=?, lease_expires_at=?, failure_code=NULL WHERE message_id=?",
                    (lease_owner, timestamp + lease, message_id),
                )
            if not message_ids:
                return ()
            placeholders = ",".join("?" for _ in message_ids)
            claimed = db.execute(
                "SELECT trigger.message_id, trigger.attempts, uplink.application_id, "
                "uplink.dev_eui, uplink.envelope_json "
                "FROM lorawan_alert_triggers AS trigger "
                "JOIN lorawan_uplinks AS uplink ON uplink.message_id=trigger.message_id "
                f"WHERE trigger.message_id IN ({placeholders}) "
                "ORDER BY trigger.available_at, trigger.message_id",
                message_ids,
            ).fetchall()
            return tuple(
                AlertTrigger(
                    message_id=str(row["message_id"]),
                    application_id=str(row["application_id"]),
                    dev_eui=str(row["dev_eui"]),
                    envelope_json=str(row["envelope_json"]),
                    attempts=int(row["attempts"]),
                )
                for row in claimed
            )

    def mark_alert_trigger_completed(
        self,
        message_id: str,
        owner: str,
        *,
        now: int | None = None,
    ) -> bool:
        timestamp = _timestamp(now)
        with self._connection(immediate=True) as db:
            cursor = db.execute(
                "UPDATE lorawan_alert_triggers SET status='completed', completed_at=?, "
                "lease_owner=NULL, lease_expires_at=NULL, failure_code=NULL "
                "WHERE message_id=? AND status='processing' AND lease_owner=?",
                (timestamp, message_id, self._owner(owner)),
            )
            return cursor.rowcount == 1

    def retry_alert_trigger(
        self,
        message_id: str,
        owner: str,
        *,
        failure_code: str,
        retry_after_s: int,
        now: int | None = None,
    ) -> bool:
        timestamp = _timestamp(now)
        delay = _positive_int(retry_after_s, where="retry_after_s", maximum=3_600)
        code = _reason_code(failure_code)
        with self._connection(immediate=True) as db:
            cursor = db.execute(
                "UPDATE lorawan_alert_triggers SET status='pending', available_at=?, "
                "lease_owner=NULL, lease_expires_at=NULL, failure_code=? "
                "WHERE message_id=? AND status='processing' AND lease_owner=?",
                (timestamp + delay, code, message_id, self._owner(owner)),
            )
            return cursor.rowcount == 1

    def alert_trigger_counts(self) -> dict[str, int]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT status, COUNT(*) AS count FROM lorawan_alert_triggers GROUP BY status"
            ).fetchall()
            counts = {"pending": 0, "processing": 0, "completed": 0}
            counts.update({str(row["status"]): int(row["count"]) for row in rows})
            return counts

    def claim_outbox(
        self,
        owner: str,
        *,
        now: int | None = None,
        lease_s: int = 60,
        limit: int = 10,
    ) -> tuple[OutboxItem, ...]:
        owner = self._owner(owner)
        timestamp = _timestamp(now)
        lease = _positive_int(lease_s, where="lease_s", maximum=3_600)
        batch = _positive_int(limit, where="limit", maximum=100)
        with self._connection(immediate=True) as db:
            rows = db.execute(
                "SELECT message_id FROM lorawan_outbox WHERE "
                "((status='pending' AND available_at<=?) OR "
                " (status='sending' AND lease_expires_at<=?)) "
                "ORDER BY available_at, message_id LIMIT ?",
                (timestamp, timestamp, batch),
            ).fetchall()
            message_ids = [str(row["message_id"]) for row in rows]
            for message_id in message_ids:
                db.execute(
                    "UPDATE lorawan_outbox SET status='sending', attempts=attempts+1, "
                    "lease_owner=?, lease_expires_at=?, failure_code=NULL WHERE message_id=?",
                    (owner, timestamp + lease, message_id),
                )
            if not message_ids:
                return ()
            placeholders = ",".join("?" for _ in message_ids)
            claimed = db.execute(
                f"SELECT message_id, device_id, payload_json, attempts FROM lorawan_outbox "
                f"WHERE message_id IN ({placeholders}) ORDER BY available_at, message_id",
                message_ids,
            ).fetchall()
            return tuple(
                OutboxItem(
                    message_id=str(row["message_id"]),
                    device_id=str(row["device_id"]),
                    payload=json.loads(str(row["payload_json"])),
                    attempts=int(row["attempts"]),
                )
                for row in claimed
            )

    def mark_outbox_delivered(self, message_id: str, owner: str, *, now: int | None = None) -> bool:
        timestamp = _timestamp(now)
        with self._connection(immediate=True) as db:
            cursor = db.execute(
                "UPDATE lorawan_outbox SET status='delivered', delivered_at=?, lease_owner=NULL, "
                "lease_expires_at=NULL, failure_code=NULL "
                "WHERE message_id=? AND status='sending' AND lease_owner=?",
                (timestamp, message_id, self._owner(owner)),
            )
            return cursor.rowcount == 1

    def retry_outbox(
        self,
        message_id: str,
        owner: str,
        *,
        failure_code: str,
        retry_after_s: int,
        now: int | None = None,
    ) -> bool:
        timestamp = _timestamp(now)
        delay = _positive_int(retry_after_s, where="retry_after_s", maximum=86_400)
        code = _reason_code(failure_code)
        with self._connection(immediate=True) as db:
            cursor = db.execute(
                "UPDATE lorawan_outbox SET status='pending', available_at=?, lease_owner=NULL, "
                "lease_expires_at=NULL, failure_code=? "
                "WHERE message_id=? AND status='sending' AND lease_owner=?",
                (timestamp + delay, code, message_id, self._owner(owner)),
            )
            return cursor.rowcount == 1

    def outbox_counts(self) -> dict[str, int]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT status, COUNT(*) AS count FROM lorawan_outbox GROUP BY status"
            ).fetchall()
            counts = {"pending": 0, "sending": 0, "delivered": 0}
            counts.update({str(row["status"]): int(row["count"]) for row in rows})
            return counts

    @staticmethod
    def _owner(owner: str) -> str:
        if (
            not isinstance(owner, str)
            or not 1 <= len(owner) <= 64
            or any(not (char.isalnum() or char in "_.:-") for char in owner)
        ):
            raise ValueError("lease owner must use 1..64 safe identifier characters")
        return owner

    def create_wake(
        self,
        *,
        command_id: str,
        command_token: bytes,
        device_id: str,
        dev_eui: str,
        issued_at: int,
        expires_at: int,
        readiness_timeout_s: int,
        nonce: int,
        payload: bytes,
    ) -> bool:
        if not isinstance(command_id, str) or not command_id or len(command_id) > 128:
            raise ValueError("command_id must be a non-empty string of at most 128 characters")
        if not isinstance(command_token, bytes) or len(command_token) != 8:
            raise ValueError("command_token must be exactly 8 bytes")
        if not isinstance(device_id, str) or not device_id:
            raise ValueError("device_id must be a non-empty string")
        if not isinstance(dev_eui, str) or len(dev_eui) != 16:
            raise ValueError("dev_eui must contain exactly 16 hexadecimal characters")
        try:
            bytes.fromhex(dev_eui)
        except ValueError as exc:
            raise ValueError("dev_eui must contain exactly 16 hexadecimal characters") from exc
        if (
            isinstance(issued_at, bool)
            or not isinstance(issued_at, int)
            or isinstance(expires_at, bool)
            or not isinstance(expires_at, int)
            or issued_at < 0
            or expires_at < issued_at
        ):
            raise ValueError("wake timestamps are invalid")
        _positive_int(readiness_timeout_s, where="readiness_timeout_s", maximum=3_600)
        if readiness_timeout_s < 5:
            raise ValueError("readiness_timeout_s must be from 5 through 3600")
        if isinstance(nonce, bool) or not isinstance(nonce, int) or not 0 <= nonce <= (1 << 32) - 1:
            raise ValueError("nonce must be an unsigned 32-bit integer")
        if not isinstance(payload, bytes) or len(payload) != WAKE_SIZE:
            raise ValueError(f"wake payload must be exactly {WAKE_SIZE} bytes")
        with self._connection(immediate=True) as db:
            existing = db.execute(
                "SELECT * FROM maintenance_wakes WHERE command_id=?", (command_id,)
            ).fetchone()
            immutable = (
                bytes(command_token),
                device_id,
                dev_eui,
                issued_at,
                expires_at,
                readiness_timeout_s,
                nonce,
                bytes(payload),
            )
            if existing is not None:
                persisted = (
                    bytes(existing["command_token"]),
                    str(existing["device_id"]),
                    str(existing["dev_eui"]),
                    int(existing["issued_at"]),
                    int(existing["expires_at"]),
                    int(existing["readiness_timeout_s"]),
                    int(existing["nonce"]),
                    bytes(existing["payload"]),
                )
                if persisted != immutable:
                    raise StoreConflictError("command_id was reused with different wake data")
                return False
            try:
                db.execute(
                    "INSERT INTO maintenance_wakes("
                    "command_id, command_token, device_id, dev_eui, issued_at, expires_at, "
                    "readiness_timeout_s, nonce, payload, state, available_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'waiting_uplink', ?)",
                    (command_id, *immutable, issued_at),
                )
            except sqlite3.IntegrityError as exc:
                if "maintenance_wakes.device_id" in str(exc):
                    raise StoreConflictError("device already has an active maintenance wake") from exc
                raise
            return True

    def get_wake(self, command_id: str) -> WakeRecord | None:
        with self._connection() as db:
            row = db.execute("SELECT * FROM maintenance_wakes WHERE command_id=?", (command_id,)).fetchone()
            return None if row is None else self._wake_record(row)

    def expire_wakes(self, *, now: int | None = None) -> int:
        timestamp = _timestamp(now)
        with self._connection(immediate=True) as db:
            expired = db.execute(
                "UPDATE maintenance_wakes SET state='expired', lease_owner=NULL, lease_expires_at=NULL, "
                "failure_code='expired' WHERE state IN ('waiting_uplink', 'publishing', 'waiting_ready') "
                "AND expires_at<?",
                (timestamp,),
            ).rowcount
            timed_out = db.execute(
                "UPDATE maintenance_wakes SET state='timed_out', lease_owner=NULL, lease_expires_at=NULL, "
                "failure_code='readiness_timeout' WHERE state='waiting_ready' "
                "AND ready_deadline<?",
                (timestamp,),
            ).rowcount
            return int(expired + timed_out)

    def claim_wake_for_uplink(
        self,
        dev_eui: str,
        owner: str,
        *,
        now: int | None = None,
        lease_s: int = 30,
    ) -> WakeRecord | None:
        timestamp = _timestamp(now)
        lease = _positive_int(lease_s, where="lease_s", maximum=300)
        lease_owner = self._owner(owner)
        self.expire_wakes(now=timestamp)
        with self._connection(immediate=True) as db:
            row = db.execute(
                "SELECT command_id FROM maintenance_wakes WHERE dev_eui=? AND expires_at>=? AND "
                "((state='waiting_uplink' AND available_at<=?) OR "
                " (state='publishing' AND lease_expires_at<=?)) "
                "ORDER BY issued_at LIMIT 1",
                (dev_eui, timestamp, timestamp, timestamp),
            ).fetchone()
            if row is None:
                return None
            command_id = str(row["command_id"])
            db.execute(
                "UPDATE maintenance_wakes SET state='publishing', attempts=attempts+1, "
                "lease_owner=?, lease_expires_at=?, uplink_seen_at=?, failure_code=NULL "
                "WHERE command_id=?",
                (lease_owner, timestamp + lease, timestamp, command_id),
            )
            claimed = db.execute(
                "SELECT * FROM maintenance_wakes WHERE command_id=?", (command_id,)
            ).fetchone()
            return self._wake_record(claimed)

    def mark_wake_published(self, command_id: str, owner: str, *, now: int | None = None) -> bool:
        timestamp = _timestamp(now)
        lease_owner = self._owner(owner)
        with self._connection(immediate=True) as db:
            row = db.execute(
                "SELECT expires_at, readiness_timeout_s FROM maintenance_wakes "
                "WHERE command_id=? AND state='publishing' AND lease_owner=?",
                (command_id, lease_owner),
            ).fetchone()
            if row is None:
                return False
            deadline = min(int(row["expires_at"]), timestamp + int(row["readiness_timeout_s"]))
            cursor = db.execute(
                "UPDATE maintenance_wakes SET state='waiting_ready', downlink_sent_at=?, "
                "ready_deadline=?, lease_owner=NULL, lease_expires_at=NULL "
                "WHERE command_id=? AND state='publishing' AND lease_owner=?",
                (timestamp, deadline, command_id, lease_owner),
            )
            return cursor.rowcount == 1

    def retry_wake_publish(
        self,
        command_id: str,
        owner: str,
        *,
        failure_code: str,
        retry_after_s: int,
        now: int | None = None,
    ) -> bool:
        timestamp = _timestamp(now)
        code = _reason_code(failure_code)
        delay = _positive_int(retry_after_s, where="retry_after_s", maximum=3_600)
        with self._connection(immediate=True) as db:
            cursor = db.execute(
                "UPDATE maintenance_wakes SET state='waiting_uplink', available_at=?, "
                "lease_owner=NULL, lease_expires_at=NULL, failure_code=? "
                "WHERE command_id=? AND state='publishing' AND lease_owner=?",
                (timestamp + delay, code, command_id, self._owner(owner)),
            )
            return cursor.rowcount == 1

    def mark_device_ready(
        self,
        dev_eui: str,
        command_token: bytes,
        *,
        now: int | None = None,
    ) -> tuple[str, ...]:
        if not isinstance(command_token, bytes) or len(command_token) != 8:
            raise ValueError("command_token must be exactly 8 bytes")
        timestamp = _timestamp(now)
        self.expire_wakes(now=timestamp)
        with self._connection(immediate=True) as db:
            rows = db.execute(
                "SELECT command_id FROM maintenance_wakes WHERE dev_eui=? AND state='waiting_ready' "
                "AND command_token=? AND expires_at>=? AND ready_deadline>=? ORDER BY issued_at",
                (dev_eui, command_token, timestamp, timestamp),
            ).fetchall()
            command_ids = tuple(str(row["command_id"]) for row in rows)
            if command_ids:
                placeholders = ",".join("?" for _ in command_ids)
                db.execute(
                    f"UPDATE maintenance_wakes SET state='ready', ready_at=?, failure_code=NULL "
                    f"WHERE command_id IN ({placeholders})",
                    (timestamp, *command_ids),
                )
            return command_ids

    @staticmethod
    def _wake_record(row: sqlite3.Row) -> WakeRecord:
        return WakeRecord(
            command_id=str(row["command_id"]),
            command_token=bytes(row["command_token"]),
            device_id=str(row["device_id"]),
            dev_eui=str(row["dev_eui"]),
            issued_at=int(row["issued_at"]),
            expires_at=int(row["expires_at"]),
            readiness_timeout_s=int(row["readiness_timeout_s"]),
            nonce=int(row["nonce"]),
            payload=bytes(row["payload"]),
            state=str(row["state"]),
            attempts=int(row["attempts"]),
            available_at=int(row["available_at"]),
            uplink_seen_at=(None if row["uplink_seen_at"] is None else int(row["uplink_seen_at"])),
            downlink_sent_at=(None if row["downlink_sent_at"] is None else int(row["downlink_sent_at"])),
            ready_deadline=(None if row["ready_deadline"] is None else int(row["ready_deadline"])),
            ready_at=None if row["ready_at"] is None else int(row["ready_at"]),
            failure_code=None if row["failure_code"] is None else str(row["failure_code"]),
        )
