from __future__ import annotations

import json
import os
import pwd
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import scripts.telegram_control_init as init_script
from telegram_controller.config import load_config
from telegram_controller.setup import (
    Registration,
    SetupError,
    SetupPaths,
    discover_private_group_registration,
    gateway_uses_systemd_lte_power,
    prepare_controller,
    read_control_bot_token,
    render_local_gateway_sudoers,
    render_local_gateway_wrapper,
    render_systemd_unit,
    smoke_test_local_gateway_control,
)
from telegram_controller.store import ControllerStore


class FakeTelegramClient:
    instances: list["FakeTelegramClient"] = []

    def __init__(self, token: str, **_kwargs: Any) -> None:
        self.token = token
        self.update_calls: list[tuple[int | None, int]] = []
        self.messages: list[tuple[str, str, str | None]] = []
        self._responses = [
            [{"update_id": 40, "message": {"text": "old"}}],
            [],
            [
                {
                    "update_id": 41,
                    "message": {
                        "text": "/register@edgewatch_control_bot",
                        "message_thread_id": 7,
                        "chat": {"id": -100123, "type": "supergroup", "title": "Control"},
                        "from": {"id": 456, "is_bot": False},
                    },
                }
            ],
        ]
        self.__class__.instances.append(self)

    def get_me(self) -> dict[str, Any]:
        return {"id": 999, "username": "edgewatch_control_bot", "is_bot": True}

    def get_updates(self, *, offset: int | None, poll_timeout_s: int) -> list[dict[str, Any]]:
        self.update_calls.append((offset, poll_timeout_s))
        return self._responses.pop(0)

    def send_message(self, chat_id: str, text: str, topic_id: str | None = None) -> str:
        self.messages.append((chat_id, text, topic_id))
        return "1"


def test_registration_discards_stale_updates_and_accepts_only_private_group() -> None:
    client = FakeTelegramClient("control-secret")
    ready: list[str] = []

    registration = discover_private_group_registration(client, ready=ready.append)

    assert registration.chat_id == "-100123"
    assert registration.user_id == "456"
    assert registration.topic_id == "7"
    assert ready == ["edgewatch_control_bot"]
    assert client.update_calls == [(None, 0), (41, 0), (41, 10)]


@pytest.mark.parametrize(
    "chat",
    [
        {"id": 123, "type": "private"},
        {"id": -100123, "type": "channel"},
        {"id": -100123, "type": "supergroup", "username": "public_control"},
    ],
)
def test_registration_ignores_non_private_group_sources(chat: dict[str, Any]) -> None:
    class RejectingClient(FakeTelegramClient):
        def __init__(self) -> None:
            super().__init__("secret")
            self._responses = [
                [],
                [
                    {
                        "update_id": 1,
                        "message": {
                            "text": "/register",
                            "chat": chat,
                            "from": {"id": 456, "is_bot": False},
                        },
                    }
                ],
                [],
            ]

    ticks = iter([0.0, 0.0, 2.0])
    with pytest.raises(SetupError, match="timed out"):
        discover_private_group_registration(
            RejectingClient(),
            timeout_s=1,
            monotonic=lambda: next(ticks),
        )


def test_token_file_requires_exact_mode_and_never_leaks_secret_or_path(tmp_path: Path) -> None:
    token_file = tmp_path / "control-token-secret-path"
    token_file.write_text("123456:never-print-this\n", encoding="utf-8")
    token_file.chmod(0o640)

    with pytest.raises(SetupError) as caught:
        read_control_bot_token(token_file)

    rendered = str(caught.value)
    assert "never-print-this" not in rendered
    assert str(token_file) not in rendered
    assert "0600" in rendered


