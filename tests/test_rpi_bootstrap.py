from __future__ import annotations

import io
import hashlib
import logging
import json
import stat
import tarfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import scripts.rpi_bootstrap as rpi_bootstrap

from scripts.rpi_bootstrap import (
    BootstrapConfig,
    ensure_current_release_symlink,
    device_hostname,
    build_config,
    install_bundle,
    install_ota_public_key,
    parse_env_file,
    redact_consumed_secrets,
    render_agent_env,
    render_agent_service,
    render_lte_connection,
    bootstrap,
    run_tailscale,
    write_ssh_authorized_key,
    write_lte_profile,
    verify_agent_readiness,
    verify_ssh_access,
    verify_telegram_delivery,
)


SSH_PUBLIC_KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAiBCojDJ47LQ3NmXMPd7KY4KO9LNAYc+iipJmATuGQN operator@example.com"
)
CONTROL_SSH_PUBLIC_KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAABAgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhscHR4f controller@example.com"
)
OTA_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAzWMPKRLmTKdCvRuKx8es
WX7LfqH2NkrDpNIA8r0aX3vaGKJVIhYW6osFlMbCQlRloI4YFi2D6cMaCGGtvAEx
Pm5KHpNoIfekbzXEUNUe44SDN5QAxHH02470eoKjQg5Tk1AyblTbPhImRPNpuT1d
u+vlOXRSAReVVDA0jpdlgj2T3ul7+hyAUnTmcNHiCo0rXGn4pESRVfXQi4u9XKfg
T8fsnQvllVSJD2H1aZ5AT4SZmW+aH8bD/lTig+XbMDJl95mX2Vxtz13xs8AdqIRl
jwdA18DxJPs0ZiGo6SoylJG9aVCu8i/oSK7Hs2n+tNaBkrznO9LN8MaWDvA6eavG
VQIDAQAB
-----END PUBLIC KEY-----
"""


def make_config(tmp_path: Path) -> BootstrapConfig:
    return BootstrapConfig(
        repo_dir=tmp_path / "edgewatch-telemetry",
        data_dir=tmp_path / "var" / "lib" / "edgewatch",
        agent_env_path=tmp_path / "edgewatch-telemetry" / "agent" / ".env",
        agent_service_path=tmp_path / "edgewatch-agent.service",
        firstboot_marker=tmp_path / "bootstrap.complete",
        firstboot_report=tmp_path / "bootstrap-report.json",
        device_id="rpi-001",
        telemetry_transport="api",
        api_url="https://ingest.example.com",
        device_token="secret-token",
        telegram_chat_id=None,
        telegram_bot_token_file=None,
        telegram_bot_token=None,
        bootstrap_telegram_bot_token_file=None,
        ssh_user="ryne",
        ssh_authorized_key_file=None,
        control_ssh_authorized_key_file=None,
        ota_public_key_file=None,
        ota_public_key_id=None,
        sensor_config_path="./agent/config/rpi.microphone.sensors.yaml",
        runtime_power_mode="continuous",
        deep_sleep_backend="auto",
        allow_remote_shutdown="0",
        enable_ota_apply="0",
        power_mgmt_enabled="true",
        power_mgmt_mode="dual",
        python_bin=tmp_path / "edgewatch-telemetry" / ".venv" / "bin" / "python",
        agent_entrypoint=tmp_path / "edgewatch-telemetry" / "agent" / "edgewatch_agent.py",
        agent_workdir=tmp_path / "edgewatch-telemetry" / "agent",
        current_symlink=None,
        tailscale_auth_key=None,
        tailscale_required=False,
        tailscale_hostname=None,
        tailscale_enable_ssh=False,
        bundle_uri=None,
        bundle_sha256=None,
        bundle_signature=None,
        bundle_signature_scheme="none",
        bundle_signature_key_id=None,
        bundle_keyring_dir=None,
        bundle_install_dir=tmp_path / "edgewatch-telemetry",
        bundle_strip_components=1,
        lte_apn=None,
        lte_username=None,
        lte_password=None,
        lte_connection_name="edgewatch-lte",
        lte_ifname="*",
        extra_agent_env={
            "CELLULAR_METRICS_ENABLED": "true",
            "CELLULAR_WATCHDOG_ENABLED": "true",
        },
        camera_model_recovery_service_path=tmp_path / "edgewatch-camera-model-recovery.service",
    )


def prepare_runtime(config: BootstrapConfig, *, entrypoint: str = "print('agent')\n") -> None:
    config.agent_workdir.mkdir(parents=True, exist_ok=True)
    config.python_bin.parent.mkdir(parents=True, exist_ok=True)
    config.python_bin.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    config.agent_entrypoint.write_text(entrypoint, encoding="utf-8")


def make_runtime_bundle(tmp_path: Path, *, entrypoint: str = "print('new')\n") -> Path:
    bundle_root = tmp_path / "bundle-source" / "edgewatch-telemetry"
    (bundle_root / "agent").mkdir(parents=True)
    (bundle_root / ".venv" / "bin").mkdir(parents=True)
    (bundle_root / "agent" / "edgewatch_agent.py").write_text(entrypoint, encoding="utf-8")
    (bundle_root / ".venv" / "bin" / "python").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    archive = tmp_path / "edgewatch-bundle.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(bundle_root, arcname="edgewatch-telemetry")
    return archive


def test_parse_env_file_handles_quotes_and_exports(tmp_path: Path) -> None:
    env = tmp_path / "bootstrap.env"
    env.write_text(
        """
        # comment
        export BOOTSTRAP_REPO_DIR=/home/ryne/edgewatch-telemetry
        EDGEWATCH_DEVICE_ID="rpi-001"
        EDGEWATCH_DEVICE_TOKEN='secret token'
        """
    )

    parsed = parse_env_file(env)

    assert parsed["BOOTSTRAP_REPO_DIR"] == "/home/ryne/edgewatch-telemetry"
    assert parsed["EDGEWATCH_DEVICE_ID"] == "rpi-001"
    assert parsed["EDGEWATCH_DEVICE_TOKEN"] == "secret token"


def test_render_agent_env_includes_derived_paths(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    content = render_agent_env(config)

    assert "EDGEWATCH_API_URL=https://ingest.example.com" in content
    assert "EDGEWATCH_DEVICE_ID=rpi-001" in content
    assert "EDGEWATCH_DEVICE_TOKEN=secret-token" in content
    assert f"BUFFER_DB_PATH={tmp_path / 'var' / 'lib' / 'edgewatch' / 'telemetry_buffer.sqlite'}" in content
    assert (
        f"EDGEWATCH_POLICY_CACHE_PATH={tmp_path / 'var' / 'lib' / 'edgewatch' / 'policy_cache_rpi-001.json'}"
        in content
    )
    assert "CELLULAR_METRICS_ENABLED=true" in content
    assert "CELLULAR_INTERFACE=wwan0" in content
    assert (
        f"CELLULAR_USAGE_STATE_PATH={tmp_path / 'var' / 'lib' / 'edgewatch' / 'cellular_usage_rpi-001.json'}"
        in content
    )
    assert (
        f"EDGEWATCH_DEADLETTER_PATH={tmp_path / 'var' / 'lib' / 'edgewatch' / 'deadletter_rpi-001.jsonl'}"
        in content
    )
    assert f"EDGEWATCH_READY_PATH={tmp_path / 'var' / 'lib' / 'edgewatch' / 'ready_rpi-001.json'}" in content


def test_render_agent_service_points_at_repo_and_env_file(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    content = render_agent_service(config)

    assert f"WorkingDirectory={config.agent_workdir}" in content
    assert f"EnvironmentFile={config.agent_env_path}" in content
    assert f"ExecStartPre=/usr/bin/rm -f {config.data_dir / 'ready_rpi-001.json'}" in content
    assert f"ExecStart={config.python_bin} {config.agent_entrypoint}" in content
    assert f"ReadWritePaths={config.data_dir}" in content
    assert "StartLimitIntervalSec=300" in content
    assert "StartLimitBurst=10" in content
    assert "Restart=always" in content
    assert "TimeoutStopSec=30" in content
    assert "UMask=0077" in content
    assert "WatchdogSec=" not in content


def test_render_lte_connection_is_deterministic(tmp_path: Path) -> None:
    config = replace(make_config(tmp_path), lte_apn="nxtgenphone", lte_username="user", lte_password="pass")

    content = render_lte_connection(config)

    assert "type=gsm" in content
    assert "apn=nxtgenphone" in content
    assert "username=user" in content
    assert "password=pass" in content
    assert "method=auto" in content
    assert "method=ignore" in content
    assert "uuid=" in content

    dry_run_content = render_lte_connection(config, redact_secrets=True)
    assert "password=pass" not in dry_run_content
    assert "password=REDACTED" in dry_run_content


def test_build_config_accepts_bootstrap_prefixed_values(tmp_path: Path) -> None:
    raw = {
        "BOOTSTRAP_REPO_DIR": str(tmp_path / "edgewatch-telemetry"),
        "EDGEWATCH_API_URL": "https://ingest.example.com",
        "EDGEWATCH_DEVICE_ID": "rpi-001",
        "EDGEWATCH_DEVICE_TOKEN": "secret-token",
        "BOOTSTRAP_LTE_APN": "nxtgenphone",
    }
    config = build_config(raw)

    assert config.repo_dir == tmp_path / "edgewatch-telemetry"
    assert config.lte_apn == "nxtgenphone"


def test_current_release_symlink_is_atomic_idempotent_and_durable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = replace(
        make_config(tmp_path),
        current_symlink=tmp_path / "opt" / "edgewatch" / "current",
    )
    config.repo_dir.mkdir(parents=True)
    fsynced: list[Path] = []
    monkeypatch.setattr("scripts.rpi_bootstrap._fsync_directory", fsynced.append)

    ensure_current_release_symlink(config)
    ensure_current_release_symlink(config)

    assert config.current_symlink is not None
    assert config.current_symlink.is_symlink()
    assert config.current_symlink.resolve() == config.repo_dir.resolve()
    assert fsynced == [config.current_symlink.parent]


def test_current_release_symlink_rejects_unexpected_existing_target(tmp_path: Path) -> None:
    config = replace(
        make_config(tmp_path),
        current_symlink=tmp_path / "opt" / "edgewatch" / "current",
    )
    config.repo_dir.mkdir(parents=True)
    unexpected = tmp_path / "unexpected"
    unexpected.mkdir()
    assert config.current_symlink is not None
    config.current_symlink.parent.mkdir(parents=True)
    config.current_symlink.symlink_to(unexpected, target_is_directory=True)

    with pytest.raises(RuntimeError, match="unexpected target"):
        ensure_current_release_symlink(config)


def test_build_config_supports_telegram_without_api_credentials(tmp_path: Path) -> None:
    config = build_config(
        {
            "BOOTSTRAP_REPO_DIR": str(tmp_path / "edgewatch-telemetry"),
            "BOOTSTRAP_DATA_DIR": str(tmp_path / "data"),
            "EDGEWATCH_TELEMETRY_TRANSPORT": "telegram",
            "EDGEWATCH_DEVICE_ID": "rpi-telegram-001",
            "TELEGRAM_CHAT_ID": "-1001234567890",
            "BOOTSTRAP_TELEGRAM_BOT_TOKEN": "super-secret-token",
            "SENSOR_BACKEND": "none",
            "SAMPLE_INTERVAL_S": "1800",
            "HEARTBEAT_INTERVAL_S": "3600",
            "BUFFER_MAX_DB_BYTES": "10485760",
            "MAX_BYTES_PER_DAY": "2000000",
            "RUNTIME_POWER_MODE": "eco",
        }
    )

    content = render_agent_env(config)

    assert config.api_url is None
    assert config.device_token is None
    assert config.telegram_bot_token_file == tmp_path / "data" / "telegram_bot_token"
    assert "EDGEWATCH_TELEMETRY_TRANSPORT=telegram" in content
    assert "TELEGRAM_CHAT_ID=-1001234567890" in content
    assert f"TELEGRAM_BOT_TOKEN_FILE={tmp_path / 'data' / 'telegram_bot_token'}" in content
    assert "SENSOR_BACKEND=none" in content
    assert "SAMPLE_INTERVAL_S=1800" in content
    assert "HEARTBEAT_INTERVAL_S=3600" in content
    assert "BUFFER_MAX_DB_BYTES=10485760" in content
    assert "MAX_BYTES_PER_DAY=2000000" in content
    assert "RUNTIME_POWER_MODE=eco" in content
    assert "EDGEWATCH_API_URL=" not in content
    assert "EDGEWATCH_DEVICE_TOKEN=" not in content
    assert "super-secret-token" not in content


def test_build_config_requires_complete_ota_trust_anchor_configuration(tmp_path: Path) -> None:
    raw = {
        "BOOTSTRAP_REPO_DIR": str(tmp_path / "edgewatch-telemetry"),
        "EDGEWATCH_API_URL": "https://ingest.example.com",
        "EDGEWATCH_DEVICE_ID": "rpi-001",
        "EDGEWATCH_DEVICE_TOKEN": "secret-token",
        "BOOTSTRAP_OTA_PUBLIC_KEY_FILE": str(tmp_path / "release.pem"),
    }

    with pytest.raises(ValueError, match="must be configured together"):
        build_config(raw)


def test_build_config_keeps_api_mode_requirements(tmp_path: Path) -> None:
    raw = {
        "BOOTSTRAP_REPO_DIR": str(tmp_path / "edgewatch-telemetry"),
        "EDGEWATCH_DEVICE_ID": "rpi-001",
    }

    try:
        build_config(raw)
    except ValueError as exc:
        assert "EDGEWATCH_API_URL" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("API mode accepted missing API credentials")


def test_build_config_recovers_redacted_api_token_from_installed_agent_env(tmp_path: Path) -> None:
    repo_dir = tmp_path / "edgewatch-telemetry"
    agent_env = repo_dir / "agent" / ".env"
    agent_env.parent.mkdir(parents=True)
    agent_env.write_text(
        "EDGEWATCH_DEVICE_ID=rpi-001\nEDGEWATCH_DEVICE_TOKEN=persisted-device-token\n",
        encoding="utf-8",
    )

    config = build_config(
        {
            "BOOTSTRAP_REPO_DIR": str(repo_dir),
            "EDGEWATCH_API_URL": "https://ingest.example.com",
            "EDGEWATCH_DEVICE_ID": "rpi-001",
        }
    )

    assert config.device_token == "persisted-device-token"


def test_dry_run_agent_env_redacts_api_token(tmp_path: Path) -> None:
    content = render_agent_env(make_config(tmp_path), redact_secrets=True)

    assert "secret-token" not in content
    assert "EDGEWATCH_DEVICE_TOKEN=REDACTED" in content


def test_bootstrap_writes_secure_telegram_token_and_marks_complete_after_health(
    tmp_path: Path, monkeypatch
) -> None:
    config = replace(
        make_config(tmp_path),
        telemetry_transport="telegram",
        api_url=None,
        device_token=None,
        telegram_chat_id="-1001234567890",
        telegram_bot_token_file=tmp_path / "data" / "telegram-token",
        telegram_bot_token="super-secret-token",
        bootstrap_telegram_bot_token_file=None,
    )
    config.repo_dir.mkdir(parents=True)
    config.agent_workdir.mkdir(parents=True)
    config.python_bin.parent.mkdir(parents=True)
    config.python_bin.write_text("#!/usr/bin/env python3\n")
    config.agent_entrypoint.write_text("print('agent')\n")
    commands: list[list[str]] = []

    def fake_run_required(command: list[str], description: str) -> None:
        commands.append(command)

    monkeypatch.setattr("scripts.rpi_bootstrap.run_required", fake_run_required)
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.verify_agent_readiness",
        lambda _config: commands.append(["verified-agent-readiness"]),
    )
    monkeypatch.setattr("scripts.rpi_bootstrap.verify_telegram_delivery", lambda _config: None)

    warnings = bootstrap(config, logging.getLogger("test"))

    assert warnings == []
    assert config.telegram_bot_token_file is not None
    assert config.telegram_bot_token_file.read_text() == "super-secret-token\n"
    assert stat.S_IMODE(config.telegram_bot_token_file.stat().st_mode) == 0o600
    assert "super-secret-token" not in config.agent_env_path.read_text()
    assert config.firstboot_marker.read_text() == "complete\n"
    report = json.loads(config.firstboot_report.read_text())
    assert report["telemetry_transport"] == "telegram"
    assert ["verified-agent-readiness"] in commands


def test_bootstrap_imports_and_removes_boot_partition_token_file(tmp_path: Path, monkeypatch) -> None:
    source_token = tmp_path / "boot" / "edgewatch" / "telegram_bot_token"
    source_token.parent.mkdir(parents=True)
    source_token.write_text("file-secret-token\n")
    config = replace(
        make_config(tmp_path),
        telemetry_transport="telegram",
        api_url=None,
        device_token=None,
        telegram_chat_id="-1001234567890",
        telegram_bot_token_file=tmp_path / "data" / "telegram-token",
        telegram_bot_token=None,
        bootstrap_telegram_bot_token_file=source_token,
    )
    config.repo_dir.mkdir(parents=True)
    config.agent_workdir.mkdir(parents=True)
    config.python_bin.parent.mkdir(parents=True)
    config.python_bin.write_text("#!/usr/bin/env python3\n")
    config.agent_entrypoint.write_text("print('agent')\n")
    monkeypatch.setattr("scripts.rpi_bootstrap.run_required", lambda command, description: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.verify_agent_readiness", lambda _config: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.verify_telegram_delivery", lambda _config: None)

    bootstrap(config, logging.getLogger("test"))

    assert config.telegram_bot_token_file is not None
    assert config.telegram_bot_token_file.read_text() == "file-secret-token\n"
    assert stat.S_IMODE(config.telegram_bot_token_file.stat().st_mode) == 0o600
    assert not source_token.exists()
    assert "file-secret-token" not in config.agent_env_path.read_text()


def test_bootstrap_consumes_boot_secrets_before_completion_marker(tmp_path: Path, monkeypatch) -> None:
    source_token = tmp_path / "boot" / "edgewatch" / "telegram_bot_token"
    source_key = tmp_path / "boot" / "edgewatch" / "authorized_key"
    source_control_key = tmp_path / "boot" / "edgewatch" / "control_authorized_key"
    source_ota_key = tmp_path / "boot" / "edgewatch" / "ota_keys" / "edgewatch-release.pem"
    source_token.parent.mkdir(parents=True)
    source_ota_key.parent.mkdir(parents=True)
    source_token.write_text("file-secret-token\n")
    source_key.write_text(f"{SSH_PUBLIC_KEY}\n")
    source_control_key.write_text(f"{CONTROL_SSH_PUBLIC_KEY}\n")
    source_ota_key.write_text(OTA_PUBLIC_KEY, encoding="ascii")
    boot_config = tmp_path / "boot" / "edgewatch" / "bootstrap.env"
    boot_config.write_text(
        "EDGEWATCH_DEVICE_ID=rpi-001\n"
        "BOOTSTRAP_TELEGRAM_BOT_TOKEN_FILE=/boot/firmware/edgewatch/telegram_bot_token\n"
        "BOOTSTRAP_LTE_PASSWORD=secret-lte-password\n"
    )
    config = replace(
        make_config(tmp_path),
        telemetry_transport="telegram",
        api_url=None,
        device_token=None,
        telegram_chat_id="-1001234567890",
        telegram_bot_token_file=tmp_path / "data" / "telegram-token",
        bootstrap_telegram_bot_token_file=source_token,
        ssh_authorized_key_file=source_key,
        control_ssh_authorized_key_file=source_control_key,
        ota_public_key_file=source_ota_key,
        ota_public_key_id="edgewatch-release",
        extra_agent_env={"EDGEWATCH_OTA_KEYRING_DIR": str(tmp_path / "opt" / "edgewatch" / "keys")},
    )
    config.repo_dir.mkdir(parents=True)
    config.agent_workdir.mkdir(parents=True)
    config.python_bin.parent.mkdir(parents=True)
    config.python_bin.write_text("#!/usr/bin/env python3\n")
    config.agent_entrypoint.write_text("print('agent')\n")
    monkeypatch.setattr("scripts.rpi_bootstrap.run_required", lambda command, description: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.verify_agent_readiness", lambda _config: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.verify_telegram_delivery", lambda _config: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.write_ssh_authorized_key", lambda _config: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.verify_ssh_access", lambda _config: None)

    def assert_consumed_before_marker(_config, _logger, *, warnings):
        assert warnings == []
        assert not source_token.exists()
        assert not source_key.exists()
        assert not source_control_key.exists()
        assert not source_ota_key.exists()
        assert "secret-lte-password" not in boot_config.read_text()

    monkeypatch.setattr("scripts.rpi_bootstrap.write_firstboot_state", assert_consumed_before_marker)

    bootstrap(config, logging.getLogger("test"), boot_config_path=boot_config)


def test_bootstrap_fsyncs_boot_secret_directories_before_completion_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_dir = tmp_path / "boot-token"
    key_dir = tmp_path / "boot-key"
    token_dir.mkdir()
    key_dir.mkdir()
    source_token = token_dir / "telegram_bot_token"
    source_key = key_dir / "authorized_key"
    ota_key_dir = tmp_path / "boot-ota-key"
    ota_key_dir.mkdir()
    source_ota_key = ota_key_dir / "edgewatch-release.pem"
    source_token.write_text("file-secret-token\n", encoding="utf-8")
    source_key.write_text(f"{SSH_PUBLIC_KEY}\n", encoding="utf-8")
    source_ota_key.write_text(OTA_PUBLIC_KEY, encoding="ascii")
    config = replace(
        make_config(tmp_path),
        telemetry_transport="telegram",
        api_url=None,
        device_token=None,
        telegram_chat_id="-1001234567890",
        telegram_bot_token_file=tmp_path / "data" / "telegram-token",
        bootstrap_telegram_bot_token_file=source_token,
        ssh_authorized_key_file=source_key,
        ota_public_key_file=source_ota_key,
        ota_public_key_id="edgewatch-release",
        extra_agent_env={"EDGEWATCH_OTA_KEYRING_DIR": str(tmp_path / "opt" / "edgewatch" / "keys")},
    )
    prepare_runtime(config)
    synced_directories: list[Path] = []
    monkeypatch.setattr("scripts.rpi_bootstrap.run_required", lambda command, description: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.verify_runtime_health", lambda _config: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.write_ssh_authorized_key", lambda _config: None)
    monkeypatch.setattr(
        "scripts.rpi_bootstrap._fsync_directory",
        lambda path: synced_directories.append(path),
    )

    def assert_durable_before_marker(_config, _logger, *, warnings):
        assert warnings == []
        assert token_dir in synced_directories
        assert key_dir in synced_directories
        assert ota_key_dir in synced_directories

    monkeypatch.setattr("scripts.rpi_bootstrap.write_firstboot_state", assert_durable_before_marker)

    bootstrap(config, logging.getLogger("test"))


def test_bootstrap_does_not_mark_complete_when_boot_secret_directory_fsync_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_token = tmp_path / "boot" / "telegram_bot_token"
    source_token.parent.mkdir()
    source_token.write_text("file-secret-token\n", encoding="utf-8")
    config = replace(
        make_config(tmp_path),
        telemetry_transport="telegram",
        api_url=None,
        device_token=None,
        telegram_chat_id="-1001234567890",
        telegram_bot_token_file=tmp_path / "data" / "telegram-token",
        bootstrap_telegram_bot_token_file=source_token,
    )
    prepare_runtime(config)
    real_fsync_directory = rpi_bootstrap._fsync_directory

    def fail_boot_directory_fsync(path: Path) -> None:
        if path == source_token.parent:
            raise OSError("simulated boot filesystem sync failure")
        real_fsync_directory(path)

    monkeypatch.setattr("scripts.rpi_bootstrap.run_required", lambda command, description: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.verify_runtime_health", lambda _config: None)
    monkeypatch.setattr("scripts.rpi_bootstrap._fsync_directory", fail_boot_directory_fsync)

    with pytest.raises(OSError, match="simulated boot filesystem sync failure"):
        bootstrap(config, logging.getLogger("test"))

    assert not config.firstboot_marker.exists()


def test_bootstrap_does_not_mark_complete_when_health_check_fails(tmp_path: Path, monkeypatch) -> None:
    config = make_config(tmp_path)
    config.repo_dir.mkdir(parents=True)
    config.agent_workdir.mkdir(parents=True)
    config.python_bin.parent.mkdir(parents=True)
    config.python_bin.write_text("#!/usr/bin/env python3\n")
    config.agent_entrypoint.write_text("print('agent')\n")

    monkeypatch.setattr("scripts.rpi_bootstrap.run_required", lambda command, description: None)
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.verify_runtime_health",
        lambda _config: (_ for _ in ()).throw(RuntimeError("agent unhealthy")),
    )

    try:
        bootstrap(config, logging.getLogger("test"))
    except RuntimeError as exc:
        assert "unhealthy" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("bootstrap accepted unhealthy agent")
    assert not config.firstboot_marker.exists()


def test_failed_health_keeps_boot_partition_token_for_retry(tmp_path: Path, monkeypatch) -> None:
    source_token = tmp_path / "boot" / "telegram_bot_token"
    source_token.parent.mkdir(parents=True)
    source_token.write_text("retry-secret-token\n")
    config = replace(
        make_config(tmp_path),
        telemetry_transport="telegram",
        api_url=None,
        device_token=None,
        telegram_chat_id="-1001234567890",
        telegram_bot_token_file=tmp_path / "data" / "telegram-token",
        bootstrap_telegram_bot_token_file=source_token,
    )
    config.repo_dir.mkdir(parents=True)
    config.agent_workdir.mkdir(parents=True)
    config.python_bin.parent.mkdir(parents=True)
    config.python_bin.write_text("#!/usr/bin/env python3\n")
    config.agent_entrypoint.write_text("print('agent')\n")

    monkeypatch.setattr("scripts.rpi_bootstrap.run_required", lambda command, description: None)
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.verify_runtime_health",
        lambda _config: (_ for _ in ()).throw(RuntimeError("agent unhealthy")),
    )

    try:
        bootstrap(config, logging.getLogger("test"))
    except RuntimeError:
        pass
    else:  # pragma: no cover - assertion guard
        raise AssertionError("bootstrap accepted unhealthy agent")

    assert source_token.exists()
    assert not config.firstboot_marker.exists()


def test_lte_probe_failure_cannot_be_masked_by_other_network_connectivity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boot_config = tmp_path / "boot" / "bootstrap.env"
    boot_config.parent.mkdir()
    boot_config.write_text(
        "EDGEWATCH_DEVICE_ID=rpi-001\nEDGEWATCH_DEVICE_TOKEN=retry-api-token\nBOOTSTRAP_LTE_APN=hologram\n",
        encoding="utf-8",
    )
    config = replace(make_config(tmp_path), device_token="retry-api-token", lte_apn="hologram")
    prepare_runtime(config)
    calls: list[str] = []
    monkeypatch.setattr("scripts.rpi_bootstrap.run_required", lambda command, description: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.write_lte_profile", lambda _config, _logger: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.verify_agent_readiness", lambda _config: None)

    def fail_bound_cellular_probe(_config: BootstrapConfig) -> None:
        calls.append("bound-cellular-probe")
        raise RuntimeError("wwan0 data path unavailable")

    monkeypatch.setattr(
        "scripts.rpi_bootstrap.verify_cellular_data_path",
        fail_bound_cellular_probe,
    )
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.verify_telegram_delivery",
        lambda _config: calls.append("generic-network-delivery"),
    )

    with pytest.raises(RuntimeError, match="wwan0 data path unavailable"):
        bootstrap(config, logging.getLogger("test"), boot_config_path=boot_config)

    assert calls == ["bound-cellular-probe"]
    assert "retry-api-token" in boot_config.read_text(encoding="utf-8")
    assert not config.firstboot_marker.exists()


def test_redact_consumed_secrets_removes_values(tmp_path: Path) -> None:
    config_path = tmp_path / "bootstrap.env"
    config_path.write_text(
        "EDGEWATCH_DEVICE_ID=rpi-001\n"
        "export BOOTSTRAP_TELEGRAM_BOT_TOKEN='secret bot token'\n"
        "EDGEWATCH_DEVICE_TOKEN=secret-api-token\n"
        "BOOTSTRAP_LTE_PASSWORD=secret-lte-password\n"
        "BOOTSTRAP_TAILSCALE_AUTH_KEY=tskey-auth-secret\n"
        "BOOTSTRAP_TELEGRAM_BOT_TOKEN_FILE=/boot/firmware/edgewatch/telegram_bot_token\n"
        "BOOTSTRAP_SSH_AUTHORIZED_KEY_FILE=/boot/firmware/edgewatch/authorized_key\n"
    )

    redact_consumed_secrets(config_path)

    content = config_path.read_text()
    assert "secret bot token" not in content
    assert "secret-api-token" not in content
    assert "secret-lte-password" not in content
    assert "tskey-auth-secret" not in content
    assert "BOOTSTRAP_TAILSCALE_ENROLLED=true" in content
    assert "BOOTSTRAP_TELEGRAM_BOT_TOKEN_FILE=/boot/firmware/edgewatch/telegram_bot_token" in content
    assert "BOOTSTRAP_SSH_AUTHORIZED_KEY_FILE=/boot/firmware/edgewatch/authorized_key" in content
    assert "EDGEWATCH_DEVICE_ID=rpi-001" in content
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_install_bundle_extracts_bundle_into_repo_dir(tmp_path: Path, monkeypatch) -> None:
    bundle_root = tmp_path / "bundle"
    repo_root = bundle_root / "edgewatch-telemetry"
    (repo_root / "agent").mkdir(parents=True)
    (repo_root / ".venv" / "bin").mkdir(parents=True)
    (repo_root / "agent" / "edgewatch_agent.py").write_text("print('hello')\n")
    (repo_root / ".venv" / "bin" / "python").write_text("#!/usr/bin/env python3\n")

    archive = tmp_path / "edgewatch-bundle.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(repo_root, arcname="edgewatch-telemetry")

    config = replace(
        make_config(tmp_path),
        bundle_uri=f"file://{archive}",
        bundle_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        bundle_signature=None,
        bundle_signature_scheme="none",
        bundle_signature_key_id=None,
        bundle_keyring_dir=None,
        bundle_install_dir=tmp_path / "install-target",
        bundle_strip_components=1,
    )
    monkeypatch.setattr("scripts.rpi_bootstrap.DEFAULT_BUNDLE_CACHE_DIR", tmp_path / "cache")

    install_bundle(config, logger=logging.getLogger("test"))

    assert (config.bundle_install_dir / "agent" / "edgewatch_agent.py").exists()
    assert (config.bundle_install_dir / ".venv" / "bin" / "python").exists()


def test_install_bundle_failure_keeps_last_working_install(tmp_path: Path, monkeypatch) -> None:
    install_dir = tmp_path / "edgewatch-telemetry"
    (install_dir / "agent").mkdir(parents=True)
    (install_dir / ".venv" / "bin").mkdir(parents=True)
    (install_dir / "agent" / "edgewatch_agent.py").write_text("print('old')\n")
    (install_dir / ".venv" / "bin" / "python").write_text("old python\n")

    invalid_root = tmp_path / "invalid" / "edgewatch-telemetry"
    invalid_root.mkdir(parents=True)
    (invalid_root / "README.md").write_text("missing runtime\n")
    archive = tmp_path / "invalid-bundle.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(invalid_root, arcname="edgewatch-telemetry")

    config = replace(
        make_config(tmp_path),
        repo_dir=install_dir,
        agent_env_path=install_dir / "agent" / ".env",
        python_bin=install_dir / ".venv" / "bin" / "python",
        agent_entrypoint=install_dir / "agent" / "edgewatch_agent.py",
        agent_workdir=install_dir / "agent",
        bundle_uri=f"file://{archive}",
        bundle_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        bundle_install_dir=install_dir,
    )
    monkeypatch.setattr("scripts.rpi_bootstrap.DEFAULT_BUNDLE_CACHE_DIR", tmp_path / "cache")

    try:
        install_bundle(config, logging.getLogger("test"))
    except ValueError as exc:
        assert "missing required runtime paths" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("invalid bundle replaced the working install")

    assert (install_dir / "agent" / "edgewatch_agent.py").read_text() == "print('old')\n"
    assert (install_dir / ".venv" / "bin" / "python").read_text() == "old python\n"
    assert not list(tmp_path.glob(".edgewatch-telemetry.staging-*"))


@pytest.mark.parametrize(
    "invalid_sha",
    [None, "", "abc123", "A" * 64, "g" * 64],
)
def test_install_bundle_rejects_missing_or_invalid_sha256(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_sha: str | None,
) -> None:
    archive = make_runtime_bundle(tmp_path)
    config = replace(
        make_config(tmp_path),
        bundle_uri=f"file://{archive}",
        bundle_sha256=invalid_sha,
        bundle_install_dir=tmp_path / "install-target",
    )
    monkeypatch.setattr("scripts.rpi_bootstrap.DEFAULT_BUNDLE_CACHE_DIR", tmp_path / "cache")

    with pytest.raises(ValueError, match="required and must be 64 lowercase hex"):
        install_bundle(config, logging.getLogger("test"))

    assert not config.bundle_install_dir.exists()


@pytest.mark.parametrize(
    ("signature", "key_id", "has_keyring"),
    [
        ("signature", None, False),
        (None, "release-key", False),
        (None, None, True),
        ("signature", "release-key", False),
        ("signature", None, True),
        (None, "release-key", True),
    ],
)
def test_install_bundle_rejects_partial_signature_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    signature: str | None,
    key_id: str | None,
    has_keyring: bool,
) -> None:
    archive = make_runtime_bundle(tmp_path)
    keyring = tmp_path / "keyring" if has_keyring else None
    if keyring is not None:
        keyring.mkdir()
    config = replace(
        make_config(tmp_path),
        bundle_uri=f"file://{archive}",
        bundle_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        bundle_signature=signature,
        bundle_signature_key_id=key_id,
        bundle_keyring_dir=keyring,
        bundle_install_dir=tmp_path / "install-target",
    )
    monkeypatch.setattr("scripts.rpi_bootstrap.DEFAULT_BUNDLE_CACHE_DIR", tmp_path / "cache")

    with pytest.raises(ValueError, match="must be configured together"):
        install_bundle(config, logging.getLogger("test"))

    assert not config.bundle_install_dir.exists()


def test_install_bundle_rejects_signature_fields_when_scheme_is_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = make_runtime_bundle(tmp_path)
    keyring = tmp_path / "keyring"
    keyring.mkdir()
    config = replace(
        make_config(tmp_path),
        bundle_uri=f"file://{archive}",
        bundle_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        bundle_signature="signature",
        bundle_signature_scheme="none",
        bundle_signature_key_id="release-key",
        bundle_keyring_dir=keyring,
        bundle_install_dir=tmp_path / "install-target",
    )
    monkeypatch.setattr("scripts.rpi_bootstrap.DEFAULT_BUNDLE_CACHE_DIR", tmp_path / "cache")

    with pytest.raises(ValueError, match="cannot be 'none'"):
        install_bundle(config, logging.getLogger("test"))

    assert not config.bundle_install_dir.exists()


def test_post_activation_health_failure_restores_and_restarts_previous_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config(tmp_path)
    prepare_runtime(config, entrypoint="print('old')\n")
    archive = make_runtime_bundle(tmp_path, entrypoint="print('new')\n")
    config = replace(
        config,
        bundle_uri=f"file://{archive}",
        bundle_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
    )
    commands: list[list[str]] = []
    monkeypatch.setattr("scripts.rpi_bootstrap.DEFAULT_BUNDLE_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.run_required",
        lambda command, description: commands.append(command),
    )
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.verify_runtime_health",
        lambda _config: (_ for _ in ()).throw(RuntimeError("new agent unhealthy")),
    )

    with pytest.raises(RuntimeError, match="new agent unhealthy"):
        bootstrap(config, logging.getLogger("test"))

    assert config.agent_entrypoint.read_text(encoding="utf-8") == "print('old')\n"
    assert ["systemctl", "restart", "edgewatch-agent"] in commands
    assert ["systemctl", "is-active", "--quiet", "edgewatch-agent"] in commands
    assert not config.firstboot_marker.exists()


def test_device_hostname_is_stable_and_safe() -> None:
    assert device_hostname(" RPI_Field 001 ") == "rpi-field-001"
    assert len(device_hostname("x" * 100)) == 63
    assert device_hostname("雪") == device_hostname("雪")


def test_verify_telegram_delivery_posts_secret_safe_receipt(tmp_path: Path, monkeypatch) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("secret-token\n")
    config = replace(
        make_config(tmp_path),
        telemetry_transport="telegram",
        api_url=None,
        device_token=None,
        telegram_chat_id="-1001234567890",
        telegram_bot_token_file=token_file,
    )
    captured: dict[str, object] = {}

    class Response(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = request.data
        captured["timeout"] = timeout
        return Response(b'{"ok":true}')

    monkeypatch.setattr("scripts.rpi_bootstrap.urllib.request.urlopen", fake_urlopen)

    verify_telegram_delivery(config)

    assert captured["timeout"] == 20
    assert "secret-token" in str(captured["url"])
    assert isinstance(captured["body"], bytes)
    assert b"EdgeWatch+rpi-001+provisioning+verified" in captured["body"]


def test_verify_ssh_access_requires_effective_public_key_only_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = replace(make_config(tmp_path), ssh_authorized_key_file=tmp_path / "authorized_key")
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.run_required",
        lambda command, description: commands.append(command),
    )
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.run_capture_required",
        lambda command, description: (
            "authenticationmethods publickey\n"
            "kbdinteractiveauthentication no\n"
            "passwordauthentication no\n"
            "permitrootlogin no\n"
            "pubkeyauthentication yes\n"
        ),
    )

    verify_ssh_access(config)

    assert ["sshd", "-t"] in commands
    assert ["systemctl", "is-active", "--quiet", "ssh"] in commands


def test_write_ssh_authorized_key_forces_controller_through_typed_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operator_source = tmp_path / "authorized_key"
    controller_source = tmp_path / "control_authorized_key"
    operator_source.write_text(f"{SSH_PUBLIC_KEY}\n", encoding="utf-8")
    controller_source.write_text(f"{CONTROL_SSH_PUBLIC_KEY}\n", encoding="utf-8")
    home = tmp_path / "home" / "ryne"
    helper = tmp_path / "edgewatch-telemetry" / "scripts" / "edgewatch_device_control.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    config = replace(
        make_config(tmp_path),
        ssh_authorized_key_file=operator_source,
        control_ssh_authorized_key_file=controller_source,
    )
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.pwd.getpwnam",
        lambda _user: SimpleNamespace(pw_dir=str(home), pw_uid=-1, pw_gid=-1),
    )
    monkeypatch.setattr("scripts.rpi_bootstrap.os.chown", lambda *_args: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.run_required", lambda *_args: None)
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.DEFAULT_SSH_HARDENING_PATH",
        tmp_path / "sshd" / "01-edgewatch-publickey-only.conf",
    )

    write_ssh_authorized_key(config)

    authorized_keys = home / ".ssh" / "authorized_keys"
    lines = authorized_keys.read_text(encoding="utf-8").splitlines()
    assert lines[0] == SSH_PUBLIC_KEY
    assert lines[1].startswith('restrict,command="/usr/bin/sudo -n -- ')
    assert (
        f'{helper} --device-id rpi-001 --runtime-profile standalone --ssh-stdin" {CONTROL_SSH_PUBLIC_KEY}'
    ) in lines[1]
    assert stat.S_IMODE(authorized_keys.stat().st_mode) == 0o600

    operator_source.unlink()
    controller_source.unlink()
    write_ssh_authorized_key(config)
    assert authorized_keys.read_text(encoding="utf-8").splitlines() == lines


def test_write_ssh_authorized_key_rejects_reused_operator_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operator_source = tmp_path / "authorized_key"
    controller_source = tmp_path / "control_authorized_key"
    operator_source.write_text(f"{SSH_PUBLIC_KEY}\n", encoding="utf-8")
    controller_source.write_text(f"{SSH_PUBLIC_KEY}\n", encoding="utf-8")
    helper = tmp_path / "edgewatch-telemetry" / "scripts" / "edgewatch_device_control.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    config = replace(
        make_config(tmp_path),
        ssh_authorized_key_file=operator_source,
        control_ssh_authorized_key_file=controller_source,
    )
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.pwd.getpwnam",
        lambda _user: SimpleNamespace(pw_dir=str(tmp_path / "home" / "ryne"), pw_uid=-1, pw_gid=-1),
    )

    with pytest.raises(ValueError, match="different key material"):
        write_ssh_authorized_key(config)


def test_install_ota_public_key_is_validated_and_retry_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "boot" / "edgewatch" / "ota_keys" / "edgewatch-release.pem"
    source.parent.mkdir(parents=True)
    source.write_text(OTA_PUBLIC_KEY, encoding="ascii")
    keyring = tmp_path / "opt" / "edgewatch" / "keys"
    config = replace(
        make_config(tmp_path),
        ota_public_key_file=source,
        ota_public_key_id="edgewatch-release",
        extra_agent_env={"EDGEWATCH_OTA_KEYRING_DIR": str(keyring)},
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.run_required",
        lambda command, description: commands.append(command),
    )

    install_ota_public_key(config)

    destination = keyring / "edgewatch-release.pem"
    assert destination.read_text(encoding="ascii") == OTA_PUBLIC_KEY
    assert stat.S_IMODE(destination.stat().st_mode) == 0o644
    assert commands[-1] == [
        "openssl",
        "pkey",
        "-pubin",
        "-in",
        str(destination),
        "-noout",
    ]

    source.unlink()
    install_ota_public_key(config)
    assert destination.read_text(encoding="ascii") == OTA_PUBLIC_KEY


def test_install_ota_public_key_rejects_private_key_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "private.pem"
    source.write_text(
        "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----\n",
        encoding="ascii",
    )
    config = replace(
        make_config(tmp_path),
        ota_public_key_file=source,
        ota_public_key_id="edgewatch-release",
        extra_agent_env={"EDGEWATCH_OTA_KEYRING_DIR": str(tmp_path / "keys")},
    )
    monkeypatch.setattr("scripts.rpi_bootstrap.run_required", lambda *_args: None)

    with pytest.raises(ValueError, match="public key"):
        install_ota_public_key(config)


def test_verify_ssh_access_rejects_password_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = replace(make_config(tmp_path), ssh_authorized_key_file=tmp_path / "authorized_key")
    monkeypatch.setattr("scripts.rpi_bootstrap.run_required", lambda command, description: None)
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.run_capture_required",
        lambda command, description: (
            "authenticationmethods publickey\n"
            "kbdinteractiveauthentication no\n"
            "passwordauthentication yes\n"
            "permitrootlogin no\n"
            "pubkeyauthentication yes\n"
        ),
    )

    with pytest.raises(RuntimeError, match="passwordauthentication"):
        verify_ssh_access(config)


def test_verify_agent_readiness_matches_systemd_pid_and_stays_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config(tmp_path)
    ready_path = config.data_dir / "ready_rpi-001.json"
    ready_path.parent.mkdir(parents=True)
    ready_path.write_text(
        json.dumps(
            {
                "device_id": "rpi-001",
                "transport": "api",
                "pid": 4242,
                "process_session_id": "session-1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("scripts.rpi_bootstrap.run_required", lambda command, description: None)
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.run_capture_required",
        lambda command, description: "4242",
    )

    verify_agent_readiness(config, timeout_s=0, stability_s=0)


def test_verify_agent_readiness_rejects_receipt_from_stale_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config(tmp_path)
    ready_path = config.data_dir / "ready_rpi-001.json"
    ready_path.parent.mkdir(parents=True)
    ready_path.write_text(
        json.dumps(
            {
                "device_id": "rpi-001",
                "transport": "api",
                "pid": 4242,
                "process_session_id": "stale-session",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("scripts.rpi_bootstrap.run_required", lambda command, description: None)
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.run_capture_required",
        lambda command, description: "4343",
    )

    with pytest.raises(RuntimeError, match="did not become ready") as exc_info:
        verify_agent_readiness(config, timeout_s=0, stability_s=0)

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "stale process" in str(exc_info.value.__cause__)


def test_verify_agent_readiness_rejects_restart_during_stability_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config(tmp_path)
    ready_path = config.data_dir / "ready-rpi-001.json"
    config = replace(config, extra_agent_env={"EDGEWATCH_READY_PATH": str(ready_path)})
    ready_path.parent.mkdir(parents=True)

    def write_receipt(pid: int, session_id: str) -> None:
        ready_path.write_text(
            json.dumps(
                {
                    "device_id": "rpi-001",
                    "transport": "api",
                    "pid": pid,
                    "process_session_id": session_id,
                }
            ),
            encoding="utf-8",
        )

    write_receipt(4242, "session-1")
    main_pids = iter(["4242", "4343"])
    monkeypatch.setattr("scripts.rpi_bootstrap.run_required", lambda command, description: None)
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.run_capture_required",
        lambda command, description: next(main_pids),
    )

    def simulate_restart(_seconds: float) -> None:
        write_receipt(4343, "session-2")

    monkeypatch.setattr("scripts.rpi_bootstrap.time.sleep", simulate_restart)

    with pytest.raises(RuntimeError, match="restarted during the readiness stability window"):
        verify_agent_readiness(config, timeout_s=0, stability_s=1)


def test_tailscale_request_fails_when_cli_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = replace(
        make_config(tmp_path),
        tailscale_auth_key="tskey-auth-secret",
        tailscale_required=True,
    )
    monkeypatch.setattr("scripts.rpi_bootstrap.shutil_which", lambda command: None)

    with pytest.raises(RuntimeError, match="not installed"):
        run_tailscale(config, logging.getLogger("test"))


def test_tailscale_bootstrap_failure_keeps_credentials_and_completion_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boot_config = tmp_path / "boot" / "bootstrap.env"
    boot_config.parent.mkdir()
    boot_config.write_text(
        "EDGEWATCH_DEVICE_ID=rpi-001\n"
        "EDGEWATCH_DEVICE_TOKEN=secret-token\n"
        "BOOTSTRAP_TAILSCALE_AUTH_KEY=tskey-auth-retry-secret\n",
        encoding="utf-8",
    )
    config = replace(
        make_config(tmp_path),
        tailscale_auth_key="tskey-auth-retry-secret",
        tailscale_required=True,
    )
    prepare_runtime(config)
    monkeypatch.setattr("scripts.rpi_bootstrap.run_required", lambda command, description: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.shutil_which", lambda command: None)

    with pytest.raises(RuntimeError, match="not installed"):
        bootstrap(config, logging.getLogger("test"), boot_config_path=boot_config)

    assert "tskey-auth-retry-secret" in boot_config.read_text(encoding="utf-8")
    assert not config.firstboot_marker.exists()


def test_tailscale_enrollment_is_health_gated_and_temp_secret_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = replace(
        make_config(tmp_path),
        tailscale_auth_key="tskey-auth-secret",
        tailscale_required=True,
        tailscale_enable_ssh=True,
    )
    config.data_dir.mkdir(parents=True)
    commands: list[list[str]] = []
    monkeypatch.setattr("scripts.rpi_bootstrap.shutil_which", lambda command: "/usr/bin/tailscale")
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.run_required",
        lambda command, description: commands.append(command),
    )
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.run_capture_required",
        lambda command, description: "100.64.0.42",
    )

    run_tailscale(config, logging.getLogger("test"))

    assert not (config.data_dir / ".tailscale-auth-key").exists()
    assert ["tailscale", "set", "--ssh"] in commands
    assert all("tskey-auth-secret" not in " ".join(command) for command in commands)


def test_lte_retry_preserves_installed_password(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile_dir = tmp_path / "NetworkManager"
    profile_dir.mkdir()
    profile_path = profile_dir / "edgewatch-lte.nmconnection"
    profile_path.write_text("[gsm]\napn=hologram\npassword=persisted-lte-secret\n", encoding="utf-8")
    config = replace(make_config(tmp_path), lte_apn="hologram", lte_password=None)
    monkeypatch.setattr("scripts.rpi_bootstrap.DEFAULT_NETWORKMANAGER_CONNECTION_DIR", profile_dir)
    monkeypatch.setattr("scripts.rpi_bootstrap.run_required", lambda command, description: None)

    write_lte_profile(config, logging.getLogger("test"))

    assert "password=persisted-lte-secret" in profile_path.read_text(encoding="utf-8")


def test_build_config_enforces_role_specific_trust_and_transport(tmp_path: Path) -> None:
    base = {
        "BOOTSTRAP_REPO_DIR": str(tmp_path / "repo"),
        "BOOTSTRAP_OTA_PUBLIC_KEY_FILE": str(tmp_path / "ota.pem"),
        "BOOTSTRAP_OTA_PUBLIC_KEY_ID": "release",
        "EDGEWATCH_DEVICE_ID": "camera-001",
    }
    camera = build_config(
        {
            **base,
            "BOOTSTRAP_PROFILE": "camera-satellite",
            "EDGEWATCH_TELEMETRY_TRANSPORT": "none",
            "BOOTSTRAP_CONTROL_SSH_AUTHORIZED_KEY_FILE": str(tmp_path / "controller.pub"),
            "BOOTSTRAP_CAMERA_RUNTIME_ENV_FILE": str(tmp_path / "camera.env"),
            "BOOTSTRAP_CAMERA_CREDENTIALS_FILE": str(tmp_path / "camera.json"),
            "BOOTSTRAP_MODEL_PUBLIC_KEY_FILE": str(tmp_path / "model.pem"),
            "BOOTSTRAP_MODEL_PUBLIC_KEY_ID": "models",
            "BOOTSTRAP_INITIAL_MODEL_BUNDLE_FILE": str(tmp_path / "initial-model.tar"),
            "EDGEWATCH_OTA_GATEWAY_CACHE_URL": "http://10.42.0.1:8091",
        }
    )
    assert camera.profile == "camera-satellite"
    assert camera.lte_apn is None
    assert camera.telegram_bot_token_file is None
    assert camera.extra_agent_env["EDGEWATCH_OTA_GATEWAY_CACHE_URL"] == ("http://10.42.0.1:8091")

    missing_initial_model = {
        **base,
        "BOOTSTRAP_PROFILE": "camera-satellite",
        "EDGEWATCH_TELEMETRY_TRANSPORT": "none",
        "BOOTSTRAP_CONTROL_SSH_AUTHORIZED_KEY_FILE": str(tmp_path / "controller.pub"),
        "BOOTSTRAP_CAMERA_RUNTIME_ENV_FILE": str(tmp_path / "camera.env"),
        "BOOTSTRAP_CAMERA_CREDENTIALS_FILE": str(tmp_path / "camera.json"),
        "BOOTSTRAP_MODEL_PUBLIC_KEY_FILE": str(tmp_path / "model.pem"),
        "BOOTSTRAP_MODEL_PUBLIC_KEY_ID": "models",
        "EDGEWATCH_OTA_GATEWAY_CACHE_URL": "http://10.42.0.1:8091",
    }
    with pytest.raises(ValueError, match="initial signed model bundle"):
        build_config(missing_initial_model)

    with pytest.raises(ValueError, match="gateway controller SSH public key"):
        build_config(
            {
                **base,
                "BOOTSTRAP_PROFILE": "camera-satellite",
                "EDGEWATCH_TELEMETRY_TRANSPORT": "none",
                "BOOTSTRAP_CAMERA_RUNTIME_ENV_FILE": str(tmp_path / "camera.env"),
                "BOOTSTRAP_CAMERA_CREDENTIALS_FILE": str(tmp_path / "camera.json"),
                "BOOTSTRAP_MODEL_PUBLIC_KEY_FILE": str(tmp_path / "model.pem"),
                "BOOTSTRAP_MODEL_PUBLIC_KEY_ID": "models",
                "EDGEWATCH_OTA_GATEWAY_CACHE_URL": "http://10.42.0.1:8091",
            }
        )

    with pytest.raises(ValueError, match="must not contain Telegram"):
        build_config(
            {
                **base,
                "BOOTSTRAP_PROFILE": "camera-satellite",
                "EDGEWATCH_TELEMETRY_TRANSPORT": "none",
                "BOOTSTRAP_CONTROL_SSH_AUTHORIZED_KEY_FILE": str(tmp_path / "controller.pub"),
                "BOOTSTRAP_CAMERA_RUNTIME_ENV_FILE": str(tmp_path / "camera.env"),
                "BOOTSTRAP_CAMERA_CREDENTIALS_FILE": str(tmp_path / "camera.json"),
                "BOOTSTRAP_MODEL_PUBLIC_KEY_FILE": str(tmp_path / "model.pem"),
                "BOOTSTRAP_MODEL_PUBLIC_KEY_ID": "models",
                "EDGEWATCH_OTA_GATEWAY_CACHE_URL": "http://10.42.0.1:8091",
                "TELEGRAM_CHAT_ID": "-100123",
            }
        )


def test_camera_cache_url_rejects_public_or_credentialed_endpoints(tmp_path: Path) -> None:
    base = {
        "BOOTSTRAP_REPO_DIR": str(tmp_path / "repo"),
        "BOOTSTRAP_PROFILE": "camera-satellite",
        "BOOTSTRAP_OTA_PUBLIC_KEY_FILE": str(tmp_path / "ota.pem"),
        "BOOTSTRAP_OTA_PUBLIC_KEY_ID": "release",
        "BOOTSTRAP_CONTROL_SSH_AUTHORIZED_KEY_FILE": str(tmp_path / "controller.pub"),
        "BOOTSTRAP_CAMERA_RUNTIME_ENV_FILE": str(tmp_path / "camera.env"),
        "BOOTSTRAP_CAMERA_CREDENTIALS_FILE": str(tmp_path / "camera.json"),
        "BOOTSTRAP_MODEL_PUBLIC_KEY_FILE": str(tmp_path / "model.pem"),
        "BOOTSTRAP_MODEL_PUBLIC_KEY_ID": "models",
        "EDGEWATCH_DEVICE_ID": "camera-001",
        "EDGEWATCH_TELEMETRY_TRANSPORT": "none",
    }
    for url in (
        "https://10.42.0.1:8091",
        "http://user:secret@10.42.0.1:8091",
        "http://8.8.8.8:8091",
        "http://10.42.0.1:8091/path",
    ):
        with pytest.raises(ValueError, match="OTA_GATEWAY_CACHE_URL"):
            build_config({**base, "EDGEWATCH_OTA_GATEWAY_CACHE_URL": url})


def test_image_profile_mismatch_fails_before_any_state_mutation(tmp_path: Path) -> None:
    image_profile = tmp_path / "etc" / "edgewatch-image-profile"
    image_profile.parent.mkdir(parents=True)
    image_profile.write_text("standalone\n", encoding="ascii")
    config = replace(
        make_config(tmp_path),
        profile="gateway",
        image_profile_path=image_profile,
    )

    with pytest.raises(RuntimeError, match="does not match image profile"):
        bootstrap(config, logging.getLogger("test"))

    assert not config.data_dir.exists()
    assert not config.firstboot_marker.exists()


def test_import_boot_file_requires_exact_private_source_mode(tmp_path: Path) -> None:
    source = tmp_path / "secret.env"
    source.write_text("SECRET=value\n", encoding="utf-8")
    source.chmod(0o640)

    with pytest.raises(ValueError, match="source must have mode 0600"):
        rpi_bootstrap.import_boot_file(
            source,
            tmp_path / "installed.env",
            label="private test input",
        )


def test_camera_runtime_stages_local_ota_env_and_all_service_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    camera_config_dir = tmp_path / "etc" / "edgewatch"
    runtime_source = tmp_path / "boot" / "camera.env"
    credentials_source = tmp_path / "boot" / "camera.json"
    runtime_source.parent.mkdir(parents=True)
    runtime = (
        Path("deploy/rpi/camera-satellite/camera-satellite.env.example")
        .read_text(encoding="utf-8")
        .replace("EDGEWATCH_DEVICE_ID=satellite-001", "EDGEWATCH_DEVICE_ID=camera-001")
        .replace(
            "/etc/edgewatch/camera-cam1.json",
            str(camera_config_dir / "camera-cam1.json"),
        )
    )
    runtime_source.write_text(runtime, encoding="utf-8")
    runtime_source.chmod(0o600)
    credentials_source.write_text(
        json.dumps({"username": "camera-user", "password": "camera-secret"}) + "\n",
        encoding="utf-8",
    )
    credentials_source.chmod(0o600)
    config = replace(
        make_config(tmp_path),
        profile="camera-satellite",
        device_id="camera-001",
        telemetry_transport="none",
        api_url=None,
        device_token=None,
        control_ssh_authorized_key_file=tmp_path / "controller.pub",
        camera_runtime_env_file=runtime_source,
        camera_credentials_file=credentials_source,
        camera_config_dir=camera_config_dir,
        camera_service_path=tmp_path / "systemd" / "edgewatch-camera-satellite@.service",
        camera_wake_service_path=(tmp_path / "systemd" / "edgewatch-camera-satellite-wake@.service"),
        camera_poweroff_service_path=(tmp_path / "systemd" / "edgewatch-camera-satellite-poweroff.service"),
        camera_poweroff_path=(tmp_path / "systemd" / "edgewatch-camera-satellite-poweroff.path"),
        extra_agent_env={"EDGEWATCH_OTA_GATEWAY_CACHE_URL": "http://10.42.0.1:8091"},
    )
    commands: list[list[str]] = []
    monkeypatch.setattr("scripts.rpi_bootstrap.ensure_service_account", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("scripts.rpi_bootstrap._chown", lambda *_args: None)
    monkeypatch.setattr("scripts.rpi_bootstrap._chgrp", lambda *_args: None)
    monkeypatch.setattr("scripts.rpi_bootstrap._install_model_public_key", lambda *_args: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.install_initial_model", lambda *_args: None)
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.run_required",
        lambda command, description: commands.append(command),
    )

    rpi_bootstrap.install_camera_runtime(config, logging.getLogger("test"))

    agent_env = config.agent_env_path.read_text(encoding="utf-8")
    assert "EDGEWATCH_OTA_GATEWAY_CACHE_URL=http://10.42.0.1:8091" in agent_env
    assert "EDGEWATCH_ASSET_BUNDLE_APPLY_CMD=" in agent_env
    assert "/opt/edgewatch/current/scripts/apply_model_bundle.py" in agent_env
    assert "EDGEWATCH_ENABLE_OTA_APPLY=0" in agent_env
    assert "EDGEWATCH_POWER_STATE_PATH=/var/lib/edgewatch-camera-satellite/ota-power-state.json" in agent_env
    assert "EDGEWATCH_TELEMETRY_TRANSPORT=none" in agent_env
    assert "TELEGRAM_" not in agent_env
    assert "BOOTSTRAP_LTE_" not in agent_env
    assert "--mode %i --poweroff-on-success" in config.camera_wake_service_path.read_text(encoding="utf-8")
    assert "ExecCondition=/usr/bin/test %i = check" in config.camera_service_path.read_text(encoding="utf-8")
    recovery_unit = config.camera_model_recovery_service_path.read_text(encoding="utf-8")
    assert "User=root" in recovery_unit
    assert "--recover-only" in recovery_unit
    assert "ProtectSystem=strict" in recovery_unit
    assert "ReadWritePaths=" in recovery_unit and "models" in recovery_unit
    assert "RemainAfterExit" not in recovery_unit
    assert "User=edgewatch-camera" not in recovery_unit
    assert [
        "systemctl",
        "enable",
        "--now",
        "edgewatch-camera-model-recovery.service",
    ] in commands
    assert [
        "systemctl",
        "enable",
        "--now",
        "edgewatch-camera-satellite-poweroff.path",
    ] in commands


def test_camera_bootstrap_skips_cloud_agent_and_consumes_role_inputs_after_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = [
        tmp_path / "boot" / name
        for name in (
            "controller.pub",
            "ota.pem",
            "camera.env",
            "camera.json",
            "model.pem",
            "model.tar.gz",
        )
    ]
    sources[0].parent.mkdir(parents=True)
    for source in sources:
        source.write_text("input\n", encoding="utf-8")
    config = replace(
        make_config(tmp_path),
        profile="camera-satellite",
        telemetry_transport="none",
        api_url=None,
        device_token=None,
        control_ssh_authorized_key_file=sources[0],
        ota_public_key_file=sources[1],
        ota_public_key_id="release",
        camera_runtime_env_file=sources[2],
        camera_credentials_file=sources[3],
        model_public_key_file=sources[4],
        model_public_key_id="models",
        initial_model_bundle_file=sources[5],
        extra_agent_env={"EDGEWATCH_OTA_GATEWAY_CACHE_URL": "http://10.42.0.1:8091"},
    )
    config.repo_dir.mkdir(parents=True)
    calls: list[str] = []
    monkeypatch.setattr("scripts.rpi_bootstrap.install_bundle", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.write_telegram_token_file", lambda _config: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.write_ssh_authorized_key", lambda _config: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.install_ota_public_key", lambda _config: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.configure_hostname", lambda _config: None)
    monkeypatch.setattr("scripts.rpi_bootstrap.ensure_current_release_symlink", lambda _config: None)
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.install_agent_service",
        lambda *_args: pytest.fail("camera profile must not install edgewatch-agent"),
    )
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.install_camera_runtime",
        lambda *_args: calls.append("camera-installed"),
    )
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.verify_runtime_health",
        lambda _config: calls.append("health-passed"),
    )

    bootstrap(config, logging.getLogger("test"))

    assert calls == ["camera-installed", "health-passed"]
    assert all(not source.exists() for source in sources)
    report = json.loads(config.firstboot_report.read_text(encoding="utf-8"))
    assert report["profile"] == "camera-satellite"
    assert any("HALT_ACK" in boundary for boundary in report["hardware_boundaries"])
    assert any("Wio-E5" in boundary for boundary in report["hardware_boundaries"])


def test_gateway_health_requires_radio_supervisor_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = replace(make_config(tmp_path), profile="gateway")
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.run_required",
        lambda command, description: commands.append(command),
    )

    rpi_bootstrap.verify_gateway_runtime(config)

    assert ["systemctl", "is-active", "--quiet", "edgewatch-lorawan-radio-ingress"] in commands
    assert [
        str(config.python_bin),
        "-m",
        "agent.lorawan.radio_cli",
        "check",
        "--config",
        str(config.gateway_config_dir / "lorawan-radio-ingress.yaml"),
    ] in commands


def test_gateway_runtime_imports_private_inputs_and_installs_both_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boot_dir = tmp_path / "boot"
    boot_dir.mkdir()

    def private_source(name: str, content: str) -> Path:
        source = boot_dir / name
        source.write_text(content, encoding="utf-8")
        source.chmod(0o600)
        return source

    token = tmp_path / "telemetry-token"
    token.write_text("telegram-token\n", encoding="utf-8")
    token.chmod(0o600)
    config = replace(
        make_config(tmp_path),
        profile="gateway",
        telemetry_transport="telegram",
        api_url=None,
        device_token=None,
        telegram_chat_id="-1001234567890",
        telegram_bot_token_file=token,
        lorawan_gateway_config_file=private_source("gateway.yaml", "schema_version: 1\n"),
        lorawan_registry_file=private_source("registry.yaml", "devices: {}\n"),
        lorawan_radio_ingress_file=private_source("radio.yaml", "schema_version: 1\n"),
        lorawan_vendor_config_file=private_source("vendor.yaml", "region: US915\n"),
        gateway_power_env_file=private_source(
            "power.env",
            "EDGEWATCH_GATEWAY_LTE_POWER_MODE=observe\n"
            "EDGEWATCH_GATEWAY_LTE_WINDOW_INTERVAL_S=3600\n"
            "EDGEWATCH_GATEWAY_LTE_MIN_WINDOW_S=60\n"
            "EDGEWATCH_GATEWAY_LTE_MAX_WINDOW_S=300\n"
            "EDGEWATCH_GATEWAY_LTE_MAX_HELD_WINDOW_S=14400\n",
        ),
        gateway_config_dir=tmp_path / "etc" / "edgewatch-controller",
        gateway_state_dir=tmp_path / "state" / "controller",
        gateway_radio_state_dir=tmp_path / "state" / "radio",
        gateway_service_path=tmp_path / "systemd" / "edgewatch-lorawan-gateway.service",
        radio_service_path=tmp_path / "systemd" / "edgewatch-lorawan-radio-ingress.service",
    )
    commands: list[list[str]] = []
    monkeypatch.setattr("scripts.rpi_bootstrap.ensure_service_account", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("scripts.rpi_bootstrap._chown", lambda *_args: None)
    monkeypatch.setattr("scripts.rpi_bootstrap._chgrp", lambda *_args: None)
    monkeypatch.setattr("agent.lorawan.service.load_gateway_service_config", lambda _path: None)
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.run_required",
        lambda command, description: commands.append(command),
    )

    rpi_bootstrap.install_gateway_runtime(config, logging.getLogger("test"))

    for name in (
        "lorawan-gateway.yaml",
        "lorawan-registry.yaml",
        "lorawan-radio-ingress.yaml",
        "sx1302-adapter.yaml",
        "gateway-power.env",
    ):
        installed = config.gateway_config_dir / name
        assert installed.is_file()
        assert stat.S_IMODE(installed.stat().st_mode) == 0o600
    assert ["systemctl", "enable", "edgewatch-lorawan-radio-ingress"] in commands
    assert ["systemctl", "enable", "edgewatch-lorawan-gateway"] in commands
    assert "agent.lorawan.radio_cli run" in config.radio_service_path.read_text(encoding="utf-8")
    assert "-m agent.lorawan --config" in config.gateway_service_path.read_text(encoding="utf-8")


def test_camera_readiness_health_gate_requires_fresh_local_media_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = replace(
        make_config(tmp_path),
        profile="camera-satellite",
        camera_config_dir=tmp_path / "etc" / "edgewatch",
    )
    ready = tmp_path / "ready.json"
    config.camera_config_dir.mkdir(parents=True)
    (config.camera_config_dir / "camera-satellite.env").write_text(
        f"EDGEWATCH_SATELLITE_READY_PATH={ready}\n",
        encoding="utf-8",
    )
    ready.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "ready",
                "device_id": config.device_id,
                "known_answers_valid": True,
                "preprocessing_valid": True,
                "local_media_only": True,
                "application_target": str((config.current_symlink or config.repo_dir).resolve()),
                "video_codec": "h264",
                "audio_codec": "aac",
                "valid_until": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    ready.chmod(0o600)
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.run_required",
        lambda command, description: commands.append(command),
    )
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.run_capture_required",
        lambda command, description: "success\n",
    )
    monkeypatch.setattr(
        "scripts.rpi_bootstrap.pwd.getpwnam",
        lambda _user: SimpleNamespace(pw_uid=ready.stat().st_uid),
    )

    rpi_bootstrap.verify_camera_runtime(config)

    assert ["systemctl", "start", "edgewatch-camera-satellite@check.service"] in commands

    payload = json.loads(ready.read_text(encoding="utf-8"))
    payload["local_media_only"] = False
    ready.write_text(json.dumps(payload), encoding="utf-8")
    ready.chmod(0o600)
    with pytest.raises(RuntimeError, match="readiness receipt is invalid"):
        rpi_bootstrap.verify_camera_runtime(config)
