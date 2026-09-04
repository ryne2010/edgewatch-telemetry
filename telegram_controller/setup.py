from __future__ import annotations

import json
import os
import pwd
import re
import secrets
import shlex
import sqlite3
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import yaml

from .config import ConfigError, load_config
from .store import ControllerStore


class SetupError(RuntimeError):
    pass


class SetupTelegramClient(Protocol):
    def get_me(self) -> dict[str, Any]: ...

    def get_updates(self, *, offset: int | None, poll_timeout_s: int) -> list[dict[str, Any]]: ...

    def send_message(self, chat_id: str, text: str, topic_id: str | None = None) -> str: ...


RunCommand = Callable[..., Any]


@dataclass(frozen=True)
class Registration:
    update_id: int
    chat_id: str
    user_id: str
    topic_id: str | None
    bot_username: str


@dataclass(frozen=True)
class SetupPaths:
    config_path: Path
    state_dir: Path
    source_token_file: Path
    key_file: Path
    known_hosts_file: Path

    @property
    def installed_token_file(self) -> Path:
        return self.config_path.parent / "control_bot_token"

    @property
    def database_path(self) -> Path:
        return self.state_dir / "controller.sqlite"


@dataclass(frozen=True)
class SetupResult:
    config_path: Path
    database_path: Path
    public_key: str
    key_fingerprint: str
    chat_id: str
    admin_user_id: str
    gateway_device_id: str


def default_service_user() -> str:
    return "edgewatch-controller"


