from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
IMAGE_ROOT = ROOT / "deploy" / "rpi" / "image"
BUILD_SCRIPT = IMAGE_ROOT / "build.sh"


def _pins() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (IMAGE_ROOT / "pins.env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


def test_builder_and_base_are_immutable_inputs() -> None:
    pins = _pins()

    assert pins["RPI_IMAGE_GEN_REPOSITORY"] == "https://github.com/raspberrypi/rpi-image-gen.git"
    assert re.fullmatch(r"[0-9a-f]{40}", pins["RPI_IMAGE_GEN_REVISION"])
    assert pins["RPI_OS_SUITE"] == "bookworm"
    assert pins["RPI_OS_ARCH"] == "arm64"
    assert pins["DEFAULT_DEVICE_LAYER"] == "rpizero2w"
    assert pins["DEFAULT_IMAGE_PROFILE"] == "standalone"
    assert pins["CHIRPSTACK_SQLITE_VERSION"].startswith("4.19.")
    assert pins["LITERT_VERSION"] == "2.1.6"
    for key in (
        "CHIRPSTACK_SQLITE_SHA256",
        "PAHO_MQTT_SHA256",
        "LITERT_SHA256",
        "BACKPORTS_STRENUM_SHA256",
    ):
        assert re.fullmatch(r"[0-9a-f]{64}", pins[key])


def test_image_config_is_arm64_lite_class_and_secret_free() -> None:
    config_text = (IMAGE_ROOT / "config" / "fleet-image-v1.yaml.in").read_text()
    parsed = yaml.safe_load(
        config_text.replace("@SOURCE_DATE_EPOCH@", "1")
        .replace("@DEVICE_LAYER@", "rpizero2w")
        .replace("@IMAGE_NAME@", "contract-test")
        .replace("@PROFILE_LAYER@", "edgewatch-standalone-v1")
    )

    assert parsed["layer"]["base"] == "bookworm-minbase"
    assert parsed["layer"]["edgewatch"] == "edgewatch-fleet-v1"
    assert parsed["layer"]["profile"] == "edgewatch-standalone-v1"
    assert parsed["ssh"]["pubkey_only"] == "y"
    assert parsed["device"]["hostname"] == "edgewatch-unprovisioned"
    assert parsed["device"]["user1"] == "ryne"
    assert parsed["device"]["user1sudo"] == "nopasswd"
    forbidden = ("DEVICE_TOKEN", "BOT_TOKEN", "AUTH_KEY", "LTE_PASSWORD", "PRIVATE KEY")
    all_source = "\n".join(path.read_text() for path in IMAGE_ROOT.rglob("*") if path.is_file())
    assert not any(secret in config_text for secret in forbidden)
    assert "-----BEGIN PRIVATE KEY-----" not in all_source


def test_layer_bakes_runtime_and_clears_cloned_identity() -> None:
    layer = (IMAGE_ROOT / "layer" / "edgewatch-fleet-v1.yaml").read_text()
    identity_service = (IMAGE_ROOT / "assets" / "edgewatch-firstboot-identity.service").read_text()

    for package in (
        "network-manager",
        "modemmanager",
        "openssl",
        "python3-requests",
        "python3-yaml",
    ):
        assert f"- {package}" in layer
    assert "scripts/rpi_bootstrap.py" in layer
    assert 'rm -f "$1"/etc/ssh/ssh_host_*' in layer
    assert ': > "$1/etc/machine-id"' in layer
    assert "ConditionFirstBoot=yes" in identity_service
    assert "ssh-keygen -A" in identity_service
    assert "systemd-machine-id-setup" in identity_service

    build_script = BUILD_SCRIPT.read_text()
    assert "scripts/apply_model_bundle.py" in build_script


def test_hardware_watchdog_policy_is_present_but_opt_in() -> None:
    watchdog = (IMAGE_ROOT / "assets" / "90-edgewatch-watchdog.conf.disabled").read_text()
    layer = (IMAGE_ROOT / "layer" / "edgewatch-fleet-v1.yaml").read_text()

    assert "RuntimeWatchdogSec=30s" in watchdog
    assert "RebootWatchdogSec=2min" in watchdog
    assert "90-edgewatch-watchdog.conf.disabled" in layer
    assert "/etc/systemd/system.conf.d/90-edgewatch-watchdog.conf" not in layer


def test_gateway_and_camera_profiles_pin_native_runtime_dependencies() -> None:
    gateway = (IMAGE_ROOT / "layer" / "edgewatch-gateway-v1.yaml").read_text()
    satellite = (IMAGE_ROOT / "layer" / "edgewatch-camera-satellite-v1.yaml").read_text()
    script = BUILD_SCRIPT.read_text()

    for package in ("mosquitto", "redis-server", "sqlite3"):
        assert f"- {package}" in gateway
    assert "chirpstack-sqlite.deb" in gateway
    assert "paho-mqtt.whl" in gateway
    for package in ("ffmpeg", "python3-numpy", "v4l-utils"):
        assert f"- {package}" in satellite
    assert "litert.whl" in satellite
    assert "--no-deps --no-index" in satellite
    assert "download_verified" in script
    assert "gateway profile requires rpi4 or rpi5" in script
    assert '"image_profile"' in script


def test_build_wrapper_is_fail_fast_and_emits_supply_chain_metadata() -> None:
    subprocess.run(["bash", "-n", str(BUILD_SCRIPT)], check=True)
    pins = subprocess.run(
        [str(BUILD_SCRIPT), "--print-pins"], check=True, capture_output=True, text=True
    ).stdout
    script = BUILD_SCRIPT.read_text()

    assert "set -Eeuo pipefail" in script
    assert "image inputs must be committed and clean before building" in script
    assert " archive --format=tar " in script
    assert "grep -Eq" not in script
    assert "grep -aEq" not in script
    assert "sha256sum" in script
    assert '"schema_version": 1' in script
    assert '"contains_device_secrets": False' in script
    assert "revision=" in pins and "arch=arm64" in pins
    assert "default_profile=standalone" in pins


def test_prs_validate_contract_but_only_manual_dispatch_builds_image() -> None:
    workflow = (ROOT / ".github" / "workflows" / "build-rpi-image.yml").read_text()

    assert "pull_request:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "if: github.event_name == 'workflow_dispatch'" in workflow
    assert "ARM64" in workflow
    assert "camera-satellite" in workflow
    assert '--profile "$IMAGE_PROFILE"' in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "*.img.xz.sha256" in workflow
    assert "*.manifest.json" in workflow


def test_release_docs_do_not_promise_an_unexported_sbom() -> None:
    readme = (IMAGE_ROOT / "README.md").read_text()
    normalized_readme = " ".join(readme.split())
    workflow = (ROOT / ".github" / "workflows" / "build-rpi-image.yml").read_text()

    assert "upstream-generated SBOM" not in readme
    assert "does not currently export or attest an SBOM" in normalized_readme
    assert "*.sbom" not in workflow.lower()
    assert "*.spdx" not in workflow.lower()


def test_docs_define_boot_staging_and_telegram_limitations() -> None:
    image_readme = (IMAGE_ROOT / "README.md").read_text()
    tutorial = (ROOT / "docs" / "TUTORIALS" / "RPI_ZERO_TOUCH_BOOTSTRAP.md").read_text()

    for document in (image_readme, tutorial):
        normalized_document = " ".join(document.split())
        assert "FAT" in normalized_document
        assert "root-owned" in normalized_document
        assert (
            "missing-heartbeat" in normalized_document
            or "missing heartbeat" in normalized_document
            or "stops sending heartbeats" in normalized_document
        )
        assert "shared" in normalized_document and "bot" in normalized_document
