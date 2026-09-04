from __future__ import annotations

import importlib
import json
import os
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent.local_control as local_control_module
from agent.local_control import (
    MAX_ENVELOPE_BYTES,
    AppliedCommandLedger,
    LocalControlError,
    LocalControlExecutor,
    LocalControlState,
    parse_envelope,
)

AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
agent_main = importlib.import_module("edgewatch_agent")


def _raw(command_type: str, args: dict[str, object] | None = None, **changes: object) -> bytes:
    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {
        "version": 1,
        "command_id": "cmd-001",
        "device_id": "device-1",
        "issued_at": (now - timedelta(seconds=1)).isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "type": command_type,
        "args": args or {},
    }
    payload.update(changes)
    return json.dumps(payload).encode()


def _executor(tmp_path: Path, run_command=None) -> LocalControlExecutor:
    kwargs = {}
    if run_command is not None:
        kwargs["run_command"] = run_command
    return LocalControlExecutor(
        device_id="device-1",
        state=LocalControlState(tmp_path / "control.json"),
        ledger=AppliedCommandLedger(tmp_path / "ledger.sqlite"),
        **kwargs,
    )


def test_parser_rejects_unknown_duplicate_confusable_and_oversize_keys() -> None:
    with pytest.raises(LocalControlError, match="unknown=extra"):
        parse_envelope(_raw("status", extra=True), expected_device_id="device-1")

    duplicate = _raw("status").decode().replace('"version": 1', '"version": 1, "version": 1')
    with pytest.raises(LocalControlError, match="duplicate JSON key"):
        parse_envelope(duplicate.encode(), expected_device_id="device-1")

    confusable = _raw("status").decode().replace('"type"', '"typе"')  # Cyrillic e.
    with pytest.raises(LocalControlError, match="ASCII"):
        parse_envelope(confusable.encode(), expected_device_id="device-1")

    with pytest.raises(LocalControlError, match="exceeds"):
        parse_envelope(b"{" + (b" " * MAX_ENVELOPE_BYTES), expected_device_id="device-1")


def test_parser_rejects_expired_wrong_device_and_untyped_args() -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(LocalControlError) as expired:
        parse_envelope(
            _raw(
                "status",
                issued_at=(now - timedelta(minutes=2)).isoformat(),
                expires_at=(now - timedelta(seconds=1)).isoformat(),
            ),
            expected_device_id="device-1",
            now=now,
        )
    assert expired.value.code == "expired"

    with pytest.raises(LocalControlError) as wrong:
        parse_envelope(_raw("status", device_id="device-2"), expected_device_id="device-1")
    assert wrong.value.code == "wrong_device"

    with pytest.raises(LocalControlError, match="unknown args keys"):
        parse_envelope(_raw("reboot", {"command": "whoami"}), expected_device_id="device-1")

    with pytest.raises(LocalControlError, match="not allowed"):
        parse_envelope(_raw("shell", {"argv": ["id"]}), expected_device_id="device-1")


