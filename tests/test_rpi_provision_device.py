from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import TypedDict

import pytest

from scripts.rpi_provision_device import ProvisioningError, generate_bundle, render_bootstrap_env


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "rpi_provision_device.py"
TOKEN = "123456789:telegram-bot-secret"
SSH_PUBLIC_KEYS = {
    "ssh-ed25519": (
        "ssh-ed25519 "
        "AAAAC3NzaC1lZDI1NTE5AAAAIAiBCojDJ47LQ3NmXMPd7KY4KO9LNAYc+iipJmATuGQN "
        "operator@example.com"
    ),
    "ssh-rsa": (
        "ssh-rsa "
        "AAAAB3NzaC1yc2EAAAADAQABAAABAQDUvcZ9+sgH+vIjKLiVKhpPduQrdOJN1BCt3iUbFSE7Q3NBN9j3PlsnK+LuLdaFEajU385CAU2FyNfOlEUjqFIpJE/4e0DyDANQmsCNI1D7Jrl72xke3MbTQst4Y1MGjAwK5VPtUCmPeIIQTMzfx2KynJmAK0fRJEXAyLYJ76LJNFs5PG9PQdX1ChM2kr5YZXjUqMO91Ph5wlNwT8foU1R0br4t87wPmcpFFi/oW5ms2VeyAJut9YYodM/04NXCcr01i0kUZ0R3pZk3+PiRKOgfsYa/+mMNFO9P724F5tinCDJwxJBCMEFjRCIQYPI8akPThuWX6hSMIdtuylJBM85N "
        "operator@example.com"
    ),
    "ecdsa-sha2-nistp256": (
        "ecdsa-sha2-nistp256 "
        "AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBLJWR3oU1wnaBriHDvYxw2nREEq3hL6SJ+Q6ubUIFerx8NHskBxlH19TzgguAn712Hef/o46G15tbtV8/IfJfh4= "
        "operator@example.com"
    ),
}
SSH_PUBLIC_KEY = SSH_PUBLIC_KEYS["ssh-ed25519"]
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


def _token_file(tmp_path: Path, token: str = TOKEN) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "source-token"
    path.write_text(f"{token}\n")
    return path


def _ssh_public_key_file(tmp_path: Path, key: str = SSH_PUBLIC_KEY) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "id_edgewatch.pub"
    path.write_text(f"{key}\n")
    return path


def _control_ssh_public_key_file(tmp_path: Path, operator_key: str = SSH_PUBLIC_KEY) -> Path:
    control_key = (
        SSH_PUBLIC_KEYS["ssh-rsa"]
        if operator_key.split()[:2] != SSH_PUBLIC_KEYS["ssh-rsa"].split()[:2]
        else SSH_PUBLIC_KEYS["ssh-ed25519"]
    )
    path = tmp_path / "id_edgewatch_control.pub"
    path.write_text(f"{control_key}\n")
    return path


def _ota_public_key_file(tmp_path: Path, content: str = OTA_PUBLIC_KEY) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "ota_release_key.pem"
    path.write_text(content, encoding="ascii")
    return path


