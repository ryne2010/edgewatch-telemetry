import json
import base64
import threading
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from math import ceil
from pathlib import Path

import yaml
import pytest

from telegram_controller.config import ControllerConfig, OTAConfig, SSHConfig, TelegramConfig
from telegram_controller.models import Device, DispatchResult, Fleet, Principal, Role
from telegram_controller.service import ControllerService
from telegram_controller.store import ControllerStore
from telegram_controller.telegram import TelegramClient, TelegramError
from agent.local_control import parse_envelope


class Recorder:
    def __init__(self):
        self.envelopes = []

    def dispatch(self, envelope):
        self.envelopes.append(envelope)
        return DispatchResult(True, "ok")


def _config(tmp_path: Path) -> ControllerConfig:
    dummy = tmp_path / "dummy"
    dummy.write_text("x")
    return ControllerConfig(
        TelegramConfig(dummy),
        SSHConfig(dummy, dummy),
        tmp_path / "db.sqlite",
        {"10": Principal("10", Role.OPERATOR, frozenset({"west"})), "99": Principal("99", Role.ADMIN)},
        {"a": Device("a", "west", "a"), "b": Device("b", "west", "b")},
        {"west": Fleet("west", ("a", "b"), "7")},
        frozenset({"-1"}),
        confirmation_ttl_s=20,
    )


def _update(update_id: int, user: int, text: str, topic: int = 7):
    return {
        "update_id": update_id,
        "message": {"chat": {"id": -1}, "from": {"id": user}, "message_thread_id": topic, "text": text},
    }


def _ota_config(tmp_path: Path) -> ControllerConfig:
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "releases": {
                    "release-1": {
                        "version": "1.0.0",
                        "git_tag": "v1.0.0",
                        "commit_sha": "a" * 40,
                        "update_type": "application_bundle",
                        "artifact_uri": "https://releases.example/app.tar.gz",
                        "artifact_size": 100,
                        "artifact_sha256": "b" * 64,
                        "artifact_signature": base64.b64encode(b"signed").decode(),
                        "artifact_signature_scheme": "openssl_rsa_sha256",
                        "signature_key_id": "prod",
                        "runtime_dependency_sha256": "c" * 64,
                        "manifest_signature": base64.b64encode(b"manifest-signed").decode(),
                        "compatibility": {
                            "schema_version": 1,
                            "hardware_models": ["raspberry-pi-4"],
                            "release_channel": "stable",
                            "minimum_python_version": "3.11.0",
                            "minimum_runtime_schema": 1,
                            "minimum_ota_schema": 1,
                            "requires_stable_power": False,
                            "requires_apply_enabled": False,
                            "minimum_free_bytes": 1,
                        },
                    }
                },
                "aliases": {"stable": "release-1"},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    config = _config(tmp_path)
    return replace(
        config,
        ota=OTAConfig(catalog, rollout_percentages=(50, 100)),
        devices={**config.devices, "c": Device("c", "west", "c")},
        fleets={"west": Fleet("west", ("a", "b", "c"), "7", ("a",))},
    )


def _last_confirmation(store: ControllerStore) -> str:
    return str(store.pending_replies()[-1]["text"]).rsplit(" ", 1)[1]


def test_rbac_and_read_only_dispatch_are_durably_queued(tmp_path: Path) -> None:
    config = _config(tmp_path)
    recorder = Recorder()
    service = ControllerService(config, ControllerStore(config.database_path), recorder, clock=lambda: 100)
    service.handle_update(_update(1, 10, "/device a status"))
    assert recorder.envelopes == []
    service.dispatch_once("worker-1")
    assert [item.device_id for item in recorder.envelopes] == ["a"]
    assert set(vars(recorder.envelopes[0])) == {
        "version",
        "command_id",
        "device_id",
        "issued_at",
        "expires_at",
        "type",
        "args",
    }
    assert recorder.envelopes[0].issued_at == "1970-01-01T00:01:40Z"
    assert recorder.envelopes[0].expires_at == "1970-01-01T00:10:11Z"
    parsed = parse_envelope(
        json.dumps(asdict(recorder.envelopes[0])).encode(),
        expected_device_id="a",
        now=datetime.fromtimestamp(100, tz=UTC),
    )
    assert parsed.command_type == "status"
    service.handle_update(_update(2, 10, "/fleet west reboot"))
    assert len(recorder.envelopes) == 1
    assert "not authorized" in service.store.pending_replies()[-1]["text"]


