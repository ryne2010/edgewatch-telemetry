from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent.lorawan.store import GatewayStore
from gateway_runtime.artifact_cache import RetryableArtifactCacheError
from telegram_controller.config import (
    ControllerConfig,
    MaintenanceConfig,
    SSHConfig,
    TelegramConfig,
)
from telegram_controller.models import Device, DispatchEnvelope
from telegram_controller.ssh_dispatch import DeviceDispatcher


def _config(tmp_path: Path, device: Device, *, spacebridge: bool = False) -> ControllerConfig:
    key = tmp_path / "device-key"
    known_hosts = tmp_path / "known-hosts"
    token = tmp_path / "token"
    bridge_key = tmp_path / "spacebridge-key"
    for path in (key, known_hosts, token, bridge_key):
        path.write_text("fixture", encoding="utf-8")
        path.chmod(0o600)
    return ControllerConfig(
        telegram=TelegramConfig(token),
        ssh=SSHConfig(
            key,
            known_hosts,
            username="ryne",
            connect_timeout_s=7,
            command_timeout_s=19,
            spacebridge_identity_file=bridge_key if spacebridge else None,
            spacebridge_host="tunnel.hologram.io",
            spacebridge_user="htunnel",
            spacebridge_port=999,
        ),
        database_path=tmp_path / "controller.sqlite",
        principals={},
        devices={device.device_id: device},
        fleets={},
        allowed_chats=frozenset(),
    )


def _envelope(device_id: str = "pump-1") -> DispatchEnvelope:
    return DispatchEnvelope(
        version=1,
        command_id="cmd-123",
        device_id=device_id,
        issued_at="2026-08-09T12:34:56Z",
        expires_at="2026-08-09T12:39:56Z",
        type="sample_now",
        args={"reason": "operator"},
    )


def _response(*, status: str = "applied") -> bytes:
    return json.dumps(
        {
            "version": 1,
            "command_id": "cmd-123",
            "device_id": "pump-1",
            "status": status,
            "replayed": False,
            "result": {"requested": "sample_now"},
        }
    ).encode()


def _rejected_response(code: str) -> bytes:
    return json.dumps(
        {
            "version": 1,
            "command_id": "cmd-123",
            "device_id": "pump-1",
            "status": "rejected",
            "error": {"code": code, "message": "redacted device message"},
        }
    ).encode()


class RecordingRunner:
    def __init__(self, stdout: bytes = b"", returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> SimpleNamespace:
        self.calls.append((argv, kwargs))
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=b"")


def test_direct_dispatch_uses_fixed_pinned_ssh_argv_and_rfc3339_json(tmp_path: Path) -> None:
    device = Device(
        "pump-1",
        "west",
        "10.2.3.4",
        metadata={"port": 2202, "host_key_alias": "pump-1-control"},
    )
    runner = RecordingRunner(_response())
    dispatcher = DeviceDispatcher(_config(tmp_path, device), run_command=runner)

    result = dispatcher.dispatch(_envelope())

    assert result.ok
    argv, options = runner.calls[0]
    assert argv == [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={tmp_path / 'known-hosts'}",
        "-o",
        "ConnectTimeout=7",
        "-i",
        str(tmp_path / "device-key"),
        "-p",
        "2202",
        "-o",
        "HostKeyAlias=pump-1-control",
        "ryne@10.2.3.4",
    ]
    assert options["shell"] is False
    assert options["timeout"] == 19
    assert json.loads(options["input"]) == {
        "version": 1,
        "command_id": "cmd-123",
        "device_id": "pump-1",
        "issued_at": "2026-08-09T12:34:56Z",
        "expires_at": "2026-08-09T12:39:56Z",
        "type": "sample_now",
        "args": {"reason": "operator"},
    }