def ensure_service_user(
    username: str,
    *,
    state_dir: Path,
    run_command: RunCommand = subprocess.run,
) -> None:
    _assert_scoped_directory(state_dir)
    try:
        pwd.getpwnam(username)
        return
    except KeyError:
        pass
    if username != "edgewatch-controller" or os.geteuid() != 0:
        raise SetupError("controller service user does not exist")
    try:
        completed = run_command(
            [
                "/usr/sbin/useradd",
                "--system",
                "--user-group",
                "--home-dir",
                str(state_dir),
                "--create-home",
                "--shell",
                "/usr/sbin/nologin",
                username,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SetupError("controller service account could not be created") from exc
    if completed.returncode != 0:
        raise SetupError("controller service account could not be created")


def read_control_bot_token(path: Path) -> str:
    """Read a dedicated control-bot token without accepting a symlink or loose mode."""

    descriptor: int | None = None
    try:
        path_stat = path.lstat()
        if not stat.S_ISREG(path_stat.st_mode):
            raise SetupError("control-bot token file must be a regular file")
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode) or (file_stat.st_dev, file_stat.st_ino) != (
            path_stat.st_dev,
            path_stat.st_ino,
        ):
            raise SetupError("control-bot token file must be a regular file")
        if stat.S_IMODE(file_stat.st_mode) != 0o600:
            raise SetupError("control-bot token file permissions must be 0600")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            raw = handle.read(4097)
        if len(raw) > 4096:
            raise SetupError("control-bot token file is empty or malformed")
        token = raw.decode("utf-8", errors="strict").strip()
    except SetupError:
        raise
    except (OSError, UnicodeError) as exc:
        raise SetupError("control-bot token file must be readable UTF-8") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not token or any(character.isspace() for character in token):
        raise SetupError("control-bot token file is empty or malformed")
    return token


def discover_private_group_registration(
    client: SetupTelegramClient,
    *,
    timeout_s: int = 300,
    poll_timeout_s: int = 10,
    monotonic: Callable[[], float] = time.monotonic,
    ready: Callable[[str], None] | None = None,
) -> Registration:
    """Discover one fresh `/register` from a non-public Telegram group."""

    if timeout_s <= 0 or poll_timeout_s <= 0:
        raise SetupError("registration timeouts must be positive")
    identity = client.get_me()
    username = identity.get("username")
    bot_id = identity.get("id")
    if (
        not isinstance(username, str)
        or re.fullmatch(r"[A-Za-z0-9_]{5,32}", username) is None
        or not isinstance(bot_id, int)
        or isinstance(bot_id, bool)
        or identity.get("is_bot") is not True
    ):
        raise SetupError("control bot identity is invalid")

    offset: int | None = None
    for _ in range(1_000):
        pending = client.get_updates(offset=offset, poll_timeout_s=0)
        next_offset = _next_update_offset(pending)
        if next_offset is not None:
            offset = next_offset if offset is None else max(offset, next_offset)
        if not pending:
            break
    else:
        raise SetupError("could not clear pending control-bot updates before registration")
    if ready is not None:
        ready(username)
    deadline = monotonic() + timeout_s
    while True:
        current = monotonic()
        if current >= deadline:
            break
        remaining = max(1, int(deadline - current))
        updates = client.get_updates(
            offset=offset,
            poll_timeout_s=min(poll_timeout_s, remaining),
        )
        next_offset = _next_update_offset(updates)
        if next_offset is not None:
            offset = next_offset if offset is None else max(offset, next_offset)
        for update in updates:
            registration = _registration_from_update(update, username=username, bot_id=bot_id)
            if registration is not None:
                return registration
    raise SetupError("timed out waiting for a private-group /register command")


def prepare_controller(
    paths: SetupPaths,
    registration: Registration,
    *,
    token: str,
    service_user: str,
    ssh_username: str = "ryne",
    gateway_device_id: str | None = None,
    gateway_state_dir: Path = Path("/var/lib/edgewatch-gateway"),
    force: bool = False,
    run_command: RunCommand = subprocess.run,
) -> SetupResult:
    """Create the protected controller config, key, known-hosts file, and state DB."""

    _validate_registration(registration)
    _validate_setup_paths(paths)
    owner = _resolve_user(service_user)
    root_owned_setup = os.geteuid() == 0
    config_owner = (0, owner[1]) if root_owned_setup else owner
    config_dir_mode = 0o750 if root_owned_setup else 0o700
    config_file_mode = 0o640 if root_owned_setup else 0o600
    _ensure_directory(paths.config_path.parent, mode=config_dir_mode, owner=config_owner)
    _ensure_directory(paths.state_dir, mode=0o700, owner=owner)
    if root_owned_setup:
        _ensure_directory(gateway_state_dir, mode=0o700, owner=owner)
    if paths.config_path.exists() and not force:
        raise SetupError("controller configuration already exists; use --force to replace it")

    installed_token = paths.installed_token_file
    if paths.source_token_file.resolve() != installed_token.resolve():
        if installed_token.exists() and not force:
            existing = read_control_bot_token(installed_token)
            if existing != token:
                raise SetupError("installed control-bot token already exists; use --force to replace it")
            _set_owner_and_mode(installed_token, mode=0o600, owner=owner)
        else:
            _atomic_write(installed_token, f"{token}\n".encode(), mode=0o600, owner=owner)
    else:
        _set_owner_and_mode(installed_token, mode=0o600, owner=owner)

    public_key, fingerprint = _ensure_ed25519_key(paths.key_file, owner=owner, run_command=run_command)
    if not paths.known_hosts_file.exists():
        _atomic_write(
            paths.known_hosts_file,
            b"",
            mode=config_file_mode,
            owner=config_owner,
        )
    else:
        _require_regular_file(paths.known_hosts_file, "known-hosts file")
        _set_owner_and_mode(
            paths.known_hosts_file,
            mode=config_file_mode,
            owner=config_owner,
        )

    gateway_device_id = _safe_device_id(gateway_device_id or os.uname().nodename)
    gateway_fleet_id = "field-gateway"
    gateway_fleet: dict[str, Any] = {
        "devices": [gateway_device_id],
        "canaries": [gateway_device_id],
    }
    if registration.topic_id is not None:
        gateway_fleet["topic_id"] = registration.topic_id
    config_payload: dict[str, Any] = {
        "telegram": {
            "token_file": str(installed_token),
            "poll_timeout_s": 30,
            "request_timeout_s": 40,
        },
        "storage": {"database_path": str(paths.database_path)},
        "ssh": {
            "device_key_file": str(paths.key_file),
            "known_hosts_file": str(paths.known_hosts_file),
            "username": ssh_username,
            "connect_timeout_s": 10,
            "command_timeout_s": 90,
        },
        "authorization": {
            "allowed_chats": [registration.chat_id],
            "users": {
                registration.user_id: {
                    "role": "admin",
                    "fleets": [],
                }
            },
        },
        "devices": {
            gateway_device_id: {
                "fleet": gateway_fleet_id,
                "host": "localhost",
                "transport": "local",
                "capabilities": [
                    "status",
                    "health",
                    "network",
                    "power",
                    "queue",
                    "version",
                    "sample_now",
                    "sync_now",
                    "set_operation_mode",
                    "set_power_mode",
                    "deep_sleep",
                    "alerts_mute",
                    "alerts_unmute",
                    "agent_restart",
                    "reboot",
                    "shutdown",
                    "ota",
                ],
            }
        },
        "fleets": {gateway_fleet_id: gateway_fleet},
        "controller": {
            "confirmation_ttl_s": 120,
            "command_ttl_s": 7200,
            "fleet_dispatch_concurrency": 4,
            "accepted_poll_interval_s": 60,
            "shutdown_enabled": False,
        },
    }
    config_bytes = yaml.safe_dump(config_payload, sort_keys=False).encode("utf-8")
    _atomic_write(
        paths.config_path,
        config_bytes,
        mode=config_file_mode,
        owner=config_owner,
    )

    try:
        loaded = load_config(paths.config_path)
        store = ControllerStore(loaded.database_path)
        store.mark_update_processed(registration.update_id)
    except (ConfigError, OSError, sqlite3.Error) as exc:
        raise SetupError("generated controller configuration failed its smoke test") from exc
    _set_owner_and_mode(paths.database_path, mode=0o600, owner=owner)
    return SetupResult(
        config_path=paths.config_path,
        database_path=paths.database_path,
        public_key=public_key,
        key_fingerprint=fingerprint,
        chat_id=registration.chat_id,
        admin_user_id=registration.user_id,
        gateway_device_id=gateway_device_id,
    )


def install_local_gateway_helper(
    *,
    service_user: str,
    gateway_device_id: str,
    helper_path: Path = Path("/usr/local/libexec/edgewatch-device-control-local"),
    sudoers_path: Path = Path("/etc/sudoers.d/edgewatch-controller-local"),
    enable_lte_power_systemd: bool = False,
    run_command: RunCommand = subprocess.run,
) -> None:
    """Install one fixed local-control wrapper and an exact-argument sudo rule."""

    if os.geteuid() != 0:
        raise SetupError("local gateway helper installation must run as root")
    device_id = _safe_device_id(gateway_device_id)
    if re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", service_user) is None:
        raise SetupError("controller service user is invalid")
    helper_path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    wrapper = render_local_gateway_wrapper(device_id)
    _atomic_write(helper_path, wrapper.encode("utf-8"), mode=0o755, owner=(0, 0))

    sudoers_path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    sudoers = render_local_gateway_sudoers(
        service_user=service_user,
        gateway_device_id=device_id,
        helper_path=helper_path,
        enable_lte_power_systemd=enable_lte_power_systemd,
    ).encode("utf-8")
    temporary = sudoers_path.parent / f".{sudoers_path.name}.{secrets.token_hex(8)}.tmp"
    try:
        _atomic_write(temporary, sudoers, mode=0o440, owner=(0, 0))
        completed = run_command(
            ["/usr/sbin/visudo", "-cf", str(temporary)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            raise SetupError("local gateway sudo policy failed validation")
        os.replace(temporary, sudoers_path)
        _set_owner_and_mode(sudoers_path, mode=0o440, owner=(0, 0))
    except SetupError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise SetupError("local gateway sudo policy installation failed") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def smoke_test_local_gateway_control(
    *,
    service_user: str,
    gateway_device_id: str,
    helper_path: Path = Path("/usr/local/libexec/edgewatch-device-control-local"),
    run_command: RunCommand = subprocess.run,
) -> None:
    """Exercise the exact service-user sudo path with one typed status envelope."""

    if os.geteuid() != 0:
        raise SetupError("local gateway control smoke test must run as root")
    device_id = _safe_device_id(gateway_device_id)
    now = datetime.now(tz=UTC)
    payload = {
        "version": 1,
        "command_id": f"setup-smoke-{uuid.uuid4()}",
        "device_id": device_id,
        "issued_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=2)).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "type": "status",
        "args": {},
    }
    request = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    try:
        completed = run_command(
            [
                "/usr/bin/sudo",
                "-u",
                service_user,
                "--",
                "/usr/bin/sudo",
                "-n",
                str(helper_path),
                "--device-id",
                device_id,
                "--ssh-stdin",
            ],
            input=request,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SetupError("local gateway control smoke test failed") from exc
    if completed.returncode != 0:
        raise SetupError("local gateway control smoke test failed")
    raw = completed.stdout if isinstance(completed.stdout, bytes) else str(completed.stdout).encode()
    if len(raw) > 64 * 1024:
        raise SetupError("local gateway control smoke test returned an invalid response")
    try:
        response = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SetupError("local gateway control smoke test returned an invalid response") from exc
    if (
        not isinstance(response, dict)
        or response.get("version") != 1
        or response.get("command_id") != payload["command_id"]
        or response.get("device_id") != device_id
        or response.get("status") != "applied"
    ):
        raise SetupError("local gateway control smoke test returned an invalid response")


def render_local_gateway_wrapper(gateway_device_id: str) -> str:
    device_id = _safe_device_id(gateway_device_id)
    return f"""#!/bin/sh
set -eu
if [ "$#" -ne 3 ] || [ "$1" != "--device-id" ] || [ "$2" != {shlex.quote(device_id)} ] || [ "$3" != "--ssh-stdin" ]; then
    exit 64
fi
exec /opt/edgewatch/app/.venv/bin/python /opt/edgewatch/current/scripts/edgewatch_device_control.py --device-id {shlex.quote(device_id)} --runtime-profile gateway --ssh-stdin
"""


def render_local_gateway_sudoers(
    *,
    service_user: str,
    gateway_device_id: str,
    helper_path: Path = Path("/usr/local/libexec/edgewatch-device-control-local"),
    enable_lte_power_systemd: bool = False,
) -> str:
    device_id = _safe_device_id(gateway_device_id)
    if re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", service_user) is None:
        raise SetupError("controller service user is invalid")
    allowed_commands = [
        f"{helper_path} --device-id {device_id} --ssh-stdin",
    ]
    if enable_lte_power_systemd:
        allowed_commands.extend(
            [
                "/usr/bin/systemctl start edgewatch-lte-power-on.service",
                "/usr/bin/systemctl start edgewatch-lte-power-off.service",
            ]
        )
    return f"{service_user} ALL=(root) NOPASSWD: {', '.join(allowed_commands)}\n"


def render_systemd_unit(
    *,
    service_user: str,
    repository_root: Path,
    config_path: Path,
    state_dir: Path,
    python_executable: Path | None = None,
) -> str:
    values = [service_user, repository_root, config_path, state_dir]
    executable = Path(sys.executable) if python_executable is None else python_executable
    values.append(executable)
    if any(any(character.isspace() or ord(character) < 32 for character in str(value)) for value in values):
        raise SetupError("systemd setup paths and service user must not contain whitespace")
    return f"""[Unit]
Description=EdgeWatch Telegram Fleet Controller
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=10

[Service]
Type=simple
User={service_user}
Group={service_user}
WorkingDirectory={repository_root}
ExecStart={executable} -m scripts.telegram_fleet_controller --config {config_path}
Restart=always
RestartSec=5
TimeoutStopSec=30
UMask=0077
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-/etc/edgewatch-controller/gateway-power.env
NoNewPrivileges=false
PrivateDevices=true
PrivateTmp=true
ProtectClock=true
ProtectControlGroups=true
ProtectHome=true
ProtectKernelLogs=true
ProtectKernelModules=true
ProtectKernelTunables=true
ProtectSystem=strict
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
RestrictRealtime=true
LockPersonality=true
ReadWritePaths={state_dir} /var/lib/edgewatch /var/lib/edgewatch-gateway

[Install]
WantedBy=multi-user.target
"""


def install_systemd_service(
    unit_path: Path,
    unit_text: str,
    *,
    run_command: RunCommand = subprocess.run,
) -> None:
    if os.geteuid() != 0:
        raise SetupError("service installation must run as root")
    _atomic_write(unit_path, unit_text.encode("utf-8"), mode=0o644, owner=(0, 0))
    for argv in (
        ["/usr/bin/systemctl", "daemon-reload"],
        ["/usr/bin/systemctl", "enable", "--now", unit_path.name],
        ["/usr/bin/systemctl", "is-active", "--quiet", unit_path.name],
    ):
        try:
            completed = run_command(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SetupError("controller service installation failed") from exc
        if completed.returncode != 0:
            raise SetupError("controller service installation failed")


def _registration_from_update(update: dict[str, Any], *, username: str, bot_id: int) -> Registration | None:
    update_id = update.get("update_id")
    message = update.get("message")
    if not isinstance(update_id, int) or isinstance(update_id, bool) or not isinstance(message, dict):
        return None
    text = message.get("text")
    chat = message.get("chat")
    sender = message.get("from")
    if not isinstance(text, str) or not isinstance(chat, dict) or not isinstance(sender, dict):
        return None
    match = re.fullmatch(r"/register(?:@([A-Za-z0-9_]{5,32}))?", text.strip())
    if match is None or (match.group(1) is not None and match.group(1).lower() != username.lower()):
        return None
    chat_id = chat.get("id")
    user_id = sender.get("id")
    if (
        chat.get("type") not in {"group", "supergroup"}
        or chat.get("username") is not None
        or not isinstance(chat_id, int)
        or isinstance(chat_id, bool)
        or chat_id >= 0
        or not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or user_id <= 0
        or sender.get("is_bot") is True
        or user_id == bot_id
    ):
        return None
    topic_raw = message.get("message_thread_id")
    topic_id = str(topic_raw) if isinstance(topic_raw, int) and not isinstance(topic_raw, bool) else None
    return Registration(update_id, str(chat_id), str(user_id), topic_id, username)


def gateway_uses_systemd_lte_power(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        if not path.is_file():
            raise SetupError("gateway power configuration must be a regular file")
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise SetupError("gateway power configuration could not be read") from exc
    mode: str | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, raw_value = stripped.split("=", 1)
        if name.strip() == "EDGEWATCH_GATEWAY_LTE_POWER_MODE":
            mode = raw_value.strip().strip("\"'").lower()
    return mode == "systemd"


def _next_update_offset(updates: Sequence[dict[str, Any]]) -> int | None:
    ids = [
        value
        for update in updates
        if isinstance((value := update.get("update_id")), int) and not isinstance(value, bool)
    ]
    return None if not ids else max(ids) + 1


def _safe_device_id(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value) is None:
        raise SetupError("gateway device ID must contain only letters, digits, dot, dash, or underscore")
    return value


def _validate_registration(registration: Registration) -> None:
    try:
        chat_id = int(registration.chat_id)
        user_id = int(registration.user_id)
        topic_id = None if registration.topic_id is None else int(registration.topic_id)
    except ValueError as exc:
        raise SetupError("Telegram registration IDs are invalid") from exc
    if (
        registration.update_id < 0
        or chat_id >= 0
        or user_id <= 0
        or topic_id is not None
        and topic_id <= 0
        or re.fullmatch(r"[A-Za-z0-9_]{5,32}", registration.bot_username) is None
    ):
        raise SetupError("Telegram registration IDs are invalid")


def _resolve_user(username: str) -> tuple[int, int]:
    try:
        entry = pwd.getpwnam(username)
    except KeyError as exc:
        raise SetupError("controller service user does not exist") from exc
    return entry.pw_uid, entry.pw_gid


def _ensure_directory(path: Path, *, mode: int, owner: tuple[int, int]) -> None:
    _assert_scoped_directory(path)
    try:
        path.mkdir(parents=True, exist_ok=True, mode=mode)
        _set_owner_and_mode(path, mode=mode, owner=owner)
    except OSError as exc:
        raise SetupError("controller directory could not be secured") from exc


def _atomic_write(path: Path, data: bytes, *, mode: int, owner: tuple[int, int]) -> None:
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        os.fchmod(descriptor, mode)
        if os.geteuid() == 0:
            os.fchown(descriptor, *owner)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise SetupError("protected controller file could not be written") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _set_owner_and_mode(path: Path, *, mode: int, owner: tuple[int, int]) -> None:
    path.chmod(mode)
    if os.geteuid() == 0:
        os.chown(path, *owner)


def _ensure_ed25519_key(
    key_file: Path,
    *,
    owner: tuple[int, int],
    run_command: RunCommand,
) -> tuple[str, str]:
    public_file = Path(f"{key_file}.pub")
    if key_file.exists() != public_file.exists():
        raise SetupError("controller SSH keypair is incomplete")
    if key_file.exists():
        _require_regular_file(key_file, "controller SSH private key")
        _require_regular_file(public_file, "controller SSH public key")
    if not key_file.exists():
        temporary = key_file.parent / f".{key_file.name}.{secrets.token_hex(8)}"
        try:
            completed = run_command(
                [
                    "/usr/bin/ssh-keygen",
                    "-q",
                    "-t",
                    "ed25519",
                    "-N",
                    "",
                    "-C",
                    "edgewatch-controller",
                    "-f",
                    str(temporary),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
            )
            if completed.returncode != 0:
                raise SetupError("controller Ed25519 key generation failed")
            os.replace(temporary, key_file)
            os.replace(Path(f"{temporary}.pub"), public_file)
        except SetupError:
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            raise SetupError("controller Ed25519 key generation failed") from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
                Path(f"{temporary}.pub").unlink(missing_ok=True)
            except OSError:
                pass
    _set_owner_and_mode(key_file, mode=0o600, owner=owner)
    _set_owner_and_mode(public_file, mode=0o644, owner=owner)
    try:
        public_key = public_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise SetupError("controller SSH public key could not be read") from exc
    public_parts = public_key.split(maxsplit=2)
    if (
        "\n" in public_key
        or "\r" in public_key
        or len(public_parts) not in {2, 3}
        or public_parts[0] != "ssh-ed25519"
        or re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", public_parts[1]) is None
        or len(public_parts) == 3
        and (
            len(public_parts[2]) > 128
            or any(ord(character) < 32 or ord(character) > 126 for character in public_parts[2])
        )
    ):
        raise SetupError("controller SSH key is not Ed25519")
    try:
        derived = run_command(
            ["/usr/bin/ssh-keygen", "-y", "-f", str(key_file)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SetupError("controller SSH key validation failed") from exc
    if derived.returncode != 0:
        raise SetupError("controller SSH key validation failed")
    derived_text = (
        derived.stdout.decode("utf-8", errors="replace")
        if isinstance(derived.stdout, bytes)
        else str(derived.stdout)
    ).strip()
    derived_parts = derived_text.split(maxsplit=2)
    if "\n" in derived_text or "\r" in derived_text or derived_parts[:2] != public_parts[:2]:
        raise SetupError("controller SSH keypair does not match")
    try:
        completed = run_command(
            ["/usr/bin/ssh-keygen", "-l", "-E", "sha256", "-f", str(public_file)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SetupError("controller SSH fingerprint generation failed") from exc
    if completed.returncode != 0:
        raise SetupError("controller SSH fingerprint generation failed")
    try:
        output = (
            completed.stdout.decode("utf-8", errors="strict")
            if isinstance(completed.stdout, bytes)
            else str(completed.stdout)
        )
    except UnicodeDecodeError as exc:
        raise SetupError("controller SSH fingerprint generation failed") from exc
    parts = output.split()
    if len(parts) < 2 or not parts[1].startswith("SHA256:"):
        raise SetupError("controller SSH fingerprint generation failed")
    return public_key, parts[1]


def _require_regular_file(path: Path, description: str) -> None:
    try:
        file_stat = path.lstat()
    except OSError as exc:
        raise SetupError(f"{description} could not be inspected") from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise SetupError(f"{description} must be a regular file")


def _validate_setup_paths(paths: SetupPaths) -> None:
    config_dir = paths.config_path.parent.resolve()
    state_dir = paths.state_dir.resolve()
    _assert_scoped_directory(config_dir)
    _assert_scoped_directory(state_dir)
    if config_dir == state_dir or config_dir.is_relative_to(state_dir):
        raise SetupError("controller configuration must not be inside its writable state directory")
    if paths.key_file.parent.resolve() != config_dir:
        raise SetupError("controller SSH key must be stored beside the controller configuration")
    if paths.known_hosts_file.parent.resolve() != config_dir:
        raise SetupError("known-hosts file must be stored beside the controller configuration")
    if paths.database_path.parent.resolve() != state_dir:
        raise SetupError("controller database must be stored in the controller state directory")


def _assert_scoped_directory(path: Path) -> None:
    resolved = path.resolve()
    broad_paths = {
        Path("/"),
        Path("/etc"),
        Path("/opt"),
        Path("/tmp"),
        Path("/usr"),
        Path("/usr/local"),
        Path("/var"),
        Path("/var/lib"),
    }
    if resolved in broad_paths:
        raise SetupError("controller directory must be a dedicated scoped directory")
