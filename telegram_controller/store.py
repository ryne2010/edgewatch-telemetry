from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence


class StoreError(RuntimeError):
    pass


class ConfirmationError(StoreError):
    pass


class ControllerStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        Path(self.path).chmod(0o600)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS processed_updates(update_id INTEGER PRIMARY KEY, processed_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS commands(command_id TEXT PRIMARY KEY, update_id INTEGER UNIQUE, actor_id TEXT NOT NULL, chat_id TEXT NOT NULL, topic_id TEXT, scope TEXT NOT NULL, target TEXT NOT NULL, operation TEXT NOT NULL, arguments_json TEXT NOT NULL, status TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS command_targets(command_id TEXT NOT NULL REFERENCES commands(command_id), device_id TEXT NOT NULL, ordinal INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', result_json TEXT, PRIMARY KEY(command_id, device_id));
                CREATE TABLE IF NOT EXISTS command_previews(command_id TEXT PRIMARY KEY REFERENCES commands(command_id), preview_json TEXT NOT NULL, preview_sha256 TEXT NOT NULL, created_at INTEGER NOT NULL);
                CREATE TRIGGER IF NOT EXISTS command_previews_no_update BEFORE UPDATE ON command_previews BEGIN SELECT RAISE(ABORT, 'command previews are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS command_previews_no_delete BEFORE DELETE ON command_previews BEGIN SELECT RAISE(ABORT, 'command previews are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS command_targets_identity_no_update BEFORE UPDATE OF command_id, device_id, ordinal ON command_targets BEGIN SELECT RAISE(ABORT, 'command target identity is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS commands_payload_no_update BEFORE UPDATE OF scope, target, operation, arguments_json, created_at, expires_at ON commands BEGIN SELECT RAISE(ABORT, 'command payload is immutable'); END;
                CREATE TABLE IF NOT EXISTS confirmations(confirmation_id TEXT PRIMARY KEY, command_id TEXT NOT NULL REFERENCES commands(command_id), actor_id TEXT NOT NULL, chat_id TEXT NOT NULL, topic_id TEXT, expires_at INTEGER NOT NULL, consumed_at INTEGER);
                CREATE TABLE IF NOT EXISTS deployments(deployment_id TEXT PRIMARY KEY, command_id TEXT NOT NULL, fleet_id TEXT NOT NULL, operation TEXT NOT NULL, release_alias TEXT, status TEXT NOT NULL, created_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS controller_state(state_key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS audit_events(id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, actor_id TEXT, command_id TEXT, payload_json TEXT NOT NULL, created_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS outbound_replies(id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL, topic_id TEXT, text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, telegram_message_id TEXT, created_at INTEGER NOT NULL, sent_at INTEGER);
                CREATE TABLE IF NOT EXISTS ota_abort_requests(fleet_id TEXT NOT NULL, deployment_id TEXT NOT NULL, command_id TEXT NOT NULL REFERENCES commands(command_id), requested_at INTEGER NOT NULL, PRIMARY KEY(fleet_id, deployment_id));
            """)
            self._add_column(db, "commands", "dispatch_policy_json", "TEXT")
            self._add_column(db, "commands", "lease_owner", "TEXT")
            self._add_column(db, "commands", "lease_expires_at", "INTEGER")
            self._add_column(db, "commands", "completion_text", "TEXT")
            self._add_column(db, "commands", "next_dispatch_at", "INTEGER")
            self._add_column(db, "outbound_replies", "dedupe_key", "TEXT")
            self._add_column(db, "outbound_replies", "reply_after_id", "INTEGER")
            db.executescript("""
                CREATE UNIQUE INDEX IF NOT EXISTS outbound_replies_dedupe_key
                ON outbound_replies(dedupe_key) WHERE dedupe_key IS NOT NULL;
                CREATE TRIGGER IF NOT EXISTS commands_dispatch_policy_no_update
                BEFORE UPDATE OF dispatch_policy_json ON commands
                BEGIN SELECT RAISE(ABORT, 'command dispatch policy is immutable'); END;
            """)

    def is_update_processed(self, update_id: int) -> bool:
        with self._connection() as db:
            return (
                db.execute("SELECT 1 FROM processed_updates WHERE update_id=?", (update_id,)).fetchone()
                is not None
            )

    def mark_update_processed(self, update_id: int, now: int | None = None) -> bool:
        with self._connection() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO processed_updates VALUES (?, ?)", (update_id, now or int(time.time()))
            )
            return cursor.rowcount == 1

    def next_update_offset(self) -> int | None:
        with self._connection() as db:
            row = db.execute("SELECT MAX(update_id) AS value FROM processed_updates").fetchone()
            return None if row["value"] is None else int(row["value"]) + 1

    def create_command(
        self,
        *,
        update_id: int,
        actor_id: str,
        chat_id: str,
        topic_id: str | None,
        scope: str,
        target: str,
        operation: str,
        arguments: dict[str, Any],
        device_ids: Sequence[str],
        expires_at: int,
        status: str = "accepted",
        preview: dict[str, Any] | None = None,
        dispatch_policy: dict[str, Any] | None = None,
        now: int | None = None,
    ) -> str:
        command_id = str(uuid.uuid4())
        created_at = now or int(time.time())
        with self._connection() as db:
            db.execute(
                "INSERT INTO commands(command_id, update_id, actor_id, chat_id, topic_id, scope, "
                "target, operation, arguments_json, status, created_at, expires_at, dispatch_policy_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    command_id,
                    update_id,
                    actor_id,
                    chat_id,
                    topic_id,
                    scope,
                    target,
                    operation,
                    json.dumps(arguments, sort_keys=True, separators=(",", ":")),
                    status,
                    created_at,
                    expires_at,
                    None if dispatch_policy is None else self._canonical_json(dispatch_policy),
                ),
            )
            db.executemany(
                "INSERT INTO command_targets(command_id, device_id, ordinal) VALUES (?, ?, ?)",
                ((command_id, device_id, ordinal) for ordinal, device_id in enumerate(device_ids)),
            )
            if preview is not None:
                encoded_preview = self._canonical_json(preview)
                db.execute(
                    "INSERT INTO command_previews(command_id, preview_json, preview_sha256, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        command_id,
                        encoded_preview,
                        hashlib.sha256(encoded_preview.encode()).hexdigest(),
                        created_at,
                    ),
                )
            self._audit(
                db,
                "command_created",
                actor_id,
                command_id,
                {"targets": list(device_ids), "operation": operation},
                created_at,
            )
        return command_id

    def create_confirmation(
        self,
        command_id: str,
        actor_id: str,
        chat_id: str,
        topic_id: str | None,
        expires_at: int,
        now: int | None = None,
    ) -> str:
        # ``token_urlsafe`` may begin with ``-`` or ``_``; prefix it so every
        # generated value is accepted by the controller's strict command-ID grammar.
        confirmation_id = f"c_{secrets.token_urlsafe(18)}"
        with self._connection() as db:
            db.execute(
                "INSERT INTO confirmations VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (confirmation_id, command_id, actor_id, chat_id, topic_id, expires_at),
            )
            self._audit(
                db,
                "confirmation_created",
                actor_id,
                command_id,
                {"confirmation_id_hash": hashlib.sha256(confirmation_id.encode()).hexdigest()},
                now or int(time.time()),
            )
        return confirmation_id

    def consume_confirmation(
        self, confirmation_id: str, actor_id: str, chat_id: str, topic_id: str | None, now: int | None = None
    ) -> str:
        current = now or int(time.time())
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM confirmations WHERE confirmation_id=?", (confirmation_id,)
            ).fetchone()
            if (
                row is None
                or row["actor_id"] != actor_id
                or row["chat_id"] != chat_id
                or row["topic_id"] != topic_id
            ):
                raise ConfirmationError("confirmation does not match this actor, chat, and topic")
            if row["consumed_at"] is not None:
                raise ConfirmationError("confirmation was already used")
            if int(row["expires_at"]) < current:
                raise ConfirmationError("confirmation has expired")
            preview = self._validated_preview(db, str(row["command_id"]))
            if preview.get("confirmation_expires_at") != int(row["expires_at"]):
                raise ConfirmationError("confirmation expiry does not match the frozen preview")
            updated = db.execute(
                "UPDATE confirmations SET consumed_at=? WHERE confirmation_id=? AND consumed_at IS NULL",
                (current, confirmation_id),
            )
            if updated.rowcount != 1:
                raise ConfirmationError("confirmation was already used")
            db.execute("UPDATE commands SET status='confirmed' WHERE command_id=?", (row["command_id"],))
            command = db.execute(
                "SELECT target, operation, arguments_json FROM commands WHERE command_id=?",
                (row["command_id"],),
            ).fetchone()
            if command is not None and command["operation"] == "ota_abort":
                arguments = json.loads(str(command["arguments_json"]))
                deployment_id = arguments.get("deployment_id")
                if isinstance(deployment_id, str):
                    db.execute(
                        "INSERT OR IGNORE INTO ota_abort_requests(fleet_id, deployment_id, command_id, requested_at) "
                        "VALUES (?, ?, ?, ?)",
                        (command["target"], deployment_id, row["command_id"], current),
                    )
            self._audit(db, "confirmation_consumed", actor_id, row["command_id"], {}, current)
            return str(row["command_id"])

    def inspect_confirmation(
        self, confirmation_id: str, actor_id: str, chat_id: str, topic_id: str | None, now: int | None = None
    ) -> dict[str, Any]:
        current = now or int(time.time())
        with self._connection() as db:
            row = db.execute(
                "SELECT c.*, x.scope, x.target, x.operation, x.arguments_json, "
                "x.dispatch_policy_json FROM confirmations c "
                "JOIN commands x ON x.command_id=c.command_id WHERE c.confirmation_id=?",
                (confirmation_id,),
            ).fetchone()
            if (
                row is None
                or row["actor_id"] != actor_id
                or row["chat_id"] != chat_id
                or row["topic_id"] != topic_id
            ):
                raise ConfirmationError("confirmation does not match this actor, chat, and topic")
            if row["consumed_at"] is not None:
                raise ConfirmationError("confirmation was already used")
            if int(row["expires_at"]) < current:
                raise ConfirmationError("confirmation has expired")
            result = dict(row)
            result["arguments"] = json.loads(result.pop("arguments_json"))
            raw_policy = result.pop("dispatch_policy_json", None)
            result["dispatch_policy"] = None if raw_policy is None else json.loads(raw_policy)
            return result

    def get_command(self, command_id: str) -> dict[str, Any]:
        with self._connection() as db:
            row = db.execute("SELECT * FROM commands WHERE command_id=?", (command_id,)).fetchone()
            if row is None:
                raise StoreError("command not found")
            result = dict(row)
            result["arguments"] = json.loads(result.pop("arguments_json"))
            raw_policy = result.pop("dispatch_policy_json", None)
            result["dispatch_policy"] = None if raw_policy is None else json.loads(raw_policy)
            result["device_ids"] = [
                r["device_id"]
                for r in db.execute(
                    "SELECT device_id FROM command_targets WHERE command_id=? ORDER BY ordinal", (command_id,)
                )
            ]
            preview_row = db.execute(
                "SELECT preview_json, preview_sha256 FROM command_previews WHERE command_id=?",
                (command_id,),
            ).fetchone()
            if preview_row is not None:
                result["preview"] = self._validated_preview(db, command_id)
                result["preview_sha256"] = str(preview_row["preview_sha256"])
            return result

    def get_preview(self, command_id: str) -> dict[str, Any]:
        with self._connection() as db:
            return self._validated_preview(db, command_id)

    def get_command_targets(self, command_id: str) -> list[dict[str, Any]]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT device_id, ordinal, status, result_json FROM command_targets "
                "WHERE command_id=? ORDER BY ordinal",
                (command_id,),
            )
            result = []
            for row in rows:
                item = dict(row)
                raw = item.pop("result_json")
                item["result"] = None if raw is None else json.loads(raw)
                result.append(item)
            return result

    def pending_command_ids(self, now: int | None = None) -> list[str]:
        current = int(time.time()) if now is None else now
        with self._connection() as db:
            return [
                str(row["command_id"])
                for row in db.execute(
                    "SELECT command_id FROM commands "
                    "WHERE status IN ('accepted', 'confirmed', 'dispatching') AND expires_at>=? "
                    "ORDER BY created_at, command_id",
                    (current,),
                )
            ]

    def claim_next_command(
        self, worker_id: str, lease_s: int, now: int | None = None
    ) -> dict[str, Any] | None:
        """Atomically claim one dispatchable command, including an expired lease."""
        current = int(time.time()) if now is None else now
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT command_id FROM commands "
                "WHERE (status IN ('accepted', 'confirmed', 'dispatching') "
                "OR (status IN ('applied', 'failed', 'expired', 'aborted') "
                "AND completion_text IS NULL)) "
                "AND (next_dispatch_at IS NULL OR next_dispatch_at<=?) "
                "AND (lease_owner IS NULL OR lease_expires_at<=?) "
                "ORDER BY created_at, command_id LIMIT 1",
                (current, current),
            ).fetchone()
            if row is None:
                return None
            command_id = str(row["command_id"])
            updated = db.execute(
                "UPDATE commands SET lease_owner=?, lease_expires_at=? "
                "WHERE command_id=? AND (lease_owner IS NULL OR lease_expires_at<=?)",
                (worker_id, current + lease_s, command_id, current),
            )
            if updated.rowcount != 1:
                return None
        return self.get_command(command_id)

    def renew_command_lease(
        self, command_id: str, worker_id: str, lease_s: int, now: int | None = None
    ) -> bool:
        current = int(time.time()) if now is None else now
        with self._connection() as db:
            cursor = db.execute(
                "UPDATE commands SET lease_expires_at=? WHERE command_id=? AND lease_owner=?",
                (current + lease_s, command_id, worker_id),
            )
            return cursor.rowcount == 1

    def release_command_lease(self, command_id: str, worker_id: str) -> bool:
        with self._connection() as db:
            cursor = db.execute(
                "UPDATE commands SET lease_owner=NULL, lease_expires_at=NULL "
                "WHERE command_id=? AND lease_owner=?",
                (command_id, worker_id),
            )
            return cursor.rowcount == 1

    def defer_command(self, command_id: str, worker_id: str, next_dispatch_at: int) -> bool:
        with self._connection() as db:
            cursor = db.execute(
                "UPDATE commands SET lease_owner=NULL, lease_expires_at=NULL, next_dispatch_at=? "
                "WHERE command_id=? AND lease_owner=?",
                (next_dispatch_at, command_id, worker_id),
            )
            return cursor.rowcount == 1

    def complete_command(
        self,
        command_id: str,
        worker_id: str,
        status: str,
        text: str,
        now: int | None = None,
    ) -> bool:
        """Commit terminal state and its once-only completion reply together."""
        current = int(time.time()) if now is None else now
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT chat_id, topic_id FROM commands WHERE command_id=? AND lease_owner=?",
                (command_id, worker_id),
            ).fetchone()
            if row is None:
                return False
            db.execute(
                "UPDATE commands SET status=?, completion_text=?, lease_owner=NULL, lease_expires_at=NULL "
                "WHERE command_id=? AND lease_owner=?",
                (status, text, command_id, worker_id),
            )
            self._enqueue_reply(
                db,
                str(row["chat_id"]),
                None if row["topic_id"] is None else str(row["topic_id"]),
                text,
                current,
                f"command:{command_id}:completion",
            )
            return True

    def complete_local_command(self, command_id: str, status: str, text: str, now: int | None = None) -> bool:
        """Atomically finish controller-local work and queue its reply."""
        current = int(time.time()) if now is None else now
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT chat_id, topic_id, completion_text FROM commands WHERE command_id=?",
                (command_id,),
            ).fetchone()
            if row is None:
                raise StoreError("command not found")
            if row["completion_text"] is not None:
                return False
            db.execute(
                "UPDATE commands SET status=?, completion_text=? WHERE command_id=?",
                (status, text, command_id),
            )
            return self._enqueue_reply(
                db,
                str(row["chat_id"]),
                None if row["topic_id"] is None else str(row["topic_id"]),
                text,
                current,
                f"command:{command_id}:completion",
            )

    def enqueue_command_progress(
        self, command_id: str, progress_key: str, text: str, now: int | None = None
    ) -> bool:
        current = int(time.time()) if now is None else now
        with self._connection() as db:
            row = db.execute(
                "SELECT chat_id, topic_id FROM commands WHERE command_id=?", (command_id,)
            ).fetchone()
            if row is None:
                raise StoreError("command not found")
            return self._enqueue_reply(
                db,
                str(row["chat_id"]),
                None if row["topic_id"] is None else str(row["topic_id"]),
                text,
                current,
                f"command:{command_id}:progress:{progress_key}",
            )

    def reconcile_completion_replies(self, now: int | None = None) -> int:
        current = int(time.time()) if now is None else now
        created = 0
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT command_id, chat_id, topic_id, completion_text FROM commands "
                "WHERE status IN ('applied', 'failed', 'expired', 'aborted') AND completion_text IS NOT NULL"
            )
            for row in rows:
                created += int(
                    self._enqueue_reply(
                        db,
                        str(row["chat_id"]),
                        None if row["topic_id"] is None else str(row["topic_id"]),
                        str(row["completion_text"]),
                        current,
                        f"command:{row['command_id']}:completion",
                    )
                )
        return created

    def is_ota_abort_requested(self, fleet_id: str, deployment_id: str) -> bool:
        with self._connection() as db:
            return (
                db.execute(
                    "SELECT 1 FROM ota_abort_requests WHERE fleet_id=? AND deployment_id=?",
                    (fleet_id, deployment_id),
                ).fetchone()
                is not None
            )

    def get_command_by_update(self, update_id: int) -> dict[str, Any] | None:
        with self._connection() as db:
            row = db.execute("SELECT command_id FROM commands WHERE update_id=?", (update_id,)).fetchone()
        return None if row is None else self.get_command(str(row["command_id"]))

    def get_confirmation_for_command(self, command_id: str) -> str | None:
        with self._connection() as db:
            row = db.execute(
                "SELECT confirmation_id FROM confirmations WHERE command_id=? AND consumed_at IS NULL ORDER BY expires_at DESC LIMIT 1",
                (command_id,),
            ).fetchone()
            return None if row is None else str(row["confirmation_id"])

    def set_target_result(self, command_id: str, device_id: str, status: str, result: dict[str, Any]) -> None:
        with self._connection() as db:
            db.execute(
                "UPDATE command_targets SET status=?, result_json=? WHERE command_id=? AND device_id=?",
                (status, json.dumps(result, sort_keys=True), command_id, device_id),
            )

    def set_command_status(self, command_id: str, status: str) -> None:
        with self._connection() as db:
            db.execute("UPDATE commands SET status=? WHERE command_id=?", (status, command_id))

    def get_state(self, state_key: str) -> dict[str, Any] | None:
        with self._connection() as db:
            row = db.execute(
                "SELECT value_json FROM controller_state WHERE state_key=?", (state_key,)
            ).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(str(row["value_json"]))
        except json.JSONDecodeError as exc:
            raise StoreError("controller state is corrupt") from exc
        if not isinstance(value, dict):
            raise StoreError("controller state is corrupt")
        return value

    def set_state(self, state_key: str, value: dict[str, Any], now: int | None = None) -> None:
        try:
            encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise StoreError("controller state must be JSON serializable") from exc
        current = int(time.time()) if now is None else now
        with self._connection() as db:
            db.execute(
                "INSERT INTO controller_state(state_key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(state_key) DO UPDATE SET value_json=excluded.value_json, "
                "updated_at=excluded.updated_at",
                (state_key, encoded, current),
            )

    def set_state_and_command_status(
        self,
        state_key: str,
        value: dict[str, Any],
        command_id: str,
        status: str,
        now: int | None = None,
    ) -> None:
        try:
            encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise StoreError("controller state must be JSON serializable") from exc
        current = int(time.time()) if now is None else now
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO controller_state(state_key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(state_key) DO UPDATE SET value_json=excluded.value_json, "
                "updated_at=excluded.updated_at",
                (state_key, encoded, current),
            )
            db.execute("UPDATE commands SET status=? WHERE command_id=?", (status, command_id))

    def create_deployment(
        self,
        command_id: str,
        fleet_id: str,
        operation: str,
        release_alias: str | None = None,
        now: int | None = None,
    ) -> str:
        deployment_id = str(uuid.uuid4())
        with self._connection() as db:
            db.execute(
                "INSERT INTO deployments VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                (deployment_id, command_id, fleet_id, operation, release_alias, now or int(time.time())),
            )
        return deployment_id

    def enqueue_reply(self, chat_id: str, topic_id: str | None, text: str, now: int | None = None) -> int:
        with self._connection() as db:
            cursor = db.execute(
                "INSERT INTO outbound_replies(chat_id, topic_id, text, created_at) VALUES (?, ?, ?, ?)",
                (chat_id, topic_id, text[:4096], now or int(time.time())),
            )
            if cursor.lastrowid is None:
                raise StoreError("outbound reply was not persisted")
            return cursor.lastrowid

    def enqueue_reply_group(
        self,
        chat_id: str,
        topic_id: str | None,
        texts: Sequence[str],
        now: int | None = None,
    ) -> tuple[int, ...]:
        """Persist a reply sequence whose next page unlocks only after its predecessor is sent."""
        if not texts:
            return ()
        current = now or int(time.time())
        reply_ids: list[int] = []
        predecessor: int | None = None
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for text in texts:
                cursor = db.execute(
                    "INSERT INTO outbound_replies(chat_id, topic_id, text, created_at, reply_after_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (chat_id, topic_id, text[:4096], current, predecessor),
                )
                if cursor.lastrowid is None:
                    raise StoreError("outbound reply group was not persisted")
                predecessor = int(cursor.lastrowid)
                reply_ids.append(predecessor)
        return tuple(reply_ids)

    @staticmethod
    def _enqueue_reply(
        db: sqlite3.Connection,
        chat_id: str,
        topic_id: str | None,
        text: str,
        now: int,
        dedupe_key: str,
    ) -> bool:
        cursor = db.execute(
            "INSERT OR IGNORE INTO outbound_replies(chat_id, topic_id, text, created_at, dedupe_key) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, topic_id, text[:4096], now, dedupe_key),
        )
        return cursor.rowcount == 1

    def pending_replies(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connection() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT reply.* FROM outbound_replies reply "
                    "LEFT JOIN outbound_replies predecessor ON predecessor.id=reply.reply_after_id "
                    "WHERE reply.status='pending' "
                    "AND (reply.reply_after_id IS NULL OR predecessor.status='sent') "
                    "ORDER BY reply.id LIMIT ?",
                    (limit,),
                )
            ]

    def mark_reply_sent(self, reply_id: int, message_id: str, now: int | None = None) -> None:
        with self._connection() as db:
            db.execute(
                "UPDATE outbound_replies SET status='sent', attempts=attempts+1, telegram_message_id=?, sent_at=? WHERE id=?",
                (message_id, now or int(time.time()), reply_id),
            )

    def mark_reply_attempt(self, reply_id: int) -> None:
        with self._connection() as db:
            db.execute("UPDATE outbound_replies SET attempts=attempts+1 WHERE id=?", (reply_id,))

    @staticmethod
    def _audit(
        db: sqlite3.Connection,
        event_type: str,
        actor_id: str | None,
        command_id: str | None,
        payload: dict[str, Any],
        now: int,
    ) -> None:
        db.execute(
            "INSERT INTO audit_events(event_type, actor_id, command_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                event_type,
                actor_id,
                command_id,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                now,
            ),
        )

    @staticmethod
    def _canonical_json(value: dict[str, Any]) -> str:
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        except (TypeError, ValueError) as exc:
            raise StoreError("preview must be JSON serializable") from exc

    @staticmethod
    def _add_column(db: sqlite3.Connection, table: str, name: str, sql_type: str) -> None:
        columns = {str(row["name"]) for row in db.execute(f"PRAGMA table_info({table})")}
        if name not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")

    def _validated_preview(self, db: sqlite3.Connection, command_id: str) -> dict[str, Any]:
        row = db.execute(
            "SELECT preview_json, preview_sha256 FROM command_previews WHERE command_id=?",
            (command_id,),
        ).fetchone()
        if row is None:
            raise ConfirmationError("confirmation preview is missing")
        encoded = str(row["preview_json"])
        actual_hash = hashlib.sha256(encoded.encode()).hexdigest()
        if not secrets.compare_digest(actual_hash, str(row["preview_sha256"])):
            raise ConfirmationError("confirmation preview integrity check failed")
        try:
            preview = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise ConfirmationError("confirmation preview is corrupt") from exc
        if not isinstance(preview, dict):
            raise ConfirmationError("confirmation preview is corrupt")
        target_rows = db.execute(
            "SELECT device_id FROM command_targets WHERE command_id=? ORDER BY ordinal", (command_id,)
        )
        persisted_targets = [str(target["device_id"]) for target in target_rows]
        if preview.get("eligible_device_ids") != persisted_targets:
            raise ConfirmationError("confirmation preview targets do not match the frozen command")
        command = db.execute(
            "SELECT scope, target, operation, arguments_json, expires_at, dispatch_policy_json "
            "FROM commands WHERE command_id=?",
            (command_id,),
        ).fetchone()
        if command is None:
            raise ConfirmationError("confirmation command is missing")
        try:
            arguments = json.loads(str(command["arguments_json"]))
        except json.JSONDecodeError as exc:
            raise ConfirmationError("confirmation command is corrupt") from exc
        bound_fields = {
            "scope": str(command["scope"]),
            "target": str(command["target"]),
            "operation": str(command["operation"]),
            "arguments": arguments,
            "command_expires_at": int(command["expires_at"]),
        }
        if any(preview.get(field) != expected for field, expected in bound_fields.items()):
            raise ConfirmationError("confirmation preview does not match the frozen command")
        raw_policy = command["dispatch_policy_json"] if "dispatch_policy_json" in command.keys() else None
        if raw_policy is not None:
            try:
                policy = json.loads(str(raw_policy))
            except json.JSONDecodeError as exc:
                raise ConfirmationError("frozen dispatch policy is corrupt") from exc
            if preview.get("dispatch_policy") != policy:
                raise ConfirmationError("preview dispatch policy does not match the frozen command")
        return preview
