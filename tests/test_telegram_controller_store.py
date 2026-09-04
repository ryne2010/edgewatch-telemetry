from pathlib import Path
import sqlite3

import pytest

from telegram_controller.parser import parse_command
from telegram_controller.store import ConfirmationError, ControllerStore


def _command(store: ControllerStore, now: int = 100) -> str:
    return store.create_command(
        update_id=8,
        actor_id="1",
        chat_id="-2",
        topic_id="3",
        scope="fleet",
        target="west",
        operation="reboot",
        arguments={},
        device_ids=("a", "b"),
        expires_at=500,
        preview={
            "scope": "fleet",
            "target": "west",
            "operation": "reboot",
            "arguments": {},
            "eligible_device_ids": ["a", "b"],
            "excluded_devices": [],
            "dispatch_policy": {"max_workers": 2},
            "command_expires_at": 500,
            "confirmation_expires_at": 220,
        },
        now=now,
    )


def test_update_dedupe_and_offset_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    store = ControllerStore(path)
    assert store.mark_update_processed(40, 100)
    assert not store.mark_update_processed(40, 101)
    assert ControllerStore(path).next_update_offset() == 41
    assert path.stat().st_mode & 0o777 == 0o600


def test_commands_and_frozen_targets_survive_inventory_changes(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    command_id = _command(ControllerStore(path))
    assert ControllerStore(path).get_command(command_id)["device_ids"] == ["a", "b"]


def test_preview_and_command_target_identity_are_database_immutable(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    command_id = _command(ControllerStore(path))

    with sqlite3.connect(path) as db, pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("UPDATE command_previews SET preview_json='{}' WHERE command_id=?", (command_id,))
    with sqlite3.connect(path) as db, pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute(
            "UPDATE command_targets SET device_id='drifted' WHERE command_id=? AND device_id='a'",
            (command_id,),
        )


def test_confirmation_is_one_use_actor_chat_topic_bound_and_expires(tmp_path: Path) -> None:
    store = ControllerStore(tmp_path / "state.sqlite")
    command_id = _command(store)
    token = store.create_confirmation(command_id, "1", "-2", "3", 220, 100)
    for actor, chat, topic in [("9", "-2", "3"), ("1", "-9", "3"), ("1", "-2", "9")]:
        with pytest.raises(ConfirmationError):
            store.consume_confirmation(token, actor, chat, topic, 110)
    assert store.consume_confirmation(token, "1", "-2", "3", 110) == command_id
    with pytest.raises(ConfirmationError, match="already used"):
        store.consume_confirmation(token, "1", "-2", "3", 111)
    second = store.create_confirmation(command_id, "1", "-2", "3", 120, 100)
    with pytest.raises(ConfirmationError, match="expired"):
        store.consume_confirmation(second, "1", "-2", "3", 121)


def test_generated_confirmation_is_always_accepted_by_command_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("telegram_controller.store.secrets.token_urlsafe", lambda _size: "_leading")
    store = ControllerStore(tmp_path / "state.sqlite")
    token = store.create_confirmation(_command(store), "1", "-2", "3", 220, 100)

    command = parse_command(f"/fleet west confirm {token}")

    assert token == "c__leading"
    assert command.confirmation_id == token


def test_controller_state_and_pending_dispatch_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    store = ControllerStore(path)
    command_id = _command(store)
    store.set_command_status(command_id, "dispatching")
    store.set_state("ota:west", {"status": "staging", "targets": ["a", "b"]}, 101)

    restarted = ControllerStore(path)

    assert restarted.get_state("ota:west") == {"status": "staging", "targets": ["a", "b"]}
    assert restarted.pending_command_ids(200) == [command_id]
    assert restarted.pending_command_ids(501) == []


def test_state_and_command_status_transition_is_atomic(tmp_path: Path) -> None:
    store = ControllerStore(tmp_path / "state.sqlite")
    command_id = _command(store)

    store.set_state_and_command_status(
        "ota:west", {"status": "canary", "deployment_id": "dep-1"}, command_id, "dispatching", 110
    )

    assert store.get_state("ota:west") == {"status": "canary", "deployment_id": "dep-1"}
    assert store.get_command(command_id)["status"] == "dispatching"


def test_dispatch_claim_is_exclusive_and_expired_lease_is_reclaimed(tmp_path: Path) -> None:
    store = ControllerStore(tmp_path / "state.sqlite")
    command_id = _command(store)
    store.set_command_status(command_id, "accepted")

    first = store.claim_next_command("worker-a", 10, 100)
    assert first is not None and first["command_id"] == command_id
    assert store.claim_next_command("worker-b", 10, 109) is None

    reclaimed = ControllerStore(store.path).claim_next_command("worker-b", 10, 110)
    assert reclaimed is not None and reclaimed["command_id"] == command_id
    assert not store.complete_command(command_id, "worker-a", "applied", "stale completion", 111)
    assert store.complete_command(command_id, "worker-b", "applied", "complete", 111)


def test_completion_reply_is_generated_once_across_reconciliation(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    store = ControllerStore(path)
    command_id = _command(store)
    store.set_command_status(command_id, "accepted")
    assert store.claim_next_command("worker", 10, 100) is not None
    assert store.complete_command(command_id, "worker", "applied", "complete", 101)

    restarted = ControllerStore(path)
    assert restarted.reconcile_completion_replies(102) == 0
    assert restarted.reconcile_completion_replies(103) == 0
    assert [reply["text"] for reply in restarted.pending_replies()] == ["complete"]


def test_reply_group_pages_unlock_strictly_in_order_across_retry_and_restart(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    store = ControllerStore(path)
    reply_ids = store.enqueue_reply_group("-2", "3", ("page one", "page two", "confirm"), 100)

    assert [reply["text"] for reply in store.pending_replies()] == ["page one"]
    store.mark_reply_attempt(reply_ids[0])
    assert [reply["text"] for reply in ControllerStore(path).pending_replies()] == ["page one"]

    ControllerStore(path).mark_reply_sent(reply_ids[0], "telegram-1", 101)
    assert [reply["text"] for reply in ControllerStore(path).pending_replies()] == ["page two"]
    ControllerStore(path).mark_reply_sent(reply_ids[1], "telegram-2", 102)
    assert [reply["text"] for reply in ControllerStore(path).pending_replies()] == ["confirm"]
