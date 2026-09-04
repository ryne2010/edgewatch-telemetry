from __future__ import annotations

import json
import socket
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import yaml

from agent.lorawan.config import DeviceRegistry, IdentityConfigError
from agent.lorawan.maintenance import MaintenanceWakeCoordinator, WakeRequestError
from agent.lorawan.store import GatewayStore, StoreConflictError
from gateway_runtime.artifact_cache import ArtifactCacheError, RetryableArtifactCacheError

from .config import ControllerConfig
from .models import Device, DispatchEnvelope, DispatchResult


MAX_OUTPUT_BYTES = 64 * 1024
_DEFAULT_DEVICE_PORT = 22
_LOCAL_HELPER = "/usr/local/libexec/edgewatch-device-control-local"


class _TunnelProcess(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


class _ArtifactCache(Protocol):
    def ensure(self, payload: Mapping[str, Any]) -> Path: ...


RunCommand = Callable[..., Any]
StartTunnel = Callable[..., _TunnelProcess]
ConnectionProbe = Callable[[str, int, float], bool]


class DeviceDispatcher:
    """Deliver typed control envelopes through a pinned, forced-command SSH key."""

    def __init__(
        self,
        config: ControllerConfig,
        *,
        run_command: RunCommand = subprocess.run,
        start_tunnel: StartTunnel = subprocess.Popen,
        connection_probe: ConnectionProbe | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        max_output_bytes: int = MAX_OUTPUT_BYTES,
        artifact_cache: _ArtifactCache | None = None,
    ) -> None:
        self.config = config
        self.run_command = run_command
        self.start_tunnel = start_tunnel
        self.connection_probe = connection_probe or _connection_probe
        self.sleeper = sleeper
        self.monotonic = monotonic
        self.max_output_bytes = max_output_bytes
        self.artifact_cache = artifact_cache
        self._maintenance: MaintenanceWakeCoordinator | None = None
        self._maintenance_store: GatewayStore | None = None
        if config.maintenance is not None:
            try:
                registry = DeviceRegistry.from_mapping(
                    yaml.safe_load(config.maintenance.registry_file.read_text(encoding="utf-8"))
                )
            except (OSError, UnicodeError, yaml.YAMLError, IdentityConfigError) as exc:
                raise ValueError("maintenance registry could not be loaded") from exc
            self._maintenance_store = GatewayStore(config.maintenance.gateway_store_path)
            self._maintenance = MaintenanceWakeCoordinator(
                registry,
                self._maintenance_store,
                lambda _identity, _payload, _now: False,
                worker_id="telegram-controller",
            )

    def dispatch(self, envelope: DispatchEnvelope) -> DispatchResult:
        device = self.config.devices.get(envelope.device_id)
        if device is None or not device.enabled:
            return DispatchResult(False, "device is unknown or disabled", retryable=False)
        try:
            request = _encode_envelope(envelope)
        except (TypeError, ValueError):
            return DispatchResult(False, "command envelope is invalid", retryable=False)

        if device.transport == "maintenance_via_lora" and envelope.type in {
            "ota_stage",
            "ota_canary",
        }:
            manifest = envelope.args.get("manifest")
            if not isinstance(manifest, Mapping):
                return DispatchResult(False, "OTA command manifest is invalid", retryable=False)
            if self.artifact_cache is None:
                return DispatchResult(False, "gateway OTA cache is unavailable", retryable=True)
            try:
                self.artifact_cache.ensure(manifest)
            except RetryableArtifactCacheError:
                return DispatchResult(False, "gateway OTA cache is not ready", retryable=True)
            except ArtifactCacheError:
                return DispatchResult(False, "gateway rejected the OTA artifact", retryable=False)

        if device.transport == "direct":
            return self._run_device_ssh(device, envelope, request)
        if device.transport == "spacebridge":
            return self._run_spacebridge(device, envelope, request)
        if device.transport == "local":
            return self._run_local(envelope, request)
        if device.transport == "maintenance_via_lora":
            return self._run_maintenance(device, envelope, request)
        return DispatchResult(False, "device transport is unsupported", retryable=False)

    def _run_local(self, envelope: DispatchEnvelope, request: bytes) -> DispatchResult:
        argv = [
            "/usr/bin/sudo",
            "-n",
            _LOCAL_HELPER,
            "--device-id",
            envelope.device_id,
            "--ssh-stdin",
        ]
        return self._execute(argv, request, envelope)

    def _run_maintenance(self, device: Device, envelope: DispatchEnvelope, request: bytes) -> DispatchResult:
        coordinator = self._maintenance
        store = self._maintenance_store
        maintenance_config = self.config.maintenance
        if coordinator is None or store is None or maintenance_config is None:
            return DispatchResult(False, "maintenance transport is not configured", retryable=False)
        wake = store.get_wake(envelope.command_id)
        if wake is None:
            try:
                expires_at = int(
                    datetime.fromisoformat(envelope.expires_at.replace("Z", "+00:00")).timestamp()
                )
                wake = coordinator.request_wake(
                    envelope.command_id,
                    envelope.device_id,
                    expires_at=expires_at,
                    readiness_timeout_s=maintenance_config.readiness_timeout_s,
                )
            except StoreConflictError:
                return DispatchResult(
                    False,
                    "maintenance wake queued behind an active request",
                    retryable=True,
                    details={"status": "accepted", "wake_state": "queued"},
                )
            except (ValueError, WakeRequestError):
                return DispatchResult(False, "maintenance wake request is invalid", retryable=False)
        if wake.state == "ready":
            return self._run_device_ssh(device, envelope, request)
        if wake.state in {"expired", "timed_out", "failed"}:
            return DispatchResult(
                False,
                "maintenance wake did not become ready",
                retryable=False,
                details={"wake_state": wake.state},
            )
        return DispatchResult(
            False,
            "maintenance wake accepted and pending a satellite receive window",
            retryable=True,
            details={"status": "accepted", "wake_state": wake.state},
        )

    def _run_device_ssh(
        self,
        device: Device,
        envelope: DispatchEnvelope,
        request: bytes,
        *,
        host: str | None = None,
        port: int | None = None,
    ) -> DispatchResult:
        target_port = port if port is not None else _metadata_port(device.metadata)
        alias = _host_key_alias(device)
        argv = self._base_ssh_argv(self.config.ssh.private_key_file)
        argv.extend(
            [
                "-p",
                str(target_port),
                "-o",
                f"HostKeyAlias={alias}",
                f"{self.config.ssh.username}@{host or device.host}",
            ]
        )
        return self._execute(argv, request, envelope)

    def _run_spacebridge(self, device: Device, envelope: DispatchEnvelope, request: bytes) -> DispatchResult:
        identity = self.config.ssh.spacebridge_identity_file
        if identity is None:
            return DispatchResult(False, "Spacebridge identity is not configured", retryable=False)

        local_port = _available_local_port()
        device_port = _metadata_port(device.metadata)
        tunnel_argv = self._base_ssh_argv(identity)
        tunnel_argv.extend(
            [
                "-N",
                "-o",
                "ExitOnForwardFailure=yes",
                "-p",
                str(self.config.ssh.spacebridge_port),
                "-L",
                f"127.0.0.1:{local_port}:{device.host}:{device_port}",
                f"{self.config.ssh.spacebridge_user}@{self.config.ssh.spacebridge_host}",
            ]
        )
        tunnel: _TunnelProcess | None = None
        try:
            tunnel = self.start_tunnel(
                tunnel_argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
            if not self._wait_for_tunnel(tunnel, local_port):
                return DispatchResult(False, "Spacebridge tunnel could not be established", retryable=True)
            return self._run_device_ssh(
                device,
                envelope,
                request,
                host="127.0.0.1",
                port=local_port,
            )
        except (OSError, subprocess.SubprocessError):
            return DispatchResult(False, "Spacebridge tunnel could not be started", retryable=True)
        finally:
            if tunnel is not None:
                _stop_tunnel(tunnel)

    def _base_ssh_argv(self, identity: Path) -> list[str]:
        return [
            "ssh",
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={self.config.ssh.known_hosts_file}",
            "-o",
            f"ConnectTimeout={self.config.ssh.connect_timeout_s}",
            "-i",
            str(identity),
        ]

    def _execute(self, argv: Sequence[str], request: bytes, envelope: DispatchEnvelope) -> DispatchResult:
        try:
            completed = self.run_command(
                list(argv),
                input=request,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.config.ssh.command_timeout_s,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return DispatchResult(False, "device command timed out", retryable=True)
        except (OSError, subprocess.SubprocessError):
            return DispatchResult(False, "SSH dispatch failed", retryable=True)

        output = completed.stdout or b""
        if isinstance(output, str):
            output = output.encode("utf-8", errors="replace")
        if len(output) > self.max_output_bytes:
            return DispatchResult(False, "device response exceeded the output limit", retryable=False)
        parsed = _parse_response(output, envelope)
        if parsed is not None and parsed[0] == "rejected":
            code = parsed[2]
            return DispatchResult(
                False,
                "device rejected command",
                retryable=code == "ota_retryable",
                details={"code": code},
            )
        if completed.returncode != 0:
            return DispatchResult(
                False,
                "SSH dispatch failed",
                retryable=completed.returncode == 255,
                details={"exit_code": completed.returncode},
            )
        if parsed is None:
            return DispatchResult(False, "device returned an invalid response", retryable=False)
        status, details, _code = parsed
        if status == "accepted":
            return DispatchResult(
                False,
                "command accepted and pending device completion",
                retryable=True,
                details={"status": status, **details},
            )
        return DispatchResult(
            status == "applied",
            "command applied" if status == "applied" else "device command failed",
            retryable=False,
            details={"status": status, **details},
        )

    def _wait_for_tunnel(self, tunnel: _TunnelProcess, port: int) -> bool:
        deadline = self.monotonic() + self.config.ssh.connect_timeout_s
        while self.monotonic() < deadline:
            if tunnel.poll() is not None:
                return False
            if self.connection_probe("127.0.0.1", port, 0.2):
                return True
            self.sleeper(0.05)
        return False


def _encode_envelope(envelope: DispatchEnvelope) -> bytes:
    payload = {
        "version": envelope.version,
        "command_id": envelope.command_id,
        "device_id": envelope.device_id,
        "issued_at": envelope.issued_at,
        "expires_at": envelope.expires_at,
        "type": envelope.type,
        "args": dict(envelope.args),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _parse_response(
    raw: bytes, envelope: DispatchEnvelope
) -> tuple[str, Mapping[str, Any], str | None] | None:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    common = {
        "version": envelope.version,
        "command_id": envelope.command_id,
        "device_id": envelope.device_id,
    }
    if any(value.get(key) != expected for key, expected in common.items()):
        return None
    status = value.get("status")
    if status in {"accepted", "applied", "failed"}:
        if set(value) != {*common, "status", "replayed", "result"}:
            return None
        if not isinstance(value.get("replayed"), bool) or not isinstance(value.get("result"), dict):
            return None
        return status, {"replayed": value["replayed"], "result": value["result"]}, None
    if status == "rejected":
        if set(value) != {*common, "status", "error"}:
            return None
        error = value.get("error")
        if not isinstance(error, dict) or set(error) != {"code", "message"}:
            return None
        if not isinstance(error.get("code"), str) or not isinstance(error.get("message"), str):
            return None
        return status, {}, error["code"]
    return None


def _metadata_port(metadata: Mapping[str, Any]) -> int:
    value = metadata.get("port", _DEFAULT_DEVICE_PORT)
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 65535:
        return value
    return _DEFAULT_DEVICE_PORT


def _host_key_alias(device: Device) -> str:
    value = device.metadata.get("host_key_alias")
    return value if isinstance(value, str) and value else device.device_id


def _available_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _connection_probe(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _stop_tunnel(tunnel: _TunnelProcess) -> None:
    if tunnel.poll() is not None:
        return
    try:
        tunnel.terminate()
        try:
            tunnel.wait(timeout=2)
        except subprocess.TimeoutExpired:
            tunnel.kill()
            try:
                tunnel.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
    except OSError:
        # The process may exit between poll and the cleanup signal.
        pass