def test_local_dispatch_uses_only_the_fixed_privileged_helper(tmp_path: Path) -> None:
    device = Device("pump-1", "west", "localhost", transport="local")
    runner = RecordingRunner(_response())
    dispatcher = DeviceDispatcher(_config(tmp_path, device), run_command=runner)

    result = dispatcher.dispatch(_envelope())

    assert result.ok
    argv, options = runner.calls[0]
    assert argv == [
        "/usr/bin/sudo",
        "-n",
        "/usr/local/libexec/edgewatch-device-control-local",
        "--device-id",
        "pump-1",
        "--ssh-stdin",
    ]
    assert options["shell"] is False
    assert json.loads(options["input"])["command_id"] == "cmd-123"


def test_maintenance_transport_wakes_over_lora_before_pinned_wifi_ssh(tmp_path: Path) -> None:
    device = Device(
        "pump-1",
        "west",
        "10.42.0.21",
        transport="maintenance_via_lora",
        metadata={"host_key_alias": "pump-1-maintenance"},
    )
    registry = tmp_path / "lorawan-registry.yaml"
    registry.write_text(
        """
devices:
  pump-1:
    application_id: edgewatch
    dev_eui: '0011223344556677'
    join_eui: '0102030405060708'
    app_key: '00112233445566778899aabbccddeeff'
    wake_key: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
""",
        encoding="utf-8",
    )
    registry.chmod(0o600)
    store_path = tmp_path / "lorawan.sqlite"
    base = _config(tmp_path, device)
    config = replace(
        base,
        maintenance=MaintenanceConfig(registry, store_path, readiness_timeout_s=300),
        command_ttl_s=7200,
    )
    runner = RecordingRunner(_response())
    dispatcher = DeviceDispatcher(config, run_command=runner)
    now = datetime.now(tz=UTC)
    envelope = replace(
        _envelope(),
        issued_at=now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        expires_at=(now + timedelta(hours=2)).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )

    waiting = dispatcher.dispatch(envelope)

    assert not waiting.ok
    assert waiting.retryable
    assert waiting.details == {"status": "accepted", "wake_state": "waiting_uplink"}
    assert runner.calls == []
    store = GatewayStore(store_path)
    wake = store.get_wake("cmd-123")
    assert wake is not None
    claimed = store.claim_wake_for_uplink(wake.dev_eui, "test", now=wake.issued_at + 1)
    assert claimed is not None
    assert store.mark_wake_published("cmd-123", "test", now=wake.issued_at + 1)
    assert store.mark_device_ready(
        wake.dev_eui,
        wake.command_token,
        now=wake.issued_at + 2,
    ) == ("cmd-123",)

    applied = dispatcher.dispatch(envelope)

    assert applied.ok
    assert runner.calls[0][0][-1] == "ryne@10.42.0.21"
    assert "HostKeyAlias=pump-1-maintenance" in runner.calls[0][0]


def test_maintenance_ota_is_cached_before_satellite_wake(tmp_path: Path) -> None:
    device = Device(
        "pump-1",
        "west",
        "10.42.0.21",
        transport="maintenance_via_lora",
        metadata={"host_key_alias": "pump-1-maintenance"},
    )
    registry = tmp_path / "lorawan-registry.yaml"
    registry.write_text(
        """
devices:
  pump-1:
    application_id: edgewatch
    dev_eui: '0011223344556677'
    join_eui: '0102030405060708'
    app_key: '00112233445566778899aabbccddeeff'
    wake_key: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
""",
        encoding="utf-8",
    )
    registry.chmod(0o600)
    config = replace(
        _config(tmp_path, device),
        maintenance=MaintenanceConfig(registry, tmp_path / "lorawan.sqlite"),
        command_ttl_s=7200,
    )

    class Cache:
        def __init__(self) -> None:
            self.payloads: list[dict[str, object]] = []

        def ensure(self, payload: Mapping[str, Any]) -> Path:
            self.payloads.append(dict(payload))
            return tmp_path / "cached"

    cache = Cache()
    now = datetime.now(tz=UTC)
    envelope = replace(
        _envelope(),
        type="ota_stage",
        args={"release_alias": "v1", "manifest": {"artifact_sha256": "a" * 64}},
        issued_at=now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        expires_at=(now + timedelta(hours=2)).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )

    result = DeviceDispatcher(config, artifact_cache=cache).dispatch(envelope)

    assert result.retryable
    assert cache.payloads == [{"artifact_sha256": "a" * 64}]
    assert GatewayStore(tmp_path / "lorawan.sqlite").get_wake("cmd-123") is not None