def test_legacy_command_without_frozen_dispatch_policy_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    recorder = Recorder()
    store = ControllerStore(config.database_path)
    command_id = store.create_command(
        update_id=1,
        actor_id="10",
        chat_id="-1",
        topic_id="7",
        scope="device",
        target="a",
        operation="status",
        arguments={},
        device_ids=("a",),
        expires_at=1_000,
        now=100,
    )
    service = ControllerService(config, store, recorder, clock=lambda: 100)

    assert service.dispatch_once("legacy-worker")

    command = store.get_command(command_id)
    assert command["status"] == "failed"
    assert recorder.envelopes == []
    replies = store.pending_replies(limit=100)
    assert any("frozen dispatch policy is missing" in str(reply["text"]) for reply in replies)


def test_human_replies_are_decorated_but_dispatch_envelopes_remain_plain(tmp_path: Path) -> None:
    config = _config(tmp_path)
    recorder = Recorder()
    store = ControllerStore(config.database_path)
    service = ControllerService(config, store, recorder, clock=lambda: 100)

    service.handle_update(_update(1, 10, "/device a power"))
    assert str(store.pending_replies()[-1]["text"]).startswith("⏳ 🔋 Command accepted")
    service.dispatch_once("worker-1")
    assert any(str(reply["text"]).startswith("✅ 🔋 power:") for reply in store.pending_replies())
    encoded = json.dumps(asdict(recorder.envelopes[0]), ensure_ascii=False)
    assert all(icon not in encoded for icon in ("⏳", "✅", "🔋"))

    service.handle_update(_update(2, 10, "/device missing power"))
    assert str(store.pending_replies()[-1]["text"]).startswith("❌ Rejected:")

    service.handle_update(_update(3, 99, "/fleet west reboot"))
    assert str(store.pending_replies()[-1]["text"]).startswith("⏳ Preview reboot:")


def test_single_device_read_only_completions_render_only_allowlisted_details(
    tmp_path: Path,
) -> None:
    results = {
        "status": {
            "device_id": "a",
            "ready": True,
            "transport": "telegram",
            "version": "1.2.3",
            "operation_mode": "active",
            "runtime_power_mode": "eco",
            "alerts_muted_until": None,
            "pending_requests": 2,
            "bot_token": "SECRET-STATUS",
        },
        "health": {"ready": False, "database_url": "SECRET-HEALTH"},
        "network": {
            "interfaces": [
                {"name": f"eth{index}", "state": "up", "mac": "SECRET-MAC"} for index in range(12)
            ],
            "ssid": "SECRET-NETWORK",
        },
        "power": {
            "runtime_power_mode": "continuous",
            "source": "mains",
            "input_out_of_range": False,
            "unsustainable": False,
            "saver_active": True,
            "throttled": "0x0",
            "credential": "SECRET-POWER",
        },
        "queue": {"queued_points": 7, "database_bytes": 4096, "path": "SECRET-QUEUE"},
        "version": {"version": "v" * 300, "environment": "SECRET-VERSION"},
        "ota_status": {
            "status": "ok",
            "ota": {
                "active": {
                    "manifest": {
                        "version": "2.0.0",
                        "git_tag": "v2.0.0",
                        "manifest_signature": "SECRET-SIGNATURE",
                    },
                    "artifact_path": "SECRET-PATH",
                },
                "staged": {"manifest": {"version": "2.1.0", "git_tag": "v2.1.0"}},
                "aborted": False,
            },
            "command_id": "SECRET-ENVELOPE",
        },
    }

    class ResultDispatcher:
        def dispatch(self, envelope):
            return DispatchResult(
                True,
                "ok",
                details={"status": "applied", "result": results[envelope.type]},
            )

    config = _config(tmp_path)
    store = ControllerStore(config.database_path)
    service = ControllerService(config, store, ResultDispatcher(), clock=lambda: 100)
    commands = {
        "status": "status",
        "health": "health",
        "network": "network",
        "power": "power",
        "queue": "queue",
        "version": "version",
        "ota_status": "ota status",
    }
    expected = {
        "status": "ready: yes; transport: telegram; version: 1.2.3; operation: active; power: eco",
        "health": "ready: no",
        "network": "interfaces: eth0=up, eth1=up",
        "power": "mode: continuous; source: mains; input out of range: no",
        "queue": "queued points: 7; database bytes: 4096",
        "version": "version: " + "v" * 95 + "…",
        "ota_status": (
            "status: ok; active version: 2.0.0; active tag: v2.0.0; "
            "staged version: 2.1.0; staged tag: v2.1.0; aborted: no"
        ),
    }

    for update_id, (operation, command_text) in enumerate(commands.items(), start=1):
        service.handle_update(_update(update_id, 10, f"/device a {command_text}"))
        assert service.dispatch_once(f"worker-{update_id}")
        completion = str(store.pending_replies(limit=100)[-1]["text"])
        assert expected[operation] in completion
        assert completion.splitlines()[-1] == (
            f"{operation}: 1/1 target(s) applied; 0 accepted/pending; 0 failed."
        )
        assert len(completion) < 2_000
        assert "SECRET" not in completion
        if operation == "network":
            assert "+4 more" in completion