def test_token_file_rejects_symlink_even_when_target_is_mode_0600(tmp_path: Path) -> None:
    target = tmp_path / "token-target"
    target.write_text("123456:never-follow-this\n", encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "token-link"
    link.symlink_to(target)

    with pytest.raises(SetupError, match="regular file"):
        read_control_bot_token(link)


@pytest.mark.skipif(not Path("/usr/bin/ssh-keygen").is_file(), reason="OpenSSH client is unavailable")
def test_guided_init_writes_strict_config_and_smoke_tests_bot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    FakeTelegramClient.instances.clear()
    monkeypatch.setattr(init_script, "TelegramClient", FakeTelegramClient)
    token_file = tmp_path / "input-control-token"
    token = "123456:dedicated-control-secret"
    token_file.write_text(f"{token}\n", encoding="utf-8")
    token_file.chmod(0o600)
    config_dir = tmp_path / "config"
    state_dir = tmp_path / "state"
    service_user = pwd.getpwuid(os.getuid()).pw_name

    result = init_script.main(
        [
            "--token-file",
            str(token_file),
            "--config",
            str(config_dir / "controller.yaml"),
            "--state-dir",
            str(state_dir),
            "--key-file",
            str(config_dir / "controller_device_ed25519"),
            "--known-hosts-file",
            str(config_dir / "known_hosts"),
            "--service-user",
            service_user,
            "--gateway-device-id",
            "gateway-001",
        ]
    )

    assert result == 0
    loaded = load_config(config_dir / "controller.yaml")
    assert loaded.allowed_chats == frozenset({"-100123"})
    assert loaded.principals["456"].role.name == "ADMIN"
    assert loaded.devices["gateway-001"].transport == "local"
    assert loaded.fleets["field-gateway"].topic_id == "7"
    assert loaded.command_ttl_s == 7200
    assert loaded.accepted_poll_interval_s == 60
    assert loaded.telegram.token_file != token_file
    assert loaded.telegram.token_file.read_text(encoding="utf-8").strip() == token
    expected_config_mode = 0o640 if os.geteuid() == 0 else 0o600
    assert stat.S_IMODE((config_dir / "controller.yaml").stat().st_mode) == expected_config_mode
    assert stat.S_IMODE(loaded.telegram.token_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(loaded.ssh.private_key_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
    assert ControllerStore(loaded.database_path).next_update_offset() == 42
    client = FakeTelegramClient.instances[-1]
    assert client.messages == [
        (
            "-100123",
            "✅ EdgeWatch control registration and configuration verified.",
            "7",
        )
    ]
    output = capsys.readouterr()
    assert token not in output.out + output.err
    assert "PRIVATE KEY" not in output.out
    assert "ssh-ed25519 " in output.out
    assert "Existing telemetry bot and channel settings were not changed." in output.out


def test_local_helper_and_sudoers_are_exact_and_never_grant_shell() -> None:
    wrapper = render_local_gateway_wrapper("gateway-001")
    base = render_local_gateway_sudoers(
        service_user="edgewatch-controller",
        gateway_device_id="gateway-001",
    )
    power = render_local_gateway_sudoers(
        service_user="edgewatch-controller",
        gateway_device_id="gateway-001",
        enable_lte_power_systemd=True,
    )

    assert "exec /opt/edgewatch/app/.venv/bin/python" in wrapper
    assert "/opt/edgewatch/current/scripts/edgewatch_device_control.py" in wrapper
    assert "--runtime-profile gateway --ssh-stdin" in wrapper
    assert '"$@"' not in wrapper
    assert "edgewatch-device-control-local --device-id gateway-001 --ssh-stdin" in base
    assert "systemctl" not in base
    assert "edgewatch-lte-power-on.service" in power
    assert "edgewatch-lte-power-off.service" in power
    assert " ALL=(root) NOPASSWD: " in power
    assert "*" not in power
    assert "/bin/sh" not in power


def test_local_control_smoke_uses_service_user_and_exact_sudo_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    @dataclass
    class Completed:
        returncode: int
        stdout: bytes

    def run_command(argv: list[str], **kwargs: Any) -> Completed:
        calls.append((argv, kwargs))
        request = json.loads(kwargs["input"].decode("ascii"))
        response = {
            "version": 1,
            "command_id": request["command_id"],
            "device_id": request["device_id"],
            "status": "applied",
        }
        return Completed(0, json.dumps(response).encode("utf-8"))

    monkeypatch.setattr("telegram_controller.setup.os.geteuid", lambda: 0)

    smoke_test_local_gateway_control(
        service_user="edgewatch-controller",
        gateway_device_id="gateway-001",
        run_command=run_command,
    )

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == [
        "/usr/bin/sudo",
        "-u",
        "edgewatch-controller",
        "--",
        "/usr/bin/sudo",
        "-n",
        "/usr/local/libexec/edgewatch-device-control-local",
        "--device-id",
        "gateway-001",
        "--ssh-stdin",
    ]
    assert kwargs["shell"] is False
    assert kwargs["stderr"] is not None
    envelope = json.loads(kwargs["input"].decode("ascii"))
    assert envelope["type"] == "status"
    assert envelope["device_id"] == "gateway-001"
    assert all(ord(character) < 128 for character in kwargs["input"].decode("ascii"))


def test_systemd_power_sudo_is_enabled_only_by_explicit_mode(tmp_path: Path) -> None:
    power_env = tmp_path / "gateway-power.env"
    assert gateway_uses_systemd_lte_power(power_env) is False
    power_env.write_text("EDGEWATCH_GATEWAY_LTE_POWER_MODE=observe\n", encoding="utf-8")
    assert gateway_uses_systemd_lte_power(power_env) is False
    power_env.write_text("EDGEWATCH_GATEWAY_LTE_POWER_MODE=systemd\n", encoding="utf-8")
    assert gateway_uses_systemd_lte_power(power_env) is True


def test_generated_unit_uses_stable_runtime_and_optional_power_environment(tmp_path: Path) -> None:
    unit = render_systemd_unit(
        service_user="edgewatch-controller",
        repository_root=Path("/opt/edgewatch/current"),
        config_path=Path("/etc/edgewatch-controller/controller.yaml"),
        state_dir=Path("/var/lib/edgewatch-controller"),
        python_executable=Path("/opt/edgewatch/app/.venv/bin/python"),
    )

    assert "User=edgewatch-controller" in unit
    assert "WorkingDirectory=/opt/edgewatch/current" in unit
    assert "EnvironmentFile=-/etc/edgewatch-controller/gateway-power.env" in unit
    assert "NoNewPrivileges=false" in unit
    assert (
        "ReadWritePaths=/var/lib/edgewatch-controller /var/lib/edgewatch /var/lib/edgewatch-gateway" in unit
    )
    assert " -m scripts.telegram_fleet_controller " in unit


def test_guided_init_preserves_stable_repository_symlink(tmp_path: Path) -> None:
    release = tmp_path / "releases" / "v1"
    release.mkdir(parents=True)
    current = tmp_path / "current"
    current.symlink_to(release)

    assert init_script._absolute_without_resolving(current) == current
    assert init_script._absolute_without_resolving(current) != release


@pytest.mark.skipif(not Path("/usr/bin/ssh-keygen").is_file(), reason="OpenSSH client is unavailable")
def test_root_setup_creates_and_chowns_gateway_state_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_user = pwd.getpwuid(os.getuid()).pw_name
    owner = (os.getuid(), os.getgid())
    source_token = tmp_path / "source-token"
    source_token.write_text("123456:dedicated-control-secret\n", encoding="utf-8")
    source_token.chmod(0o600)
    config_dir = tmp_path / "config"
    state_dir = tmp_path / "controller-state"
    gateway_state_dir = tmp_path / "gateway-state"
    chowns: list[tuple[Path, int, int]] = []
    monkeypatch.setattr("telegram_controller.setup.os.geteuid", lambda: 0)
    monkeypatch.setattr("telegram_controller.setup.os.fchown", lambda *_args: None)
    monkeypatch.setattr(
        "telegram_controller.setup.os.chown",
        lambda path, uid, gid: chowns.append((Path(path), uid, gid)),
    )

    prepare_controller(
        SetupPaths(
            config_path=config_dir / "controller.yaml",
            state_dir=state_dir,
            source_token_file=source_token,
            key_file=config_dir / "controller_device_ed25519",
            known_hosts_file=config_dir / "known_hosts",
        ),
        Registration(1, "-100123", "456", None, "edgewatch_control_bot"),
        token="123456:dedicated-control-secret",
        service_user=service_user,
        gateway_device_id="gateway-001",
        gateway_state_dir=gateway_state_dir,
    )

    assert gateway_state_dir.is_dir()
    assert stat.S_IMODE(gateway_state_dir.stat().st_mode) == 0o700
    assert (gateway_state_dir, *owner) in chowns