def test_retryable_gateway_cache_failure_does_not_queue_satellite_wake(tmp_path: Path) -> None:
    device = Device(
        "pump-1",
        "west",
        "10.42.0.21",
        transport="maintenance_via_lora",
        metadata={"host_key_alias": "pump-1-maintenance"},
    )
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        """
devices:
  pump-1:
    application_id: edgewatch
    dev_eui: '0011223344556677'
    join_eui: '0102030405060708'
    app_key: '00112233445566778899aabbccddeeff'
    wake_key: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
""",
        encoding="utf-8",
    )
    registry.chmod(0o600)
    config = replace(
        _config(tmp_path, device),
        maintenance=MaintenanceConfig(registry, tmp_path / "lorawan.sqlite"),
    )

    class OfflineCache:
        def ensure(self, payload: Mapping[str, Any]) -> Path:
            del payload
            raise RetryableArtifactCacheError("offline")

    result = DeviceDispatcher(config, artifact_cache=OfflineCache()).dispatch(
        replace(
            _envelope(),
            type="ota_canary",
            args={"release_alias": "v1", "manifest": {"artifact_sha256": "a" * 64}},
        )
    )

    assert not result.ok
    assert result.retryable
    assert result.summary == "gateway OTA cache is not ready"


def test_accepted_device_response_is_strictly_parsed_as_retryable_pending(
    tmp_path: Path,
) -> None:
    device = Device("pump-1", "west", "host")

    result = DeviceDispatcher(
        _config(tmp_path, device), run_command=RecordingRunner(_response(status="accepted"))
    ).dispatch(_envelope())

    assert not result.ok
    assert result.retryable
    assert result.summary == "command accepted and pending device completion"
    assert result.details == {
        "status": "accepted",
        "replayed": False,
        "result": {"requested": "sample_now"},
    }


@pytest.mark.parametrize(("code", "retryable"), [("ota_retryable", True), ("invalid_command", False)])
def test_only_explicit_ota_retryable_rejection_is_retried(tmp_path: Path, code: str, retryable: bool) -> None:
    device = Device("pump-1", "west", "host")

    result = DeviceDispatcher(
        _config(tmp_path, device),
        run_command=RecordingRunner(_rejected_response(code), returncode=1),
    ).dispatch(_envelope())

    assert not result.ok
    assert result.retryable is retryable
    assert result.details == {"code": code}
    assert "redacted device message" not in result.summary