def test_fleet_and_mutating_completions_retain_aggregate_only(tmp_path: Path) -> None:
    class VerboseDispatcher:
        def dispatch(self, envelope):
            return DispatchResult(
                True,
                "ok",
                details={
                    "status": "applied",
                    "result": {"ready": True, "operation_mode": "active", "secret": "SECRET"},
                },
            )

    config = _config(tmp_path)
    store = ControllerStore(config.database_path)
    service = ControllerService(config, store, VerboseDispatcher(), clock=lambda: 100)

    service.handle_update(_update(1, 10, "/fleet west health"))
    assert service.dispatch_once("fleet-worker")
    fleet_completion = str(store.pending_replies(limit=100)[-1]["text"])
    assert fleet_completion == ("✅ health: 2/2 target(s) applied; 0 accepted/pending; 0 failed.")

    service.handle_update(_update(2, 10, "/device a mode active"))
    assert service.dispatch_once("mutation-worker")
    mutation_completion = str(store.pending_replies(limit=100)[-1]["text"])
    assert mutation_completion == (
        "✅ set_operation_mode: 1/1 target(s) applied; 0 accepted/pending; 0 failed."
    )
    assert "SECRET" not in fleet_completion + mutation_completion


def test_fleet_mutation_previews_then_confirms_frozen_targets_once(tmp_path: Path) -> None:
    config = _config(tmp_path)
    recorder = Recorder()
    store = ControllerStore(config.database_path)
    service = ControllerService(config, store, recorder, clock=lambda: 100)
    service.handle_update(_update(1, 99, "/fleet west reboot"))
    preview = store.pending_replies()[0]["text"]
    frozen = store.get_command_by_update(1)
    assert frozen is not None
    assert frozen["preview"]["eligible_device_ids"] == ["a", "b"]
    assert len(frozen["preview_sha256"]) == 64
    assert frozen["preview"]["dispatch_policy"]["max_workers"] == 2
    assert "Full SHA-256:" in preview
    assert "TARGET a" in preview and "TARGET b" in preview
    token = preview.rsplit(" ", 1)[1]
    service.config = replace(config, fleets={"west": Fleet("west", ("a",), "7")})
    service.handle_update(_update(2, 99, f"/fleet west confirm {token}"))
    service.resume_pending()
    assert [item.device_id for item in recorder.envelopes] == ["a", "b"]
    service.handle_update(_update(3, 99, f"/fleet west confirm {token}"))
    assert len(recorder.envelopes) == 2
    assert "already used" in store.pending_replies()[-1]["text"]


