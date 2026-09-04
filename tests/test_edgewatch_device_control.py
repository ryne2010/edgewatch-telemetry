from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import sys
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "edgewatch_device_control.py"
SPEC = importlib.util.spec_from_file_location("edgewatch_device_control", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


def _payload() -> bytes:
    now = datetime.now(timezone.utc)
    return json.dumps(
        {
            "version": 1,
            "command_id": "cmd-cli-1",
            "device_id": "device-1",
            "issued_at": (now - timedelta(seconds=1)).isoformat(),
            "expires_at": (now + timedelta(minutes=5)).isoformat(),
            "type": "sample_now",
            "args": {},
        }
    ).encode()


class _BinaryStdin:
    def __init__(self, payload: bytes) -> None:
        self.buffer = io.BytesIO(payload)


def test_ssh_stdin_cli_emits_json_and_replays(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("EDGEWATCH_LOCAL_CONTROL_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("EDGEWATCH_LOCAL_CONTROL_LEDGER_PATH", str(tmp_path / "ledger.sqlite"))
    monkeypatch.delenv("SSH_ORIGINAL_COMMAND", raising=False)

    monkeypatch.setattr(sys, "stdin", _BinaryStdin(_payload()))
    assert cli.main(["--device-id", "device-1", "--ssh-stdin"]) == 0
    first = json.loads(capsys.readouterr().out)
    monkeypatch.setattr(sys, "stdin", _BinaryStdin(_payload()))
    assert cli.main(["--device-id", "device-1", "--ssh-stdin"]) == 0
    second = json.loads(capsys.readouterr().out)

    assert first["status"] == "accepted"
    assert second["status"] == "accepted"
    assert first["replayed"] is False
    assert second["replayed"] is True


def test_cli_rejects_ssh_original_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "uname -a")
    monkeypatch.setattr(sys, "stdin", _BinaryStdin(_payload()))

    assert cli.main(["--device-id", "device-1", "--ssh-stdin"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["code"] == "original_command_rejected"


def test_authorized_keys_render_is_restrictive_and_fixed() -> None:
    rendered = cli.render_authorized_key(
        public_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest controller@example",
        helper_path="/opt/edgewatch/scripts/edgewatch_device_control.py",
        device_id="device-1",
        runtime_profile="camera-satellite",
    )

    assert rendered.startswith('restrict,command="sudo -n /opt/edgewatch/scripts/edgewatch_device_control.py')
    assert '--device-id device-1 --runtime-profile camera-satellite --ssh-stdin" ssh-ed25519' in rendered
    assert "no-pty" not in rendered  # OpenSSH's `restrict` includes PTY/forwarding restrictions.

    with pytest.raises(Exception, match="one line"):
        cli.render_authorized_key(
            public_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest\nssh-rsa injected",
            helper_path="/opt/edgewatch/scripts/edgewatch_device_control.py",
            device_id="device-1",
        )
    with pytest.raises(Exception, match="not supported"):
        cli.render_authorized_key(
            public_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest",
            helper_path="/opt/edgewatch/scripts/edgewatch_device_control.py",
            device_id="device-1",
            runtime_profile="camera-satellite --ssh-stdin;id",
        )


def test_runtime_profile_loads_only_allowlisted_values_from_fixed_trusted_files(
    tmp_path: Path,
) -> None:
    agent_env = tmp_path / "agent.env"
    camera_env = tmp_path / "camera.env"
    agent_env.write_text(
        "EDGEWATCH_OTA_GATEWAY_CACHE_URL=http://10.42.0.1:8091\n"
        "EDGEWATCH_ASSET_BUNDLE_APPLY_CMD='" + cli._CAMERA_ASSET_APPLY_CMD + "'\n"
        "EDGEWATCH_ENABLE_OTA_APPLY=false\n"
        "EDGEWATCH_POWER_STATE_PATH=/var/lib/edgewatch-camera-satellite/ota-power-state.json\n"
        "EDGEWATCH_OTA_RUNTIME_PROFILE=camera-satellite\n"
        "EDGEWATCH_CURRENT_SYMLINK=/opt/edgewatch/current\n"
        "EDGEWATCH_RELEASES_ROOT=/opt/edgewatch/releases\n"
        "RUNTIME_POWER_MODE=eco\n"
        "TELEGRAM_BOT_TOKEN_FILE=/secret/token\n",
        encoding="utf-8",
    )
    camera_env.write_text(
        "EDGEWATCH_MODEL_CURRENT_SYMLINK=/opt/edgewatch/models/current\n"
        "MEDIA_RTSP_CAM1_URL=rtsp://192.168.40.10/stream\n",
        encoding="utf-8",
    )
    agent_env.chmod(0o600)
    camera_env.chmod(0o640)
    environment = {
        "EDGEWATCH_OTA_GATEWAY_CACHE_URL": "http://10.0.0.99:9999",
        "TELEGRAM_BOT_TOKEN_FILE": "/inherited/secret",
    }

    cli._load_runtime_environment(
        "camera-satellite",
        files_by_profile={"camera-satellite": (agent_env, camera_env)},
        expected_owner_uid=os.getuid(),
        environment=environment,
    )

    assert environment["EDGEWATCH_OTA_GATEWAY_CACHE_URL"] == "http://10.42.0.1:8091"
    assert environment["EDGEWATCH_MODEL_CURRENT_SYMLINK"] == "/opt/edgewatch/models/current"
    assert environment["EDGEWATCH_ASSET_BUNDLE_APPLY_CMD"] == cli._CAMERA_ASSET_APPLY_CMD
    assert environment["EDGEWATCH_ENABLE_OTA_APPLY"] == "false"
    assert environment["RUNTIME_POWER_MODE"] == "eco"
    assert "TELEGRAM_BOT_TOKEN_FILE" not in environment
    assert "MEDIA_RTSP_CAM1_URL" not in cli._CONTROL_ENV_ALLOWLIST


def test_runtime_profile_rejects_writable_or_redirected_environment(tmp_path: Path) -> None:
    environment = tmp_path / "agent.env"
    environment.write_text("EDGEWATCH_ENABLE_OTA_APPLY=false\n", encoding="utf-8")
    environment.chmod(0o620)
    with pytest.raises(Exception, match="not trusted"):
        cli._parse_environment_file(environment, expected_owner_uid=os.getuid())

    environment.chmod(0o600)
    redirected = tmp_path / "redirected.env"
    redirected.symlink_to(environment)
    with pytest.raises(Exception, match="not trusted"):
        cli._parse_environment_file(redirected, expected_owner_uid=os.getuid())


def test_camera_power_evidence_is_fresh_private_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evidence = tmp_path / "state" / "power.json"
    monkeypatch.setenv("EDGEWATCH_POWER_STATE_PATH", str(evidence))

    cli._refresh_camera_power_evidence(
        run_command=lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="throttled=0x0\n")
    )

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["last_evaluation"]["evidence"] == "none"
    assert payload["last_evaluation"]["power_unsustainable"] is False
    assert stat.S_IMODE(evidence.stat().st_mode) == 0o600

    with pytest.raises(Exception, match="requires stable Pi power"):
        cli._refresh_camera_power_evidence(
            run_command=lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="throttled=0x50000\n")
        )
    assert not evidence.exists()


def test_cli_does_not_echo_invalid_input_or_environment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "super-secret-token"
    monkeypatch.setenv("EDGEWATCH_DEVICE_TOKEN", secret)
    monkeypatch.delenv("SSH_ORIGINAL_COMMAND", raising=False)
    monkeypatch.setattr(sys, "stdin", _BinaryStdin((b"{" + secret.encode())))

    assert cli.main(["--device-id", "device-1", "--ssh-stdin"]) == 2
    output = capsys.readouterr().out
    assert secret not in output
    assert os.environ["EDGEWATCH_DEVICE_TOKEN"] == secret