@pytest.mark.parametrize(
    ("returncode", "retryable"),
    [(1, False), (255, True)],
)
def test_nonzero_ssh_exit_is_classified_without_exposing_stderr(
    tmp_path: Path, returncode: int, retryable: bool
) -> None:
    device = Device("pump-1", "west", "host")

    def failed(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        del argv, kwargs
        return SimpleNamespace(returncode=returncode, stdout=b"", stderr=b"/secret/key: denied")

    result = DeviceDispatcher(_config(tmp_path, device), run_command=failed).dispatch(_envelope())

    assert not result.ok
    assert result.retryable is retryable
    assert "/secret/key" not in result.summary
    assert result.details == {"exit_code": returncode}


def test_timeout_is_retryable_and_redacted(tmp_path: Path) -> None:
    device = Device("pump-1", "west", "host")

    def timed_out(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        del kwargs
        raise subprocess.TimeoutExpired(argv, 19, stderr=b"private path")

    result = DeviceDispatcher(_config(tmp_path, device), run_command=timed_out).dispatch(_envelope())

    assert not result.ok
    assert result.retryable
    assert "private path" not in result.summary


@pytest.mark.parametrize(
    "output",
    [
        b"not-json",
        b"{}",
        b"[]",
        json.dumps(
            {
                "version": 1,
                "command_id": "cmd-123",
                "device_id": "pump-1",
                "status": "applied",
                "replayed": False,
                "result": {},
                "unexpected": True,
            }
        ).encode(),
    ],
)
def test_malformed_helper_output_is_rejected(tmp_path: Path, output: bytes) -> None:
    device = Device("pump-1", "west", "host")
    result = DeviceDispatcher(_config(tmp_path, device), run_command=RecordingRunner(output)).dispatch(
        _envelope()
    )
    assert not result.ok
    assert not result.retryable
    assert result.summary == "device returned an invalid response"


def test_oversized_output_is_rejected_before_json_parsing(tmp_path: Path) -> None:
    device = Device("pump-1", "west", "host")
    result = DeviceDispatcher(
        _config(tmp_path, device),
        run_command=RecordingRunner(b"x" * 17),
        max_output_bytes=16,
    ).dispatch(_envelope())
    assert not result.ok
    assert result.summary == "device response exceeded the output limit"


class TunnelProcess:
    def __init__(self) -> None:
        self.running = True
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return None if self.running else 0

    def terminate(self) -> None:
        self.terminated = True
        self.running = False

    def kill(self) -> None:
        self.killed = True
        self.running = False

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.running = False
        return 0


def test_spacebridge_uses_supervised_official_forward_and_always_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = Device(
        "pump-1",
        "west",
        "link999999",
        transport="spacebridge",
        metadata={"port": 22, "host_key_alias": "pump-1"},
    )
    runner = RecordingRunner(_response())
    tunnel = TunnelProcess()
    tunnel_calls: list[tuple[list[str], dict[str, Any]]] = []

    def start_tunnel(argv: list[str], **kwargs: Any) -> TunnelProcess:
        tunnel_calls.append((argv, kwargs))
        return tunnel

    monkeypatch.setattr("telegram_controller.ssh_dispatch._available_local_port", lambda: 45678)
    dispatcher = DeviceDispatcher(
        _config(tmp_path, device, spacebridge=True),
        run_command=runner,
        start_tunnel=start_tunnel,
        connection_probe=lambda host, port, timeout: (host, port, timeout) == ("127.0.0.1", 45678, 0.2),
    )

    result = dispatcher.dispatch(_envelope())

    assert result.ok
    outer_argv, outer_options = tunnel_calls[0]
    assert "-N" in outer_argv
    assert "ExitOnForwardFailure=yes" in outer_argv
    assert "127.0.0.1:45678:link999999:22" in outer_argv
    assert "htunnel@tunnel.hologram.io" == outer_argv[-1]
    assert str(tmp_path / "spacebridge-key") in outer_argv
    assert "StrictHostKeyChecking=yes" in outer_argv
    assert outer_options["shell"] is False
    inner_argv, inner_options = runner.calls[0]
    assert inner_argv[-1] == "ryne@127.0.0.1"
    assert "HostKeyAlias=pump-1" in inner_argv
    assert inner_options["shell"] is False
    assert tunnel.terminated


def test_spacebridge_cleanup_runs_when_inner_ssh_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = Device("pump-1", "west", "link42", transport="spacebridge")
    tunnel = TunnelProcess()

    def timed_out(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        del kwargs
        raise subprocess.TimeoutExpired(argv, 19)

    monkeypatch.setattr("telegram_controller.ssh_dispatch._available_local_port", lambda: 45679)
    dispatcher = DeviceDispatcher(
        _config(tmp_path, device, spacebridge=True),
        run_command=timed_out,
        start_tunnel=lambda argv, **kwargs: tunnel,
        connection_probe=lambda host, port, timeout: True,
    )

    result = dispatcher.dispatch(_envelope())

    assert not result.ok
    assert result.retryable
    assert tunnel.terminated