def test_preview_persists_disabled_and_capability_exclusions_across_restart(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config = replace(
        config,
        devices={
            "a": Device("a", "west", "a", capabilities=frozenset({"reboot"})),
            "b": Device("b", "west", "b", enabled=False),
            "c": Device("c", "west", "c", capabilities=frozenset({"status"})),
        },
        fleets={"west": Fleet("west", ("a", "b", "c"), "7")},
    )
    store = ControllerStore(config.database_path)

    ControllerService(config, store, Recorder(), clock=lambda: 100).handle_update(
        _update(1, 99, "/fleet west reboot")
    )

    restarted = ControllerStore(config.database_path)
    command = restarted.get_command_by_update(1)
    assert command is not None
    assert command["preview"]["eligible_device_ids"] == ["a"]
    assert command["preview"]["excluded_devices"] == [
        {"device_id": "b", "reason": "disabled"},
        {"device_id": "c", "reason": "missing capability: reboot"},
    ]
    rendered = "\n".join(str(reply["text"]) for reply in restarted.pending_replies())
    assert "EXCLUDED b: disabled" in rendered
    assert "EXCLUDED c: missing capability: reboot" in rendered


def test_large_fleet_preview_is_complete_and_each_telegram_page_is_bounded(tmp_path: Path) -> None:
    config = _config(tmp_path)
    device_ids = tuple(f"device-{index:04d}" for index in range(800))
    devices = {device_id: Device(device_id, "west", device_id) for device_id in device_ids}
    config = replace(config, devices=devices, fleets={"west": Fleet("west", device_ids, "7")})
    store = ControllerStore(config.database_path)

    ControllerService(config, store, Recorder(), clock=lambda: 100).handle_update(
        _update(1, 99, "/fleet west reboot")
    )

    replies = []
    while pending := store.pending_replies(limit=100):
        assert len(pending) == 1
        reply = pending[0]
        replies.append(reply)
        store.mark_reply_sent(int(reply["id"]), f"message-{reply['id']}", 100)
    assert len(replies) > 2
    assert all(len(str(reply["text"])) <= 4096 for reply in replies)
    rendered = "\n".join(str(reply["text"]) for reply in replies)
    assert all(device_id in rendered for device_id in device_ids)
    command = store.get_command_by_update(1)
    assert command is not None
    assert command["preview"]["eligible_device_ids"] == list(device_ids)
    assert command["preview_sha256"] in rendered


def test_ota_stage_freezes_complete_manifest_across_restart_and_catalog_alias_mutation(
    tmp_path: Path,
) -> None:
    config = _ota_config(tmp_path)
    assert config.ota is not None
    store = ControllerStore(config.database_path)
    first = ControllerService(config, store, Recorder(), clock=lambda: 100)
    first.handle_update(_update(1, 99, "/ota west stage stable"))

    command = store.get_command_by_update(1)
    assert command is not None
    reviewed_arguments = command["arguments"]
    reviewed_manifest = reviewed_arguments["manifest"]
    preview_text = str(store.pending_replies()[0]["text"])
    assert reviewed_arguments["manifest_identity"] in preview_text
    assert reviewed_manifest["git_tag"] in preview_text
    assert reviewed_manifest["commit_sha"] in preview_text
    assert reviewed_manifest["artifact_sha256"] in preview_text
    assert reviewed_manifest["runtime_dependency_sha256"] in preview_text

    catalog_payload = yaml.safe_load(config.ota.catalog_file.read_text(encoding="utf-8"))
    replacement = dict(catalog_payload["releases"]["release-1"])
    replacement.update(
        {
            "version": "2.0.0",
            "git_tag": "v2.0.0",
            "commit_sha": "d" * 40,
            "artifact_sha256": "e" * 64,
        }
    )
    catalog_payload["releases"]["release-2"] = replacement
    catalog_payload["aliases"]["stable"] = "release-2"
    config.ota.catalog_file.write_text(yaml.safe_dump(catalog_payload), encoding="utf-8")

    token = _last_confirmation(store)
    recorder = Recorder()
    restarted = ControllerService(config, ControllerStore(config.database_path), recorder, clock=lambda: 100)
    restarted.handle_update(_update(2, 99, f"/ota west confirm {token}"))
    restarted.resume_pending()

    assert recorder.envelopes
    assert all(envelope.args["manifest"] == reviewed_manifest for envelope in recorder.envelopes)
    assert all(envelope.args["manifest"]["commit_sha"] == "a" * 40 for envelope in recorder.envelopes)
    restored = ControllerService(config, ControllerStore(config.database_path), recorder, clock=lambda: 100)
    assert restored._ota_orchestrator("west").snapshot()["manifest"] == reviewed_manifest


def test_confirmed_abort_is_idempotent_after_abort_request_already_aborted_deployment(
    tmp_path: Path,
) -> None:
    config = _ota_config(tmp_path)
    store = ControllerStore(config.database_path)
    recorder = Recorder()
    service = ControllerService(config, store, recorder, clock=lambda: 100)
    service.handle_update(_update(1, 99, "/ota west stage stable"))
    service.handle_update(_update(2, 99, f"/ota west confirm {_last_confirmation(store)}"))
    service.resume_pending()
    snapshot = store.get_state("ota:west")
    assert snapshot is not None
    deployment_id = str(snapshot["deployment_id"])

    service.handle_update(_update(3, 99, f"/ota west abort {deployment_id}"))
    abort_id = store.get_command_by_update(3)
    assert abort_id is not None
    service.handle_update(_update(4, 99, f"/ota west confirm {_last_confirmation(store)}"))
    envelopes_before_abort_dispatch = len(recorder.envelopes)
    orchestrator = service._ota_orchestrator("west")
    orchestrator.abort(deployment_id)
    service._save_ota_orchestrator("west", orchestrator)

    service.resume_pending()

    assert store.get_command(str(abort_id["command_id"]))["status"] == "applied"
    assert store.get_state("ota:west")["status"] == "aborted"  # type: ignore[index]
    assert len(recorder.envelopes) == envelopes_before_abort_dispatch


def test_slow_unreachable_fleet_dispatch_is_concurrent_and_retains_safe_expiry(tmp_path: Path) -> None:
    class SlowFailure:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []
            self.lock = threading.Lock()

        def dispatch(self, envelope):
            with self.lock:
                self.calls.append((envelope.device_id, threading.current_thread().name))
            time.sleep(0.02)
            return DispatchResult(False, "unreachable", retryable=True)

    config = _config(tmp_path)
    device_ids = tuple(f"d{index}" for index in range(8))
    config = replace(
        config,
        devices={device_id: Device(device_id, "west", device_id) for device_id in device_ids},
        fleets={"west": Fleet("west", device_ids, "7")},
        fleet_dispatch_concurrency=4,
    )
    dispatcher = SlowFailure()
    store = ControllerStore(config.database_path)
    now = [100]
    service = ControllerService(
        config, store, dispatcher, clock=lambda: now[0], sleeper=lambda _: None, dispatch_attempts=3
    )
    service.handle_update(_update(1, 99, "/fleet west reboot"))
    command = store.get_command_by_update(1)
    assert command is not None
    assert command["expires_at"] > 100 + config.confirmation_ttl_s + config.command_ttl_s
    token = store.pending_replies()[-1]["text"].rsplit(" ", 1)[1]

    service.handle_update(_update(2, 99, f"/fleet west confirm {token}"))
    service.resume_pending()

    assert len(dispatcher.calls) == len(device_ids) * 3
    assert len({thread_name for _, thread_name in dispatcher.calls}) >= 4
    assert store.get_command(command["command_id"])["status"] == "failed"


def test_confirmation_wrong_topic_user_and_expiry_do_not_dispatch(tmp_path: Path) -> None:
    config = _config(tmp_path)
    recorder = Recorder()
    now = [100]
    store = ControllerStore(config.database_path)
    service = ControllerService(config, store, recorder, clock=lambda: now[0])
    service.handle_update(_update(1, 99, "/fleet west reboot"))
    token = store.pending_replies()[0]["text"].rsplit(" ", 1)[1]
    service.handle_update(_update(2, 10, f"/fleet west confirm {token}"))
    service.handle_update(_update(3, 99, f"/fleet west confirm {token}", topic=8))
    now[0] = 121
    service.handle_update(_update(4, 99, f"/fleet west confirm {token}"))
    assert recorder.envelopes == []


def test_redelivered_unacknowledged_update_reuses_durable_command(tmp_path: Path) -> None:
    config = _config(tmp_path)
    recorder = Recorder()
    store = ControllerStore(config.database_path)
    service = ControllerService(config, store, recorder, clock=lambda: 100)
    command_id = store.create_command(
        update_id=5,
        actor_id="10",
        chat_id="-1",
        topic_id="7",
        scope="device",
        target="a",
        operation="status",
        arguments={},
        device_ids=("a",),
        expires_at=400,
        dispatch_policy=service._dispatch_policy(("a",)),
        now=100,
    )
    assert service.handle_update(_update(5, 10, "/device a status"))
    service.dispatch_once("worker-1")
    assert recorder.envelopes[0].command_id == command_id
    assert store.is_update_processed(5)


def test_device_accepted_result_remains_durable_and_resumable_until_applied(tmp_path: Path) -> None:
    class AcceptedThenApplied:
        def __init__(self) -> None:
            self.calls = 0

        def dispatch(self, envelope):
            del envelope
            self.calls += 1
            if self.calls <= 3:
                return DispatchResult(
                    False,
                    "accepted",
                    retryable=True,
                    details={"status": "accepted", "result": {"requested": "sample_now"}},
                )
            return DispatchResult(True, "applied", details={"status": "applied"})

    config = _config(tmp_path)
    dispatcher = AcceptedThenApplied()
    store = ControllerStore(config.database_path)
    now = [100]
    service = ControllerService(
        config, store, dispatcher, clock=lambda: now[0], sleeper=lambda _: None, dispatch_attempts=3
    )

    service.handle_update(_update(1, 10, "/device a sample-now"))
    service.dispatch_once("worker-1")
    command = store.get_command_by_update(1)
    assert command is not None
    assert command["status"] == "dispatching"
    assert store.get_command_targets(command["command_id"])[0]["status"] == "accepted"
    assert dispatcher.calls == 1

    restarted = ControllerService(
        config,
        ControllerStore(config.database_path),
        dispatcher,
        clock=lambda: now[0],
        sleeper=lambda _: None,
    )
    assert not restarted.dispatch_once("restart-worker")
    for due in (102, 104, 106):
        now[0] = due
        assert restarted.dispatch_once("restart-worker")

    assert store.get_command(command["command_id"])["status"] == "applied"


def test_restart_resumes_accepted_commands_but_never_previews(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = ControllerStore(config.database_path)
    policy_service = ControllerService(config, store, Recorder(), clock=lambda: 100)
    accepted = store.create_command(
        update_id=5,
        actor_id="10",
        chat_id="-1",
        topic_id="7",
        scope="device",
        target="a",
        operation="status",
        arguments={},
        device_ids=("a",),
        expires_at=400,
        status="accepted",
        dispatch_policy=policy_service._dispatch_policy(("a",)),
        now=100,
    )
    store.create_command(
        update_id=6,
        actor_id="99",
        chat_id="-1",
        topic_id="7",
        scope="fleet",
        target="west",
        operation="reboot",
        arguments={},
        device_ids=("a", "b"),
        expires_at=400,
        status="preview",
        now=100,
    )
    recorder = Recorder()

    ControllerService(
        config, ControllerStore(config.database_path), recorder, clock=lambda: 100
    ).resume_pending()

    assert [envelope.command_id for envelope in recorder.envelopes] == [accepted]
    assert store.get_command(accepted)["status"] == "applied"


def test_ota_stage_canary_promote_status_and_abort_are_controller_orchestrated(
    tmp_path: Path,
) -> None:
    config = _ota_config(tmp_path)
    recorder = Recorder()
    store = ControllerStore(config.database_path)
    service = ControllerService(config, store, recorder, clock=lambda: 100)

    service.handle_update(_update(1, 99, "/ota west stage stable"))
    stage_confirmation = _last_confirmation(store)
    assert "/ota west confirm" in store.pending_replies()[-1]["text"]
    service.handle_update(_update(2, 99, f"/ota west confirm {stage_confirmation}"))
    service.resume_pending()

    snapshot = store.get_state("ota:west")
    assert snapshot is not None
    deployment_id = snapshot["deployment_id"]
    assert [envelope.type for envelope in recorder.envelopes] == [
        "ota_stage",
        "ota_stage",
        "ota_stage",
    ]
    assert {envelope.device_id for envelope in recorder.envelopes} == {"a", "b", "c"}
    assert all(
        envelope.command_id.startswith(f"{deployment_id}:ota_stage:") for envelope in recorder.envelopes
    )
    assert all(envelope.args["release_alias"] == "stable" for envelope in recorder.envelopes)
    assert all("manifest" in envelope.args for envelope in recorder.envelopes)

    restarted = ControllerService(config, ControllerStore(config.database_path), recorder, clock=lambda: 100)
    restarted.handle_update(_update(3, 99, "/ota west status"))
    assert deployment_id in store.pending_replies()[-1]["text"]
    assert len(recorder.envelopes) == 3

    restarted.handle_update(_update(4, 99, f"/ota west canary {deployment_id}"))
    canary_confirmation = _last_confirmation(store)
    restarted.handle_update(_update(5, 99, f"/ota west confirm {canary_confirmation}"))
    restarted.resume_pending()
    assert recorder.envelopes[-1].type == "ota_canary"
    assert recorder.envelopes[-1].device_id == "a"

    restarted.handle_update(_update(6, 99, f"/ota west promote {deployment_id}"))
    promote_confirmation = _last_confirmation(store)
    restarted.handle_update(_update(7, 99, f"/ota west confirm {promote_confirmation}"))
    restarted.resume_pending()
    assert recorder.envelopes[-1].type == "ota_promote"
    assert recorder.envelopes[-1].device_id == "b"
    assert recorder.envelopes[-1].args == {}

    before_abort = len(recorder.envelopes)
    restarted.handle_update(_update(8, 99, f"/ota west abort {deployment_id}"))
    abort_confirmation = _last_confirmation(store)
    restarted.handle_update(_update(9, 99, f"/ota west confirm {abort_confirmation}"))
    restarted.resume_pending()
    assert len(recorder.envelopes) == before_abort
    assert store.get_state("ota:west")["status"] == "aborted"  # type: ignore[index]
    assert "no device rollback" in store.pending_replies()[-1]["text"]


def test_ota_staging_failure_durably_halts_before_canary(tmp_path: Path) -> None:
    class StageFailure(Recorder):
        def dispatch(self, envelope):
            self.envelopes.append(envelope)
            return DispatchResult(envelope.device_id != "b", "stage result", retryable=False)

    config = _ota_config(tmp_path)
    recorder = StageFailure()
    store = ControllerStore(config.database_path)
    service = ControllerService(config, store, recorder, clock=lambda: 100)
    service.handle_update(_update(1, 99, "/ota west stage stable"))
    token = _last_confirmation(store)
    service.handle_update(_update(2, 99, f"/ota west confirm {token}"))
    service.resume_pending()
    deployment_id = store.get_state("ota:west")["deployment_id"]  # type: ignore[index]

    service.handle_update(_update(3, 99, f"/ota west canary {deployment_id}"))

    assert "stage successfully" in store.pending_replies()[-1]["text"]
    assert store.get_state("ota:west")["status"] == "halted"  # type: ignore[index]


def test_ota_resume_replays_same_device_command_after_crash_between_state_and_target_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _ota_config(tmp_path)
    assert base.ota is not None
    config = replace(
        base,
        ota=replace(base.ota, rollout_percentages=(100,)),
        devices={"a": base.devices["a"]},
        fleets={"west": Fleet("west", ("a",), "7", ("a",))},
    )
    recorder = Recorder()
    store = ControllerStore(config.database_path)
    service = ControllerService(config, store, recorder, clock=lambda: 100)
    service.handle_update(_update(1, 99, "/ota west stage stable"))
    service.handle_update(_update(2, 99, f"/ota west confirm {_last_confirmation(store)}"))
    service.resume_pending()
    deployment_id = store.get_state("ota:west")["deployment_id"]  # type: ignore[index]
    service.handle_update(_update(3, 99, f"/ota west canary {deployment_id}"))
    confirmation = _last_confirmation(store)

    def crash_before_target_receipt(*args, **kwargs):
        del args, kwargs
        raise KeyboardInterrupt

    monkeypatch.setattr(store, "set_target_result", crash_before_target_receipt)
    service.handle_update(_update(4, 99, f"/ota west confirm {confirmation}"))
    with pytest.raises(KeyboardInterrupt):
        service.dispatch_once("crashing-worker")
    pending_id = ControllerStore(config.database_path).pending_command_ids(100)[0]
    canary_command_id = recorder.envelopes[-1].command_id

    restarted_store = ControllerStore(config.database_path)
    restarted = ControllerService(config, restarted_store, recorder, clock=lambda: 286)
    restarted.resume_pending()

    canary_envelopes = [item for item in recorder.envelopes if item.type == "ota_canary"]
    assert [item.command_id for item in canary_envelopes] == [canary_command_id, canary_command_id]
    assert restarted_store.get_command(pending_id)["status"] == "applied"


def test_telegram_errors_do_not_expose_control_bot_secret() -> None:
    class BrokenSession:
        def post(self, *args, **kwargs):
            raise __import__("requests").RequestException("network failed")

    client = TelegramClient("top-secret-control-token", session=BrokenSession())  # type: ignore[arg-type]
    try:
        client.get_updates(offset=4, poll_timeout_s=1)
    except TelegramError as exc:
        assert "top-secret-control-token" not in str(exc)
    else:
        raise AssertionError("expected TelegramError")


def test_slow_dispatcher_never_blocks_update_acceptance(tmp_path: Path) -> None:
    class SlowDispatcher:
        def dispatch(self, envelope):
            del envelope
            time.sleep(0.25)
            return DispatchResult(True, "ok")

    config = _config(tmp_path)
    store = ControllerStore(config.database_path)
    service = ControllerService(config, store, SlowDispatcher(), clock=lambda: 100)

    started = time.monotonic()
    assert service.handle_update(_update(1, 10, "/device a status"))
    elapsed = time.monotonic() - started

    assert elapsed < 0.1
    command = store.get_command_by_update(1)
    assert command is not None and command["status"] == "accepted"
    assert "queued" in store.pending_replies()[-1]["text"]


def test_read_only_fleet_freezes_concurrency_and_safe_mixed_transport_ttl(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config = replace(
        config,
        ssh=replace(config.ssh, connect_timeout_s=12, command_timeout_s=70),
        devices={
            "a": config.devices["a"],
            "b": replace(config.devices["b"], transport="spacebridge"),
        },
        fleet_dispatch_concurrency=2,
    )
    store = ControllerStore(config.database_path)
    service = ControllerService(config, store, Recorder(), clock=lambda: 100, dispatch_attempts=3)

    service.handle_update(_update(1, 10, "/fleet west status"))
    command = store.get_command_by_update(1)

    assert command is not None
    assert command["status"] == "accepted"
    assert command["preview"]["dispatch_policy"] == command["dispatch_policy"]
    policy = command["dispatch_policy"]
    assert policy["max_workers"] == 2
    assert policy["spacebridge_tunnel_connect_timeout_s"] == 12
    assert policy["spacebridge_tunnel_cleanup_s"] == 4
    assert policy["per_attempt_worst_case_s"] == 86
    expected_duration = 3 * 86 + 0.25 + 0.5 + config.command_ttl_s + 30
    assert policy["max_dispatch_duration_s"] == expected_duration
    assert command["expires_at"] == 100 + ceil(expected_duration)


def test_expiry_stops_future_dispatch_waves(tmp_path: Path) -> None:
    now = [100]

    class AdvancesClock(Recorder):
        def dispatch(self, envelope):
            self.envelopes.append(envelope)
            now[0] = 10_000
            return DispatchResult(True, "ok")

    config = replace(_config(tmp_path), fleet_dispatch_concurrency=1)
    dispatcher = AdvancesClock()
    store = ControllerStore(config.database_path)
    service = ControllerService(config, store, dispatcher, clock=lambda: now[0])
    service.handle_update(_update(1, 10, "/fleet west status"))

    service.dispatch_once("worker")

    assert [item.device_id for item in dispatcher.envelopes] == ["a"]
    command = store.get_command_by_update(1)
    assert command is not None and command["status"] == "expired"


def test_confirmed_ota_abort_stops_future_stage_waves_without_rollback(tmp_path: Path) -> None:
    config = replace(_ota_config(tmp_path), fleet_dispatch_concurrency=1)
    store = ControllerStore(config.database_path)

    class AbortAfterFirst(Recorder):
        service: ControllerService

        def dispatch(self, envelope):
            self.envelopes.append(envelope)
            if len(self.envelopes) == 1:
                deployment_id = envelope.command_id.split(":", 1)[0]
                self.service.handle_update(_update(3, 99, f"/ota west abort {deployment_id}"))
                confirmation = _last_confirmation(store)
                self.service.handle_update(_update(4, 99, f"/ota west confirm {confirmation}"))
            return DispatchResult(True, "ok")

    dispatcher = AbortAfterFirst()
    service = ControllerService(config, store, dispatcher, clock=lambda: 100)
    dispatcher.service = service
    service.handle_update(_update(1, 99, "/ota west stage stable"))
    service.handle_update(_update(2, 99, f"/ota west confirm {_last_confirmation(store)}"))

    service.dispatch_once("stage-worker")

    assert len(dispatcher.envelopes) == 1
    stage = store.get_command_by_update(1)
    assert stage is not None and stage["status"] == "aborted"
    snapshot = store.get_state("ota:west")
    assert snapshot is not None and snapshot["status"] == "aborted"
    assert snapshot["undispatched_at_abort"] == ["a", "b", "c"]


def test_crash_after_terminal_state_reconciles_completion_reply_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    store = ControllerStore(config.database_path)
    recorder = Recorder()
    service = ControllerService(config, store, recorder, clock=lambda: 100)
    service.handle_update(_update(1, 10, "/device a status"))
    command = store.get_command_by_update(1)
    assert command is not None

    def crash_before_completion(*args, **kwargs):
        del args, kwargs
        raise KeyboardInterrupt

    monkeypatch.setattr(store, "complete_command", crash_before_completion)
    with pytest.raises(KeyboardInterrupt):
        service.dispatch_once("crashing-worker")
    assert store.get_command(command["command_id"])["status"] == "applied"

    restarted = ControllerService(config, ControllerStore(config.database_path), recorder, clock=lambda: 286)
    assert restarted.dispatch_once("recovery-worker")
    assert not restarted.dispatch_once("recovery-worker")
    replies = ControllerStore(config.database_path).pending_replies(limit=100)
    completion_key = f"command:{command['command_id']}:completion"
    assert sum(reply["dedupe_key"] == completion_key for reply in replies) == 1
    assert len(recorder.envelopes) == 1