def _private_input(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


class GatewayInputs(TypedDict):
    lorawan_gateway_config_file: Path
    lorawan_registry_file: Path
    lorawan_radio_ingress_file: Path
    lorawan_vendor_config_file: Path
    gateway_power_env_file: Path


class CameraInputs(TypedDict):
    camera_runtime_env_file: Path
    camera_credentials_file: Path
    model_public_key_file: Path
    initial_model_bundle_file: Path


def _gateway_inputs(tmp_path: Path, *, chat_id: str) -> GatewayInputs:
    gateway = (ROOT / "deploy/rpi/gateway/lorawan-gateway.example.yaml").read_text(encoding="utf-8")
    gateway = gateway.replace('chat_id: "-1001234567890"', f'chat_id: "{chat_id}"')
    return {
        "lorawan_gateway_config_file": _private_input(tmp_path / "gateway.yaml", gateway),
        "lorawan_registry_file": _private_input(
            tmp_path / "registry.yaml",
            (ROOT / "deploy/rpi/gateway/lorawan-registry.example.yaml").read_text(encoding="utf-8"),
        ),
        "lorawan_radio_ingress_file": _private_input(
            tmp_path / "radio.yaml",
            (ROOT / "deploy/rpi/gateway/lorawan-radio-ingress.example.yaml").read_text(encoding="utf-8"),
        ),
        "lorawan_vendor_config_file": _private_input(
            tmp_path / "sx1302-us915.yaml",
            "schema_version: 1\nregion: US915\n",
        ),
        "gateway_power_env_file": _private_input(
            tmp_path / "gateway-power.env",
            (ROOT / "deploy/rpi/gateway/gateway-power.env.example").read_text(encoding="utf-8"),
        ),
    }


def _camera_inputs(tmp_path: Path, *, device_id: str) -> CameraInputs:
    tmp_path.mkdir(parents=True, exist_ok=True)
    runtime = (ROOT / "deploy/rpi/camera-satellite/camera-satellite.env.example").read_text(encoding="utf-8")
    runtime = runtime.replace("EDGEWATCH_DEVICE_ID=satellite-001", f"EDGEWATCH_DEVICE_ID={device_id}")
    model_bundle = tmp_path / "initial-model.tar"
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    with tarfile.open(model_bundle, "w") as archive:
        archive.add(manifest, arcname="manifest.json")
    model_bundle.chmod(0o600)
    return {
        "camera_runtime_env_file": _private_input(tmp_path / "camera.env", runtime),
        "camera_credentials_file": _private_input(
            tmp_path / "camera.json",
            json.dumps({"username": "local-camera-user", "password": "camera-secret"}) + "\n",
        ),
        "model_public_key_file": _ota_public_key_file(tmp_path / "model-key"),
        "initial_model_bundle_file": model_bundle,
    }


def test_generate_bundle_has_expected_fleet_defaults_and_secure_token(tmp_path: Path) -> None:
    output_dir = tmp_path / "sd-boot"

    bundle_dir = generate_bundle(
        device_id="well-001",
        telegram_chat_id="-1001234567890",
        bot_token_file=_token_file(tmp_path),
        ssh_public_key_file=_ssh_public_key_file(tmp_path),
        control_ssh_public_key_file=_control_ssh_public_key_file(tmp_path),
        ota_public_key_file=_ota_public_key_file(tmp_path),
        output_dir=output_dir,
    )

    assert bundle_dir == output_dir / "edgewatch"
    bootstrap = (bundle_dir / "bootstrap.env").read_text()
    expected = {
        "ALERT_SAMPLE_INTERVAL_S=600",
        "BOOTSTRAP_AGENT_ENTRYPOINT=/opt/edgewatch/current/agent/edgewatch_agent.py",
        "BOOTSTRAP_AGENT_WORKDIR=/opt/edgewatch/current/agent",
        "BOOTSTRAP_CURRENT_SYMLINK=/opt/edgewatch/current",
        "BOOTSTRAP_OTA_PUBLIC_KEY_FILE=/boot/firmware/edgewatch/ota_keys/edgewatch-release.pem",
        "BOOTSTRAP_OTA_PUBLIC_KEY_ID=edgewatch-release",
        "BOOTSTRAP_LTE_APN=hologram",
        "BOOTSTRAP_REPO_DIR=/opt/edgewatch/app",
        "BOOTSTRAP_CONTROL_SSH_AUTHORIZED_KEY_FILE=/boot/firmware/edgewatch/control_authorized_key",
        "BOOTSTRAP_SSH_AUTHORIZED_KEY_FILE=/boot/firmware/edgewatch/authorized_key",
        "BOOTSTRAP_SSH_USER=ryne",
        "BOOTSTRAP_TELEGRAM_BOT_TOKEN_FILE=/boot/firmware/edgewatch/telegram_bot_token",
        "BUFFER_SQLITE_SYNCHRONOUS=FULL",
        "CELLULAR_INTERFACE=wwan0",
        "CELLULAR_METRICS_ENABLED=true",
        "CELLULAR_MODEM_POLL_INTERVAL_S=300",
        "CELLULAR_USAGE_POLL_INTERVAL_S=300",
        "CELLULAR_WATCHDOG_ENABLED=false",
        "EDGEWATCH_DEVICE_ID=well-001",
        "EDGEWATCH_CURRENT_SYMLINK=/opt/edgewatch/current",
        "EDGEWATCH_LOCAL_OTA_STATE_PATH=/var/lib/edgewatch/local_ota_well-001.json",
        "EDGEWATCH_OTA_CACHE_DIR=/opt/edgewatch/update-cache",
        "EDGEWATCH_OTA_KEYRING_DIR=/opt/edgewatch/keys",
        "EDGEWATCH_RELEASES_ROOT=/opt/edgewatch/releases",
        "EDGEWATCH_SYSTEM_IMAGE_APPLY_ENABLED=false",
        "EDGEWATCH_COST_CAP_URGENT_RESERVE_BYTES=262144",
        "EDGEWATCH_TELEMETRY_TRANSPORT=telegram",
        "HEARTBEAT_INTERVAL_S=3600",
        "MAX_BYTES_PER_DAY=5000000",
        "RUNTIME_POWER_MODE=continuous",
        "SAMPLE_INTERVAL_S=600",
        "SENSOR_BACKEND=none",
        "TELEGRAM_BATCH_ENABLED=true",
        "TELEGRAM_BATCH_MAX_AGE_S=3600",
        "TELEGRAM_BATCH_MAX_BYTES=1000000",
        "TELEGRAM_BATCH_MAX_POINTS=100",
        "TELEGRAM_BOT_TOKEN_FILE=/var/lib/edgewatch/telegram_bot_token",
        "TELEGRAM_CHAT_ID=-1001234567890",
    }
    assert expected.issubset(set(bootstrap.splitlines()))
    assert TOKEN not in bootstrap

    token_path = bundle_dir / "telegram_bot_token"
    assert token_path.read_text() == f"{TOKEN}\n"
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600
    authorized_key_path = bundle_dir / "authorized_key"
    assert authorized_key_path.read_text() == f"{SSH_PUBLIC_KEY}\n"
    assert stat.S_IMODE(authorized_key_path.stat().st_mode) == 0o644
    control_authorized_key_path = bundle_dir / "control_authorized_key"
    assert control_authorized_key_path.read_text() == f"{SSH_PUBLIC_KEYS['ssh-rsa']}\n"
    assert stat.S_IMODE(control_authorized_key_path.stat().st_mode) == 0o644
    ota_key_path = bundle_dir / "ota_keys" / "edgewatch-release.pem"
    assert ota_key_path.read_text(encoding="ascii") == OTA_PUBLIC_KEY
    assert stat.S_IMODE(ota_key_path.stat().st_mode) == 0o644


def test_manifest_is_deterministic_and_contains_no_secret_derived_data(tmp_path: Path) -> None:
    manifests = []
    public_keys = (
        SSH_PUBLIC_KEY,
        SSH_PUBLIC_KEYS["ssh-rsa"],
    )
    for index, token in enumerate((TOKEN, "987654321:a-different-secret")):
        bundle = generate_bundle(
            device_id="well-001",
            telegram_chat_id="-1001234567890",
            bot_token_file=_token_file(tmp_path / f"source-{index}", token),
            ssh_public_key_file=_ssh_public_key_file(tmp_path / f"source-{index}", public_keys[index]),
            control_ssh_public_key_file=_control_ssh_public_key_file(
                tmp_path / f"source-{index}", public_keys[index]
            ),
            ota_public_key_file=_ota_public_key_file(tmp_path / f"source-{index}"),
            output_dir=tmp_path / f"output-{index}",
        )
        manifests.append((bundle / "provisioning-manifest.json").read_text())

    assert manifests[0] == manifests[1]
    manifest = json.loads(manifests[0])
    assert manifest["schema_version"] == 1
    assert manifest["image_family"] == "fleet-image-v1"
    assert manifest["device_id"] == "well-001"
    assert manifest["manifest_contains_secrets"] is False
    assert TOKEN not in manifests[0]
    assert "a-different-secret" not in manifests[0]
    assert SSH_PUBLIC_KEY not in manifests[0]
    assert public_keys[1] not in manifests[0]
    assert manifest["files"]["authorized_key"] == "edgewatch/authorized_key"
    assert manifest["files"]["control_authorized_key"] == "edgewatch/control_authorized_key"
    assert manifest["files"]["ota_public_key"] == "edgewatch/ota_keys/edgewatch-release.pem"
    assert manifest["ota_public_key_id"] == "edgewatch-release"
    assert manifest["ota_public_key_sha256"] == hashlib.sha256(OTA_PUBLIC_KEY.encode("ascii")).hexdigest()


def test_eco_power_profile_is_rendered_in_bundle_and_manifest(tmp_path: Path) -> None:
    bundle = generate_bundle(
        device_id="pump-17",
        telegram_chat_id="12345",
        bot_token_file=_token_file(tmp_path),
        ssh_public_key_file=_ssh_public_key_file(tmp_path),
        control_ssh_public_key_file=_control_ssh_public_key_file(tmp_path),
        ota_public_key_file=_ota_public_key_file(tmp_path),
        output_dir=tmp_path / "output",
        power_profile="eco",
    )

    assert "RUNTIME_POWER_MODE=eco" in (bundle / "bootstrap.env").read_text().splitlines()
    assert json.loads((bundle / "provisioning-manifest.json").read_text())["power_profile"] == "eco"


@pytest.mark.parametrize(
    "device_id",
    ["", "UPPERCASE", "-leading", "trailing-", "contains.dot", "two words", "a" * 64],
)
def test_device_id_must_be_a_safe_hostname_label(device_id: str) -> None:
    with pytest.raises(ProvisioningError, match="hostname label"):
        render_bootstrap_env(device_id=device_id, telegram_chat_id="123")


@pytest.mark.parametrize(
    "public_key",
    [
        "",
        "ssh-ed25519 ZWRnZXdhdGNo\nssh-rsa c2Vjb25k",
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        "sk-ssh-ed25519@openssh.com ZWRnZXdhdGNo",
        "ssh-ed25519 not-base64!",
        "ssh-ed25519\tZWRnZXdhdGNo",
    ],
)
def test_ssh_public_key_rejects_unsafe_or_invalid_content(tmp_path: Path, public_key: str) -> None:
    with pytest.raises(ProvisioningError, match="SSH public key"):
        generate_bundle(
            device_id="well-001",
            telegram_chat_id="123",
            bot_token_file=_token_file(tmp_path),
            ssh_public_key_file=_ssh_public_key_file(tmp_path, public_key),
            control_ssh_public_key_file=_control_ssh_public_key_file(tmp_path),
            output_dir=tmp_path / "output",
        )


@pytest.mark.parametrize("key_type", ["ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256"])
def test_supported_ssh_public_key_types_are_accepted(tmp_path: Path, key_type: str) -> None:
    public_key = SSH_PUBLIC_KEYS[key_type]

    bundle = generate_bundle(
        device_id="well-001",
        telegram_chat_id="123",
        bot_token_file=_token_file(tmp_path),
        ssh_public_key_file=_ssh_public_key_file(tmp_path, public_key),
        control_ssh_public_key_file=_control_ssh_public_key_file(tmp_path, public_key),
        ota_public_key_file=_ota_public_key_file(tmp_path),
        output_dir=tmp_path / "output",
    )

    assert (bundle / "authorized_key").read_text() == f"{public_key}\n"


def test_ssh_public_key_rejects_type_payload_mismatch(tmp_path: Path) -> None:
    ed25519_payload = SSH_PUBLIC_KEYS["ssh-ed25519"].split()[1]
    mismatched_key = f"ssh-rsa {ed25519_payload} operator@example.com"

    with pytest.raises(ProvisioningError, match="SSH public key payload"):
        generate_bundle(
            device_id="well-001",
            telegram_chat_id="123",
            bot_token_file=_token_file(tmp_path),
            ssh_public_key_file=_ssh_public_key_file(tmp_path, mismatched_key),
            control_ssh_public_key_file=_control_ssh_public_key_file(tmp_path),
            output_dir=tmp_path / "output",
        )


def test_ota_trust_anchor_rejects_private_key_material(tmp_path: Path) -> None:
    with pytest.raises(ProvisioningError, match="public key"):
        generate_bundle(
            device_id="well-001",
            telegram_chat_id="123",
            bot_token_file=_token_file(tmp_path),
            ssh_public_key_file=_ssh_public_key_file(tmp_path),
            control_ssh_public_key_file=_control_ssh_public_key_file(tmp_path),
            ota_public_key_file=_ota_public_key_file(
                tmp_path, "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----\n"
            ),
            output_dir=tmp_path / "output",
        )


def test_nonempty_output_requires_force(tmp_path: Path) -> None:
    output_dir = tmp_path / "sd-boot"
    output_dir.mkdir()
    unrelated = output_dir / "config.txt"
    unrelated.write_text("preserve me")

    with pytest.raises(ProvisioningError, match="not empty"):
        generate_bundle(
            device_id="well-001",
            telegram_chat_id="123",
            bot_token_file=_token_file(tmp_path),
            ssh_public_key_file=_ssh_public_key_file(tmp_path),
            control_ssh_public_key_file=_control_ssh_public_key_file(tmp_path),
            ota_public_key_file=_ota_public_key_file(tmp_path),
            output_dir=output_dir,
        )

    assert unrelated.read_text() == "preserve me"
    assert not (output_dir / "edgewatch").exists()


def test_force_replaces_only_exact_edgewatch_directory(tmp_path: Path) -> None:
    output_dir = tmp_path / "sd-boot"
    old_bundle = output_dir / "edgewatch"
    old_bundle.mkdir(parents=True)
    (old_bundle / "stale").write_text("old")
    unrelated = output_dir / "config.txt"
    unrelated.write_text("preserve me")

    bundle = generate_bundle(
        device_id="well-002",
        telegram_chat_id="123",
        bot_token_file=_token_file(tmp_path),
        ssh_public_key_file=_ssh_public_key_file(tmp_path),
        control_ssh_public_key_file=_control_ssh_public_key_file(tmp_path),
        ota_public_key_file=_ota_public_key_file(tmp_path),
        output_dir=output_dir,
        force=True,
    )

    assert not (bundle / "stale").exists()
    assert unrelated.read_text() == "preserve me"
    assert "EDGEWATCH_DEVICE_ID=well-002" in (bundle / "bootstrap.env").read_text()


def test_force_restores_old_bundle_when_staged_rename_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "sd-boot"
    old_bundle = output_dir / "edgewatch"
    old_bundle.mkdir(parents=True)
    old_bootstrap = old_bundle / "bootstrap.env"
    old_bootstrap.write_text("EDGEWATCH_DEVICE_ID=old-device\n")
    real_rename = Path.rename
    rename_calls = 0

    def fail_install_rename(source: Path, target: Path) -> Path:
        nonlocal rename_calls
        rename_calls += 1
        if rename_calls == 2:
            raise OSError("simulated staged rename failure")
        return real_rename(source, target)

    monkeypatch.setattr(Path, "rename", fail_install_rename)

    with pytest.raises(OSError, match="simulated staged rename failure"):
        generate_bundle(
            device_id="well-002",
            telegram_chat_id="123",
            bot_token_file=_token_file(tmp_path),
            ssh_public_key_file=_ssh_public_key_file(tmp_path),
            control_ssh_public_key_file=_control_ssh_public_key_file(tmp_path),
            ota_public_key_file=_ota_public_key_file(tmp_path),
            output_dir=output_dir,
            force=True,
        )

    assert old_bootstrap.read_text() == "EDGEWATCH_DEVICE_ID=old-device\n"
    assert not list(output_dir.glob(".edgewatch-backup-*"))


def test_force_refuses_symlink_as_edgewatch_replace_target(tmp_path: Path) -> None:
    output_dir = tmp_path / "sd-boot"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    output_dir.mkdir()
    (output_dir / "edgewatch").symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(ProvisioningError, match="real directory"):
        generate_bundle(
            device_id="well-001",
            telegram_chat_id="123",
            bot_token_file=_token_file(tmp_path),
            ssh_public_key_file=_ssh_public_key_file(tmp_path),
            control_ssh_public_key_file=_control_ssh_public_key_file(tmp_path),
            ota_public_key_file=_ota_public_key_file(tmp_path),
            output_dir=output_dir,
            force=True,
        )

    assert not any(elsewhere.iterdir())


def test_cli_reports_path_without_printing_token(tmp_path: Path) -> None:
    output_dir = tmp_path / "sd-boot"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--device-id",
            "well-001",
            "--telegram-chat-id",
            "-1001234567890",
            "--bot-token-file",
            str(_token_file(tmp_path)),
            "--ssh-public-key-file",
            str(_ssh_public_key_file(tmp_path)),
            "--control-ssh-public-key-file",
            str(_control_ssh_public_key_file(tmp_path)),
            "--ota-public-key-file",
            str(_ota_public_key_file(tmp_path)),
            "--output-dir",
            str(output_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert str(output_dir / "edgewatch") in result.stdout
    assert TOKEN not in result.stdout
    assert TOKEN not in result.stderr


def test_generated_profiles_require_ota_trust(tmp_path: Path) -> None:
    with pytest.raises(ProvisioningError, match="OTA public trust key"):
        generate_bundle(
            device_id="well-001",
            telegram_chat_id="123",
            bot_token_file=_token_file(tmp_path),
            ssh_public_key_file=_ssh_public_key_file(tmp_path),
            control_ssh_public_key_file=_control_ssh_public_key_file(tmp_path),
            output_dir=tmp_path / "output",
        )


def test_gateway_bundle_keeps_telemetry_and_defers_controller_key(tmp_path: Path) -> None:
    chat_id = "-1001234567890"
    bundle = generate_bundle(
        device_id="gateway-001",
        profile="gateway",
        telegram_chat_id=chat_id,
        bot_token_file=_token_file(tmp_path),
        ssh_public_key_file=_ssh_public_key_file(tmp_path),
        ota_public_key_file=_ota_public_key_file(tmp_path),
        output_dir=tmp_path / "output",
        **_gateway_inputs(tmp_path / "gateway-inputs", chat_id=chat_id),
    )

    bootstrap = (bundle / "bootstrap.env").read_text(encoding="utf-8")
    assert "BOOTSTRAP_PROFILE=gateway" in bootstrap
    assert "TELEGRAM_BOT_TOKEN_FILE=/etc/edgewatch-controller/telemetry-bot-token" in bootstrap
    assert "BOOTSTRAP_CONTROL_SSH_AUTHORIZED_KEY_FILE=" not in bootstrap
    assert not (bundle / "control_authorized_key").exists()
    for name in (
        "lorawan-gateway.yaml",
        "lorawan-registry.yaml",
        "lorawan-radio-ingress.yaml",
        "sx1302-adapter.yaml",
        "gateway-power.env",
    ):
        assert stat.S_IMODE((bundle / name).stat().st_mode) == 0o600
    assert "radio_ingress_file: /etc/edgewatch-controller/lorawan-radio-ingress.yaml" in (
        bundle / "lorawan-gateway.yaml"
    ).read_text(encoding="utf-8")
    assert "adapter_config_file: /etc/edgewatch-controller/sx1302-adapter.yaml" in (
        bundle / "lorawan-radio-ingress.yaml"
    ).read_text(encoding="utf-8")
    manifest_text = (bundle / "provisioning-manifest.json").read_text(encoding="utf-8")
    assert "000102030405060708090a0b0c0d0e0f" not in manifest_text
    assert json.loads(manifest_text)["files"]["lorawan_registry"] == ("edgewatch/lorawan-registry.yaml")


def test_camera_bundle_is_local_only_and_requires_gateway_controller_key(tmp_path: Path) -> None:
    camera_inputs = _camera_inputs(tmp_path / "camera-inputs", device_id="camera-001")
    common = {
        "device_id": "camera-001",
        "profile": "camera-satellite",
        "control_ssh_public_key_file": _control_ssh_public_key_file(tmp_path),
        "ota_public_key_file": _ota_public_key_file(tmp_path),
        "output_dir": tmp_path / "output",
        **camera_inputs,
    }
    bundle = generate_bundle(**common)

    bootstrap = (bundle / "bootstrap.env").read_text(encoding="utf-8")
    assert "BOOTSTRAP_PROFILE=camera-satellite" in bootstrap
    assert "BOOTSTRAP_AGENT_ENV_PATH=/etc/edgewatch/agent.env" in bootstrap
    assert "EDGEWATCH_TELEMETRY_TRANSPORT=none" in bootstrap
    assert "EDGEWATCH_OTA_GATEWAY_CACHE_URL=http://10.42.0.1:8091" in bootstrap
    assert "EDGEWATCH_ASSET_BUNDLE_APPLY_CMD=" in bootstrap
    assert "/opt/edgewatch/current/scripts/apply_model_bundle.py" in bootstrap
    assert "EDGEWATCH_ENABLE_OTA_APPLY=false" in bootstrap
    assert "EDGEWATCH_POWER_STATE_PATH=/var/lib/edgewatch-camera-satellite/ota-power-state.json" in bootstrap
    assert "BOOTSTRAP_CONTROL_SSH_AUTHORIZED_KEY_FILE=" in bootstrap
    assert "TELEGRAM" not in bootstrap
    assert "BOOTSTRAP_LTE_" not in bootstrap
    assert not (bundle / "telegram_bot_token").exists()
    runtime = (bundle / "camera-satellite.env").read_text(encoding="utf-8")
    assert (
        "EDGEWATCH_SATELLITE_POWEROFF_REQUEST_PATH=/run/edgewatch-camera-satellite/poweroff.request"
    ) in runtime
    manifest_text = (bundle / "provisioning-manifest.json").read_text(encoding="utf-8")
    assert "camera-secret" not in manifest_text
    assert json.loads(manifest_text)["files"]["camera_credentials"] == (
        "edgewatch/camera-rtsp-credentials.json"
    )

    without_initial_model = dict(common)
    without_initial_model.pop("initial_model_bundle_file")
    without_initial_model["output_dir"] = tmp_path / "missing-initial-model"
    with pytest.raises(ProvisioningError, match="initial signed model bundle"):
        generate_bundle(**without_initial_model)

    missing_controller = dict(common)
    missing_controller["output_dir"] = tmp_path / "missing-controller"
    missing_controller["control_ssh_public_key_file"] = None
    with pytest.raises(ProvisioningError, match="gateway controller SSH public key"):
        generate_bundle(**missing_controller)


def test_gateway_private_inputs_must_have_exact_mode_0600(tmp_path: Path) -> None:
    chat_id = "-1001234567890"
    inputs = _gateway_inputs(tmp_path / "gateway-inputs", chat_id=chat_id)
    inputs["lorawan_registry_file"].chmod(0o640)

    with pytest.raises(ProvisioningError, match="mode 0600"):
        generate_bundle(
            device_id="gateway-001",
            profile="gateway",
            telegram_chat_id=chat_id,
            bot_token_file=_token_file(tmp_path),
            ssh_public_key_file=_ssh_public_key_file(tmp_path),
            ota_public_key_file=_ota_public_key_file(tmp_path),
            output_dir=tmp_path / "output",
            **inputs,
        )