def test_mutating_command_is_durable_and_replay_does_not_repeat_action(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    executor = _executor(tmp_path, run)
    envelope = parse_envelope(_raw("reboot"), expected_device_id="device-1")

    first = executor.execute(envelope)
    second = executor.execute(envelope)

    assert calls == [["systemctl", "--no-block", "reboot"]]
    assert first["result"] == second["result"] == {"scheduled": True}
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert (tmp_path / "ledger.sqlite").stat().st_mode & 0o777 == 0o600


def test_view_commands_report_effective_runtime_and_power_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ready = tmp_path / "ready.json"
    ready.write_text("{}", encoding="utf-8")
    power_state = tmp_path / "power.json"
    power_state.write_text(
        json.dumps(
            {
                "last_power_source": "unknown",
                "last_evaluation": {
                    "power_input_out_of_range": False,
                    "power_unsustainable": False,
                    "power_saver_active": False,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EDGEWATCH_READY_PATH", str(ready))
    monkeypatch.setenv("EDGEWATCH_POWER_STATE_PATH", str(power_state))
    monkeypatch.setenv("EDGEWATCH_TELEMETRY_TRANSPORT", "telegram")
    monkeypatch.setenv("EDGEWATCH_AGENT_VERSION", "control-pilot-2")
    monkeypatch.setenv("RUNTIME_POWER_MODE", "continuous")

    def run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        assert argv == ["vcgencmd", "get_throttled"]
        return SimpleNamespace(returncode=0, stdout="throttled=0x0\n", stderr="")

    executor = _executor(tmp_path, run)
    status = executor.execute(
        parse_envelope(_raw("status", command_id="cmd-status"), expected_device_id="device-1")
    )["result"]
    power = executor.execute(
        parse_envelope(_raw("power", command_id="cmd-power"), expected_device_id="device-1")
    )["result"]

    assert status == {
        "device_id": "device-1",
        "ready": True,
        "transport": "telegram",
        "version": "control-pilot-2",
        "operation_mode": "active",
        "runtime_power_mode": "continuous",
        "alerts_muted_until": None,
        "pending_requests": 0,
    }
    assert power == {
        "source": "unknown",
        "input_out_of_range": False,
        "unsustainable": False,
        "saver_active": False,
        "runtime_power_mode": "continuous",
        "throttled": "throttled=0x0",
    }


def test_command_id_cannot_be_reused_for_different_operation(tmp_path: Path) -> None:
    executor = _executor(tmp_path)
    executor.execute(parse_envelope(_raw("sample_now"), expected_device_id="device-1"))

    with pytest.raises(LocalControlError) as conflict:
        executor.execute(parse_envelope(_raw("sync_now"), expected_device_id="device-1"))
    assert conflict.value.code == "command_id_conflict"


def test_override_and_requests_are_atomic_private_and_consumed_once(tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "control.json"
    state = LocalControlState(state_path)
    executor = LocalControlExecutor(
        device_id="device-1",
        state=state,
        ledger=AppliedCommandLedger(tmp_path / "ledger.sqlite"),
    )
    executor.execute(
        parse_envelope(
            _raw("set_operation_mode", {"mode": "sleep", "sleep_poll_interval_s": 3600}),
            expected_device_id="device-1",
        )
    )
    accepted = executor.execute(
        parse_envelope(
            _raw("sample_now", command_id="cmd-002"),
            expected_device_id="device-1",
        )
    )

    first = state.consume_for_agent()
    second = state.consume_for_agent()

    assert first.operation_mode == "sleep"
    assert first.sleep_poll_interval_s == 3600
    assert first.sample_now is True
    assert second.operation_mode == "sleep"
    assert second.sample_now is False
    assert accepted["status"] == "accepted"
    assert state_path.stat().st_mode & 0o777 == 0o600
    assert list(state_path.parent.glob("*.tmp")) == []


def test_root_writer_preserves_existing_state_backup_and_lock_owners(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "control.json"
    backup_path = state_path.with_suffix(".json.bak")
    lock_path = state_path.with_suffix(".json.lock")
    state_path.write_text("{}", encoding="utf-8")
    backup_path.write_text("{}", encoding="utf-8")
    lock_path.touch()
    owners = {
        state_path: (2101, 3101),
        backup_path: (2102, 3102),
        lock_path: (2103, 3103),
    }
    real_lstat = Path.lstat

    def fake_lstat(path: Path) -> object:
        metadata = real_lstat(path)
        if path in owners:
            uid, gid = owners[path]
            values = list(metadata)
            values[4:6] = [uid, gid]
            return os.stat_result(values)
        return metadata

    changed: list[tuple[int, int]] = []
    monkeypatch.setattr(Path, "lstat", fake_lstat)
    monkeypatch.setattr(
        local_control_module.os,
        "fchown",
        lambda _fd, uid, gid: changed.append((uid, gid)),
    )

    LocalControlState(state_path).set_override(operation_mode="sleep")

    assert changed == [owners[lock_path], owners[backup_path], owners[state_path]]
    assert stat.S_IMODE(os.lstat(state_path).st_mode) == 0o600
    assert stat.S_IMODE(os.lstat(backup_path).st_mode) == 0o600
    assert stat.S_IMODE(os.lstat(lock_path).st_mode) == 0o600


def test_root_writer_gives_new_state_and_lock_the_parent_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    parent = tmp_path / "state"
    parent.mkdir()
    state_path = parent / "control.json"
    expected_owner = (2201, 3201)
    real_stat = Path.stat

    def fake_stat(path: Path, *, follow_symlinks: bool = True) -> object:
        metadata = real_stat(path, follow_symlinks=follow_symlinks)
        if path == parent:
            values = list(metadata)
            values[4:6] = list(expected_owner)
            return os.stat_result(values)
        return metadata

    changed: list[tuple[int, int]] = []
    monkeypatch.setattr(Path, "stat", fake_stat)
    monkeypatch.setattr(
        local_control_module.os,
        "fchown",
        lambda _fd, uid, gid: changed.append((uid, gid)),
    )

    LocalControlState(state_path).set_override(operation_mode="sleep")

    assert changed == [expected_owner, expected_owner]
    assert stat.S_IMODE(os.lstat(state_path).st_mode) == 0o600
    assert stat.S_IMODE(os.lstat(state_path.with_suffix(".json.lock")).st_mode) == 0o600


@pytest.mark.parametrize("redirect", ["state", "backup", "lock"])
def test_local_control_rejects_symlink_files_without_touching_the_target(
    tmp_path: Path,
    redirect: str,
) -> None:
    state_path = tmp_path / "control.json"
    backup_path = state_path.with_suffix(".json.bak")
    lock_path = state_path.with_suffix(".json.lock")
    target = tmp_path / "unrelated.json"
    target.write_text('{"protected":true}\n', encoding="utf-8")
    target.chmod(0o640)
    original = target.read_bytes()
    original_metadata = target.stat()
    paths = {"state": state_path, "backup": backup_path, "lock": lock_path}
    if redirect != "state":
        state_path.write_text("{}", encoding="utf-8")
    paths[redirect].symlink_to(target)

    with pytest.raises(LocalControlError) as rejected:
        LocalControlState(state_path).set_override(operation_mode="sleep")

    assert rejected.value.code == "unsafe_state_file"
    assert paths[redirect].is_symlink()
    assert target.read_bytes() == original
    after = target.stat()
    assert (after.st_uid, after.st_gid) == (original_metadata.st_uid, original_metadata.st_gid)
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(original_metadata.st_mode)


@pytest.mark.parametrize("invalid", ["state", "backup", "lock"])
def test_local_control_rejects_non_regular_state_files(tmp_path: Path, invalid: str) -> None:
    state_path = tmp_path / "control.json"
    backup_path = state_path.with_suffix(".json.bak")
    lock_path = state_path.with_suffix(".json.lock")
    paths = {"state": state_path, "backup": backup_path, "lock": lock_path}
    if invalid != "state":
        state_path.write_text("{}", encoding="utf-8")
    paths[invalid].mkdir()

    with pytest.raises(LocalControlError) as rejected:
        LocalControlState(state_path).set_override(operation_mode="sleep")

    assert rejected.value.code == "unsafe_state_file"


def test_request_is_applied_only_after_agent_completion_and_replay_is_truthful(
    tmp_path: Path,
) -> None:
    executor = _executor(tmp_path)
    envelope = parse_envelope(_raw("sample_now"), expected_device_id="device-1")

    first = executor.execute(envelope)
    claimed = executor.state.consume_for_agent(claim_owner="agent-session-1")
    executor.state.complete_requests(claimed.sample_request_ids, {"sample_captured": True})
    replay = executor.execute(envelope)

    assert first["status"] == "accepted"
    assert first["result"]["request_status"] == "pending"
    assert replay["status"] == "applied"
    assert replay["replayed"] is True
    assert replay["result"]["result"] == {"sample_captured": True}


def test_claim_is_recovered_immediately_by_a_new_agent_session(tmp_path: Path) -> None:
    state = LocalControlState(tmp_path / "control.json")
    state.ensure_request("cmd-sample", "sample_now")

    first = state.consume_for_agent(claim_owner="old-process")
    restarted = state.consume_for_agent(claim_owner="new-process")

    assert first.sample_request_ids == ("cmd-sample",)
    assert restarted.sample_request_ids == ("cmd-sample",)


def test_failed_sync_is_released_for_retry_not_lost(tmp_path: Path) -> None:
    state = LocalControlState(tmp_path / "control.json")
    state.ensure_request("cmd-sync", "sync_now")
    claimed = state.consume_for_agent(claim_owner="agent-session")

    agent_main._settle_local_control_requests(
        state=state,
        local_control=claimed,
        sample_durable=False,
        sync_succeeded=False,
        failure_reason="network unavailable",
    )

    assert state.has_pending_request()
    retried = state.consume_for_agent(claim_owner="agent-session")
    assert retried.sync_request_ids == ("cmd-sync",)


def test_request_point_is_immutable_across_claims_and_restart(tmp_path: Path) -> None:
    path = tmp_path / "control.json"
    state = LocalControlState(path)
    state.ensure_request("cmd-sync", "sync_now")
    state.consume_for_agent(claim_owner="first-process")
    original = {
        "message_id": "stable-message",
        "ts": "2026-08-10T12:00:00+00:00",
        "metrics": {"temperature_c": 21.25, "nested": {"source": "first"}},
    }

    persisted = state.persist_request_point("cmd-sync", original)
    state.release_requests(("cmd-sync",), "restart")
    LocalControlState(path).consume_for_agent(claim_owner="second-process")
    replayed = LocalControlState(path).persist_request_point(
        "cmd-sync",
        {
            "message_id": "different-message",
            "ts": "2026-08-10T12:01:00+00:00",
            "metrics": {"temperature_c": 99.0},
        },
    )

    assert persisted == original
    assert replayed == original
    assert LocalControlState(path).snapshot()["requests"]["cmd-sync"]["point"] == original


def test_corrupt_state_fails_closed_and_preserves_last_good_backup(tmp_path: Path) -> None:
    path = tmp_path / "control.json"
    state = LocalControlState(path)
    state.set_override(operation_mode="sleep")
    state.set_override(runtime_power_mode="eco")
    backup = path.with_suffix(".json.bak")
    assert backup.is_file()
    last_good_backup = backup.read_bytes()
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(LocalControlError) as corrupt:
        state.set_override(operation_mode="active")

    assert corrupt.value.code == "state_corrupt"
    assert path.read_text(encoding="utf-8") == "{broken"
    assert backup.read_bytes() == last_good_backup


def test_shutdown_is_guarded_and_fixed_argv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    envelope = parse_envelope(_raw("shutdown"), expected_device_id="device-1")
    with pytest.raises(LocalControlError) as disabled:
        _executor(tmp_path / "disabled", run).execute(envelope)
    assert disabled.value.code == "shutdown_disabled"
    assert calls == []

    monkeypatch.setenv("EDGEWATCH_ALLOW_LOCAL_CONTROL_SHUTDOWN", "1")
    allowed_envelope = parse_envelope(
        _raw("shutdown", command_id="cmd-shutdown-2"), expected_device_id="device-1"
    )
    _executor(tmp_path / "enabled", run).execute(allowed_envelope)
    assert calls == [["systemctl", "--no-block", "poweroff"]]


def test_no_plaintext_shell_file_environment_or_at_command_types_are_accepted() -> None:
    for command_type in ("shell", "file_read", "environment", "at_command"):
        with pytest.raises(LocalControlError) as rejected:
            parse_envelope(_raw(command_type), expected_device_id="device-1")
        assert rejected.value.code == "unknown_command"


def test_agent_applies_local_overrides_and_wakes_early_for_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = SimpleNamespace(
        operation_mode="sleep",
        sleep_poll_interval_s=900,
        runtime_power_mode="eco",
    )
    assert agent_main._apply_local_control_overrides(
        local_control=control,
        operation_mode="active",
        sleep_poll_interval_s=604800,
        runtime_power_mode="continuous",
    ) == ("sleep", 900, "eco")

    sleeps: list[float] = []
    monkeypatch.setattr(agent_main.time, "sleep", sleeps.append)
    monkeypatch.setattr(agent_main.time, "monotonic", lambda: float(len(sleeps)))
    monkeypatch.setattr(agent_main, "_LOCAL_CONTROL_WAKE_CHECK", lambda: True)
    agent_main._sleep(3600)
    assert sleeps == [2.0]


def test_agent_alert_mute_is_active_only_until_its_utc_expiry() -> None:
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)

    assert agent_main._local_alert_delivery_muted(
        "2026-08-09T12:01:00Z",
        now_utc=now,
    )
    assert not agent_main._local_alert_delivery_muted(
        "2026-08-09T12:00:00Z",
        now_utc=now,
    )
    assert not agent_main._local_alert_delivery_muted("invalid", now_utc=now)
    assert not agent_main._local_alert_delivery_muted(None, now_utc=now)

    active_alerts = {"WATER_PRESSURE_LOW"}
    assert agent_main._reportable_alert_state(
        current_alerts=active_alerts,
        previous_alerts=set(),
        delivery_muted=False,
    ) == (True, True)
    assert agent_main._reportable_alert_state(
        current_alerts=active_alerts,
        previous_alerts=set(),
        delivery_muted=True,
    ) == (False, False)


def test_controller_operation_names_map_to_typed_local_state(tmp_path: Path) -> None:
    executor = _executor(tmp_path)
    executor.execute(parse_envelope(_raw("mode_sleep", command_id="mode-1"), expected_device_id="device-1"))
    executor.execute(
        parse_envelope(
            _raw("deep_sleep", {"duration": "30m"}, command_id="power-1"),
            expected_device_id="device-1",
        )
    )
    executor.execute(
        parse_envelope(
            _raw("alert_mute", {"duration": "7d"}, command_id="mute-1"),
            expected_device_id="device-1",
        )
    )

    snapshot = executor.state.snapshot()
    assert snapshot["overrides"] == {
        "operation_mode": "sleep",
        "runtime_power_mode": "deep_sleep",
        "sleep_poll_interval_s": 1800,
    }
    assert snapshot["alerts"]["muted_until"] is not None


def test_ota_adapter_uses_only_exact_typed_command_and_alias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, object], str]] = []

    class Manager:
        @classmethod
        def from_env(cls, device_id: str):
            assert device_id == "device-1"
            return cls()

        def handle_command(
            self, *, command_type: str, args: dict[str, object], command_id: str
        ) -> dict[str, object]:
            calls.append((command_type, args, command_id))
            return {"ok": True, "status": "staged"}

    monkeypatch.setattr(
        "agent.local_control.importlib.import_module",
        lambda name: SimpleNamespace(LocalOtaManager=Manager) if name == "agent.local_ota" else None,
    )
    envelope = parse_envelope(
        _raw("ota_stage", {"release_alias": "stable"}, command_id="ota-1"),
        expected_device_id="device-1",
    )

    result = _executor(tmp_path).execute(envelope)

    assert result["status"] == "applied"
    assert calls == [("ota_stage", {"release_alias": "stable"}, "ota-1")]


def test_ota_adapter_accepts_trusted_manifest_without_local_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, object], str]] = []

    class Manager:
        @classmethod
        def from_env(cls, device_id: str):
            assert device_id == "device-1"
            return cls()

        def handle_command(self, **_kwargs: object) -> dict[str, object]:
            raise AssertionError("manifest commands must use the narrow execute adapter")

        def execute(self, action: str, manifest: dict[str, object], command_id: str) -> dict[str, object]:
            calls.append((action, manifest, command_id))
            return {"ok": True, "status": "staged" if action == "stage" else "applied"}

    monkeypatch.setattr(
        "agent.local_control.importlib.import_module",
        lambda name: SimpleNamespace(LocalOtaManager=Manager) if name == "agent.local_ota" else None,
    )
    manifest = {"version": "1.2.3", "artifact_sha256": "a" * 64}
    envelope = parse_envelope(
        _raw(
            "ota_canary",
            {"release_alias": "stable", "manifest": manifest},
            command_id="ota-canary-1",
        ),
        expected_device_id="device-1",
    )

    result = _executor(tmp_path).execute(envelope)

    assert result["status"] == "applied"
    assert calls == [
        ("stage", manifest, "ota-canary-1:stage"),
        ("apply", manifest, "ota-canary-1"),
    ]

    with pytest.raises(LocalControlError, match="manifest must be an object"):
        parse_envelope(
            _raw("ota_stage", {"release_alias": "stable", "manifest": "not-an-object"}),
            expected_device_id="device-1",
        )


def test_retryable_ota_failure_is_not_committed_to_applied_ledger(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class RetryableOtaError(RuntimeError):
        pass

    class Manager:
        @classmethod
        def from_env(cls, device_id: str):
            assert device_id == "device-1"
            return cls()

        def handle_command(self, **_kwargs: object) -> dict[str, object]:
            raise RetryableOtaError("temporary download failure")

    monkeypatch.setattr(
        "agent.local_control.importlib.import_module",
        lambda name: (
            SimpleNamespace(
                LocalOtaManager=Manager,
                RetryableOtaError=RetryableOtaError,
            )
            if name == "agent.local_ota"
            else None
        ),
    )
    executor = _executor(tmp_path)
    envelope = parse_envelope(
        _raw("ota_stage", {"release_alias": "stable"}, command_id="ota-retry-1"),
        expected_device_id="device-1",
    )

    with pytest.raises(LocalControlError) as raised:
        executor.execute(envelope)

    assert raised.value.code == "ota_retryable"
    with executor.ledger._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM applied_commands").fetchone()[0] == 0
