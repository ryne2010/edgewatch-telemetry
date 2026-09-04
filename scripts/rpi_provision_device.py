#!/usr/bin/env python3
"""Build a secret-safe per-device boot-partition provisioning bundle."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import ipaddress
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.parse
import uuid
from collections.abc import Sequence
from pathlib import Path

import yaml


DEFAULT_REPO_DIR = Path("/opt/edgewatch/app")
DEFAULT_LTE_APN = "hologram"
BOOT_EDGEWATCH_DIR = Path("edgewatch")
BOOTSTRAP_ENV_NAME = "bootstrap.env"
TELEGRAM_TOKEN_NAME = "telegram_bot_token"
SSH_AUTHORIZED_KEY_NAME = "authorized_key"
CONTROL_SSH_AUTHORIZED_KEY_NAME = "control_authorized_key"
OTA_KEYS_DIR_NAME = "ota_keys"
MANIFEST_NAME = "provisioning-manifest.json"
PROFILES = ("standalone", "gateway", "camera-satellite")
LORAWAN_GATEWAY_CONFIG_NAME = "lorawan-gateway.yaml"
LORAWAN_REGISTRY_NAME = "lorawan-registry.yaml"
LORAWAN_RADIO_INGRESS_NAME = "lorawan-radio-ingress.yaml"
LORAWAN_VENDOR_CONFIG_NAME = "sx1302-adapter.yaml"
GATEWAY_POWER_ENV_NAME = "gateway-power.env"
CAMERA_RUNTIME_ENV_NAME = "camera-satellite.env"
CAMERA_CREDENTIALS_NAME = "camera-rtsp-credentials.json"
MODEL_KEYS_DIR_NAME = "model_keys"
INITIAL_MODEL_BUNDLE_NAME = "initial-model.tar.gz"
DEFAULT_OTA_GATEWAY_CACHE_URL = "http://10.42.0.1:8091"
HOSTNAME_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
ECDSA_KEY_TYPE_PATTERN = re.compile(r"ecdsa-sha2-[A-Za-z0-9._+-]+\Z")
SAFE_KEY_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")

_GATEWAY_POWER_ENV_KEYS = frozenset(
    {
        "CELLULAR_INTERFACE",
        "EDGEWATCH_GATEWAY_LTE_HOLD_DIR",
        "EDGEWATCH_GATEWAY_LTE_MAX_WINDOW_S",
        "EDGEWATCH_GATEWAY_LTE_MAX_HELD_WINDOW_S",
        "EDGEWATCH_GATEWAY_LTE_MIN_WINDOW_S",
        "EDGEWATCH_GATEWAY_LTE_POWER_MODE",
        "EDGEWATCH_GATEWAY_LTE_POWER_STATE_PATH",
        "EDGEWATCH_GATEWAY_LTE_TRANSITION_TIMEOUT_S",
        "EDGEWATCH_GATEWAY_LTE_TRIGGER_PATH",
        "EDGEWATCH_GATEWAY_LTE_WINDOW_INTERVAL_S",
        "EDGEWATCH_DEADMAN_HEARTBEAT_URL_FILE",
        "EDGEWATCH_DEADMAN_INTERVAL_S",
        "EDGEWATCH_DEADMAN_REQUEST_TIMEOUT_S",
        "EDGEWATCH_DEADMAN_MAX_ATTEMPTS",
        "EDGEWATCH_DEADMAN_BACKOFF_BASE_S",
    }
)
_CAMERA_RUNTIME_ENV_KEYS = frozenset(
    {
        "EDGEWATCH_CAMERA_ID",
        "EDGEWATCH_CURRENT_SYMLINK",
        "EDGEWATCH_DEVICE_ID",
        "EDGEWATCH_EVENT_REASON",
        "EDGEWATCH_FFMPEG_BINARY",
        "EDGEWATCH_FFPROBE_BINARY",
        "EDGEWATCH_HARDWARE_MODEL",
        "EDGEWATCH_INFERENCE_MODE",
        "EDGEWATCH_INFERENCE_PROMOTION_FILE",
        "EDGEWATCH_MODEL_CURRENT_SYMLINK",
        "EDGEWATCH_MODEL_KEYRING_DIR",
        "EDGEWATCH_MODEL_LITERT_VERSION",
        "EDGEWATCH_MODEL_RELEASES_ROOT",
        "EDGEWATCH_RELEASES_ROOT",
        "EDGEWATCH_SATELLITE_CAPTURE_TIMEOUT_S",
        "EDGEWATCH_SATELLITE_EVIDENCE_DIR",
        "EDGEWATCH_SATELLITE_EVIDENCE_MAX_BYTES",
        "EDGEWATCH_SATELLITE_EVENT_DURATION_S",
        "EDGEWATCH_SATELLITE_GATE_STATE_PATH",
        "EDGEWATCH_SATELLITE_LOCK_PATH",
        "EDGEWATCH_SATELLITE_PREPROCESS_TIMEOUT_S",
        "EDGEWATCH_SATELLITE_POWEROFF_REQUEST_PATH",
        "EDGEWATCH_SATELLITE_READINESS_TTL_S",
        "EDGEWATCH_SATELLITE_READY_PATH",
        "EDGEWATCH_SATELLITE_RESULT_PATH",
    }
)


class ProvisioningError(ValueError):
    """Raised when a safe provisioning bundle cannot be generated."""


def validate_device_id(device_id: str) -> str:
    """Require a device id that is also a safe single-label Linux hostname."""

    if not HOSTNAME_PATTERN.fullmatch(device_id):
        raise ProvisioningError(
            "device id must be a lowercase hostname label (1-63 characters; "
            "letters, digits, and interior hyphens only)"
        )
    return device_id


def _validate_text(value: str, label: str) -> str:
    if not value or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ProvisioningError(f"{label} must be nonempty and contain no control characters")
    return value


def _format_env_value(value: str) -> str:
    if value and all(character.isalnum() or character in "-_./:@+" for character in value):
        return value
    return shlex.quote(value)


def _validate_ota_gateway_cache_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError as exc:
        raise ProvisioningError("OTA gateway cache URL is invalid") from exc
    if (
        parsed.scheme != "http"
        or parsed.username is not None
        or parsed.password is not None
        or port is None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or address.version != 4
        or not address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    ):
        raise ProvisioningError(
            "OTA gateway cache URL must be an HTTP URL on a private maintenance IPv4 address with an explicit port"
        )
    return value.rstrip("/")


def render_bootstrap_env(
    *,
    device_id: str,
    telegram_chat_id: str | None = None,
    repo_dir: Path = DEFAULT_REPO_DIR,
    lte_apn: str = DEFAULT_LTE_APN,
    power_profile: str = "continuous",
    ota_key_id: str | None = None,
    profile: str = "standalone",
    model_key_id: str | None = None,
    has_initial_model_bundle: bool = False,
    has_ssh_authorized_key: bool = True,
    has_control_ssh_authorized_key: bool = True,
    ota_gateway_cache_url: str = DEFAULT_OTA_GATEWAY_CACHE_URL,
) -> str:
    validate_device_id(device_id)
    if profile not in PROFILES:
        raise ProvisioningError(f"profile must be one of: {', '.join(PROFILES)}")
    if profile != "camera-satellite":
        if telegram_chat_id is None:
            raise ProvisioningError("Telegram chat id is required for standalone and gateway profiles")
        _validate_text(telegram_chat_id, "Telegram chat id")
    _validate_text(str(repo_dir), "repository directory")
    if profile != "camera-satellite":
        _validate_text(lte_apn, "LTE APN")
    if power_profile not in {"continuous", "eco"}:
        raise ProvisioningError("power profile must be 'continuous' or 'eco'")
    if ota_key_id is not None and SAFE_KEY_ID_PATTERN.fullmatch(ota_key_id) is None:
        raise ProvisioningError("OTA key id must contain only letters, digits, dot, underscore, or hyphen")
    if model_key_id is not None and SAFE_KEY_ID_PATTERN.fullmatch(model_key_id) is None:
        raise ProvisioningError("model key id must contain only letters, digits, dot, underscore, or hyphen")

    values = {
        "BOOTSTRAP_AGENT_ENV_PATH": "/etc/edgewatch/agent.env",
        "BOOTSTRAP_CURRENT_SYMLINK": "/opt/edgewatch/current",
        "BOOTSTRAP_IMAGE_PROFILE_PATH": "/etc/edgewatch-image-profile",
        "BOOTSTRAP_PROFILE": profile,
        "BOOTSTRAP_REPO_DIR": str(repo_dir),
        "BOOTSTRAP_SSH_USER": "ryne",
        "EDGEWATCH_DEVICE_ID": device_id,
        "EDGEWATCH_CURRENT_SYMLINK": "/opt/edgewatch/current",
        "EDGEWATCH_LOCAL_OTA_STATE_PATH": f"/var/lib/edgewatch/local_ota_{device_id}.json",
        "EDGEWATCH_RUNTIME_DEPENDENCY_PATH": "/opt/edgewatch/current/agent/requirements.txt",
        "EDGEWATCH_OTA_POWER_EVIDENCE_MAX_AGE_S": "300",
        "EDGEWATCH_OTA_CACHE_DIR": "/opt/edgewatch/update-cache",
        "EDGEWATCH_OTA_KEYRING_DIR": "/opt/edgewatch/keys",
        "EDGEWATCH_RELEASES_ROOT": "/opt/edgewatch/releases",
        "EDGEWATCH_OTA_RUNTIME_PROFILE": profile,
        "EDGEWATCH_SYSTEM_IMAGE_APPLY_ENABLED": "false",
    }
    if has_ssh_authorized_key:
        values["BOOTSTRAP_SSH_AUTHORIZED_KEY_FILE"] = "/boot/firmware/edgewatch/authorized_key"
    if has_control_ssh_authorized_key:
        values["BOOTSTRAP_CONTROL_SSH_AUTHORIZED_KEY_FILE"] = (
            "/boot/firmware/edgewatch/control_authorized_key"
        )
    if profile in {"standalone", "gateway"}:
        token_destination = (
            "/etc/edgewatch-controller/telemetry-bot-token"
            if profile == "gateway"
            else "/var/lib/edgewatch/telegram_bot_token"
        )
        values.update(
            {
                "ALERT_SAMPLE_INTERVAL_S": "600",
                "BOOTSTRAP_AGENT_ENTRYPOINT": "/opt/edgewatch/current/agent/edgewatch_agent.py",
                "BOOTSTRAP_AGENT_WORKDIR": "/opt/edgewatch/current/agent",
                "BOOTSTRAP_LTE_APN": lte_apn,
                "BOOTSTRAP_TELEGRAM_BOT_TOKEN_FILE": ("/boot/firmware/edgewatch/telegram_bot_token"),
                "BUFFER_SQLITE_SYNCHRONOUS": "FULL",
                "CELLULAR_INTERFACE": "wwan0",
                "CELLULAR_METRICS_ENABLED": "true",
                "CELLULAR_MODEM_POLL_INTERVAL_S": "300",
                "CELLULAR_USAGE_POLL_INTERVAL_S": "300",
                "CELLULAR_WATCHDOG_ENABLED": "false",
                "EDGEWATCH_COST_CAP_URGENT_RESERVE_BYTES": "262144",
                "EDGEWATCH_TELEMETRY_TRANSPORT": "telegram",
                "HEARTBEAT_INTERVAL_S": "3600",
                "MAX_BYTES_PER_DAY": "5000000",
                "RUNTIME_POWER_MODE": power_profile,
                "SAMPLE_INTERVAL_S": "600",
                "SENSOR_BACKEND": "none",
                "TELEGRAM_BATCH_ENABLED": "true",
                "TELEGRAM_BATCH_MAX_AGE_S": "3600",
                "TELEGRAM_BATCH_MAX_BYTES": "1000000",
                "TELEGRAM_BATCH_MAX_POINTS": "100",
                "TELEGRAM_BOT_TOKEN_FILE": token_destination,
                "TELEGRAM_CHAT_ID": telegram_chat_id or "",
            }
        )
    else:
        if model_key_id is None:
            raise ProvisioningError("camera-satellite profile requires a model public key")
        if not has_initial_model_bundle:
            raise ProvisioningError("camera-satellite profile requires an initial signed model bundle")
        ota_gateway_cache_url = _validate_ota_gateway_cache_url(ota_gateway_cache_url)
        values.update(
            {
                "BOOTSTRAP_CAMERA_CREDENTIALS_FILE": (f"/boot/firmware/edgewatch/{CAMERA_CREDENTIALS_NAME}"),
                "BOOTSTRAP_CAMERA_RUNTIME_ENV_FILE": (f"/boot/firmware/edgewatch/{CAMERA_RUNTIME_ENV_NAME}"),
                "BOOTSTRAP_MODEL_PUBLIC_KEY_FILE": (
                    f"/boot/firmware/edgewatch/{MODEL_KEYS_DIR_NAME}/{model_key_id}.pem"
                ),
                "BOOTSTRAP_MODEL_PUBLIC_KEY_ID": model_key_id,
                "EDGEWATCH_OTA_GATEWAY_CACHE_URL": ota_gateway_cache_url,
                "EDGEWATCH_ASSETS_ROOT": "/opt/edgewatch/assets",
                "EDGEWATCH_ASSET_BUNDLE_APPLY_CMD": (
                    "/opt/edgewatch/app/.venv/bin/python /opt/edgewatch/current/scripts/apply_model_bundle.py"
                ),
                "EDGEWATCH_ENABLE_OTA_APPLY": "false",
                "EDGEWATCH_POWER_STATE_PATH": ("/var/lib/edgewatch-camera-satellite/ota-power-state.json"),
                "EDGEWATCH_TELEMETRY_TRANSPORT": "none",
            }
        )
        if has_initial_model_bundle:
            values["BOOTSTRAP_INITIAL_MODEL_BUNDLE_FILE"] = (
                f"/boot/firmware/edgewatch/{INITIAL_MODEL_BUNDLE_NAME}"
            )
    if profile == "gateway":
        values.update(
            {
                "BOOTSTRAP_GATEWAY_POWER_ENV_FILE": (f"/boot/firmware/edgewatch/{GATEWAY_POWER_ENV_NAME}"),
                "BOOTSTRAP_GATEWAY_RADIO_STATE_DIR": "/var/lib/edgewatch-gateway",
                "BOOTSTRAP_LORAWAN_GATEWAY_CONFIG_FILE": (
                    f"/boot/firmware/edgewatch/{LORAWAN_GATEWAY_CONFIG_NAME}"
                ),
                "BOOTSTRAP_LORAWAN_RADIO_INGRESS_FILE": (
                    f"/boot/firmware/edgewatch/{LORAWAN_RADIO_INGRESS_NAME}"
                ),
                "BOOTSTRAP_LORAWAN_REGISTRY_FILE": (f"/boot/firmware/edgewatch/{LORAWAN_REGISTRY_NAME}"),
                "BOOTSTRAP_LORAWAN_VENDOR_CONFIG_FILE": (
                    f"/boot/firmware/edgewatch/{LORAWAN_VENDOR_CONFIG_NAME}"
                ),
            }
        )
    if ota_key_id is not None:
        values["BOOTSTRAP_OTA_PUBLIC_KEY_FILE"] = (
            f"/boot/firmware/edgewatch/{OTA_KEYS_DIR_NAME}/{ota_key_id}.pem"
        )
        values["BOOTSTRAP_OTA_PUBLIC_KEY_ID"] = ota_key_id
    lines = [
        "# EdgeWatch fleet-image-v1 per-device provisioning.",
        "# Secrets are stored only in adjacent protected files and imported on first boot.",
        "",
    ]
    lines.extend(f"{key}={_format_env_value(values[key])}" for key in sorted(values))
    return "\n".join(lines) + "\n"


def _read_token(path: Path) -> str:
    if not path.is_file():
        raise ProvisioningError("bot token file must be an existing regular file")
    try:
        token = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise ProvisioningError("bot token file could not be read as UTF-8 text") from exc
    if not token:
        raise ProvisioningError("bot token file must not be empty")
    if any(character.isspace() for character in token):
        raise ProvisioningError("bot token file must contain exactly one token")
    return token


def _read_private_file(path: Path, *, label: str, maximum_bytes: int = 1024 * 1024) -> bytes:
    """Read a local provisioning secret only from an exact mode-0600 regular file."""

    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ProvisioningError(f"{label} must be an existing regular file") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise ProvisioningError(f"{label} must be a regular non-symlink file")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ProvisioningError(f"{label} must have mode 0600")
    if metadata.st_size <= 0 or metadata.st_size > maximum_bytes:
        raise ProvisioningError(f"{label} size is outside the allowed range")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ProvisioningError(f"{label} could not be read") from exc
    if len(payload) != metadata.st_size:
        raise ProvisioningError(f"{label} changed while it was being read")
    return payload


def _parse_strict_env(payload: bytes, *, label: str) -> dict[str, str]:
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ProvisioningError(f"{label} must be UTF-8 text") from exc
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            tokens = shlex.split(line, comments=True, posix=True)
        except ValueError as exc:
            raise ProvisioningError(f"{label} line {line_number} is invalid") from exc
        if len(tokens) != 1 or "=" not in tokens[0]:
            raise ProvisioningError(f"{label} line {line_number} must contain one NAME=value assignment")
        key, value = tokens[0].split("=", 1)
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is None or key in values:
            raise ProvisioningError(f"{label} contains an invalid or duplicate setting: {key}")
        values[key] = value
    return values


def _render_env(values: dict[str, str], *, header: str) -> str:
    return "\n".join([header, *(f"{key}={_format_env_value(values[key])}" for key in sorted(values)), ""])


def _prepare_gateway_inputs(
    *,
    config_file: Path,
    registry_file: Path,
    radio_ingress_file: Path,
    vendor_config_file: Path,
    power_env_file: Path,
    telegram_chat_id: str,
) -> tuple[str, bytes, str, bytes, bytes]:
    from agent.lorawan.config import DeviceRegistry, IdentityConfigError
    from agent.lorawan.service import GatewayServiceConfigError, load_gateway_service_config
    from gateway_runtime.lte_power import GatewayPowerConfigError, load_gateway_power_config

    config_payload = _read_private_file(config_file, label="LoRaWAN gateway config")
    registry_payload = _read_private_file(registry_file, label="LoRaWAN registry")
    radio_payload = _read_private_file(radio_ingress_file, label="LoRaWAN radio ingress config")
    vendor_payload = _read_private_file(
        vendor_config_file,
        label="LoRaWAN vendor adapter config",
    )
    power_payload = _read_private_file(power_env_file, label="gateway power environment")
    try:
        raw_config = yaml.safe_load(config_payload.decode("utf-8"))
        raw_registry = yaml.safe_load(registry_payload.decode("utf-8"))
        raw_radio = yaml.safe_load(radio_payload.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ProvisioningError("LoRaWAN configuration files must contain valid UTF-8 YAML") from exc
    if not isinstance(raw_config, dict) or not all(isinstance(key, str) for key in raw_config):
        raise ProvisioningError("LoRaWAN gateway config must be a YAML mapping")
    if not isinstance(raw_radio, dict) or not all(isinstance(key, str) for key in raw_radio):
        raise ProvisioningError("LoRaWAN radio ingress config must be a YAML mapping")
    try:
        registry = DeviceRegistry.from_mapping(raw_registry)
    except IdentityConfigError as exc:
        raise ProvisioningError("LoRaWAN registry is invalid") from exc
    mqtt = raw_config.get("mqtt")
    delivery = raw_config.get("delivery")
    if not isinstance(mqtt, dict) or not isinstance(delivery, dict):
        raise ProvisioningError("LoRaWAN gateway config requires mqtt and delivery mappings")
    if mqtt.get("password_file") is not None:
        raise ProvisioningError("LoRaWAN MQTT password_file is not supported by this provisioning profile")
    if mqtt.get("username") is not None:
        raise ProvisioningError("LoRaWAN MQTT username is not supported by the local gateway profile")
    application_id = mqtt.get("application_id")
    if registry.application_ids != frozenset({application_id}):
        raise ProvisioningError("LoRaWAN registry application IDs must match the gateway MQTT application")
    configured_chat = str(delivery.get("chat_id", ""))
    if configured_chat != telegram_chat_id:
        raise ProvisioningError("LoRaWAN delivery chat_id must match the existing telemetry channel")

    installed_config = dict(raw_config)
    installed_config["registry_file"] = "/etc/edgewatch-controller/lorawan-registry.yaml"
    installed_config["radio_ingress_file"] = "/etc/edgewatch-controller/lorawan-radio-ingress.yaml"
    installed_config["gateway_store_path"] = "/var/lib/edgewatch-controller/lorawan-gateway.sqlite"
    installed_mqtt = dict(mqtt)
    installed_mqtt.update({"host": "127.0.0.1", "port": 1883, "tls": False})
    installed_config["mqtt"] = installed_mqtt
    installed_delivery = dict(delivery)
    installed_delivery["type"] = "telegram"
    installed_delivery["chat_id"] = telegram_chat_id
    installed_delivery["token_file"] = "/etc/edgewatch-controller/telemetry-bot-token"
    installed_config["delivery"] = installed_delivery
    installed_radio = dict(raw_radio)
    installed_radio.update(
        {
            "adapter_executable": "/usr/local/libexec/edgewatch-sx1302-ingress",
            "adapter_config_file": "/etc/edgewatch-controller/sx1302-adapter.yaml",
            "status_file": "/var/lib/edgewatch-gateway/lorawan-radio-status.json",
            "instance_file": "/run/edgewatch-lorawan-radio/instance.json",
        }
    )

    # Exercise the exact production loader against an isolated, path-complete copy.
    with tempfile.TemporaryDirectory(prefix=".edgewatch-gateway-validate-") as temp_name:
        validation_root = Path(temp_name)
        validation_registry = validation_root / "registry.yaml"
        validation_registry.write_bytes(registry_payload)
        validation_registry.chmod(0o600)
        validation_token = validation_root / "token"
        validation_token.write_text("validation-only-token\n", encoding="utf-8")
        validation_token.chmod(0o600)
        validation_vendor = validation_root / "vendor.yaml"
        validation_vendor.write_bytes(vendor_payload)
        validation_vendor.chmod(0o600)
        validation_radio = validation_root / "radio.yaml"
        validation_radio_values = dict(installed_radio)
        validation_radio_values["adapter_config_file"] = str(validation_vendor)
        validation_radio.write_text(
            yaml.safe_dump(validation_radio_values, sort_keys=False), encoding="utf-8"
        )
        validation_radio.chmod(0o600)
        validation_config = dict(installed_config)
        validation_config["registry_file"] = str(validation_registry)
        validation_config["radio_ingress_file"] = str(validation_radio)
        validation_config["gateway_store_path"] = str(validation_root / "gateway.sqlite")
        validation_delivery = dict(installed_delivery)
        validation_delivery["token_file"] = str(validation_token)
        validation_config["delivery"] = validation_delivery
        validation_path = validation_root / "gateway.yaml"
        validation_path.write_text(yaml.safe_dump(validation_config, sort_keys=False), encoding="utf-8")
        validation_path.chmod(0o600)
        try:
            load_gateway_service_config(validation_path)
        except GatewayServiceConfigError as exc:
            raise ProvisioningError("LoRaWAN gateway config is invalid") from exc

    power_values = _parse_strict_env(power_payload, label="gateway power environment")
    unknown_power = sorted(set(power_values) - _GATEWAY_POWER_ENV_KEYS)
    if unknown_power:
        raise ProvisioningError(
            "gateway power environment contains unsupported settings: " + ", ".join(unknown_power)
        )
    power_values.update(
        {
            "EDGEWATCH_GATEWAY_LTE_TRIGGER_PATH": ("/var/lib/edgewatch-gateway/lte-trigger.json"),
            "EDGEWATCH_GATEWAY_LTE_POWER_STATE_PATH": ("/var/lib/edgewatch-gateway/lte-power-state.json"),
            "EDGEWATCH_GATEWAY_LTE_HOLD_DIR": "/var/lib/edgewatch-gateway/lte-holds",
        }
    )
    try:
        load_gateway_power_config(power_values)
    except GatewayPowerConfigError as exc:
        raise ProvisioningError("gateway power environment is invalid") from exc
    deadman_file = power_values.get("EDGEWATCH_DEADMAN_HEARTBEAT_URL_FILE")
    if deadman_file and (not Path(deadman_file).is_absolute() or Path(deadman_file) == Path("/")):
        raise ProvisioningError("dead-man heartbeat URL file must be an absolute non-root path")
    return (
        yaml.safe_dump(installed_config, sort_keys=False),
        registry_payload,
        _render_env(power_values, header="# EdgeWatch gateway power configuration."),
        yaml.safe_dump(installed_radio, sort_keys=False).encode("utf-8"),
        vendor_payload,
    )


def _prepare_camera_inputs(
    *,
    device_id: str,
    runtime_env_file: Path,
    credentials_file: Path,
) -> tuple[str, bytes]:
    from agent.camera_satellite_runner import SatelliteConfig, SatelliteConfigError
    from agent.media.rtsp import FFmpegRtspBackend, RtspCameraConfig, RtspConfigurationError

    runtime_payload = _read_private_file(runtime_env_file, label="camera runtime environment")
    credentials_payload = _read_private_file(credentials_file, label="RTSP credentials", maximum_bytes=4096)
    values = _parse_strict_env(runtime_payload, label="camera runtime environment")
    camera_id = values.get("EDGEWATCH_CAMERA_ID", "cam1").strip().lower()
    media_url_key = f"MEDIA_RTSP_{camera_id.upper()}_URL"
    media_credentials_key = f"MEDIA_RTSP_{camera_id.upper()}_CREDENTIALS_FILE"
    allowed = _CAMERA_RUNTIME_ENV_KEYS | {media_url_key, media_credentials_key}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ProvisioningError(
            "camera runtime environment contains unsupported settings: " + ", ".join(unknown)
        )
    forbidden = [
        key
        for key in values
        if any(marker in key for marker in ("TELEGRAM", "BOT_TOKEN", "DEVICE_TOKEN", "LTE", "CELLULAR"))
        or key == "EDGEWATCH_API_URL"
    ]
    if forbidden:
        raise ProvisioningError("camera satellites must not receive Telegram, API, or LTE settings")
    try:
        credentials = json.loads(credentials_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProvisioningError("RTSP credentials must contain valid UTF-8 JSON") from exc
    if not isinstance(credentials, dict) or set(credentials) != {"username", "password"}:
        raise ProvisioningError("RTSP credentials must contain exactly username and password")
    for field in ("username", "password"):
        value = credentials.get(field)
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 256
            or any(ord(character) < 32 for character in value)
        ):
            raise ProvisioningError(f"RTSP {field} is invalid")

    values.update(
        {
            "EDGEWATCH_CAMERA_ID": camera_id,
            "EDGEWATCH_DEVICE_ID": device_id,
            "EDGEWATCH_INFERENCE_MODE": values.get("EDGEWATCH_INFERENCE_MODE", "shadow"),
            "EDGEWATCH_MODEL_CURRENT_SYMLINK": "/opt/edgewatch/models/current",
            "EDGEWATCH_MODEL_KEYRING_DIR": "/etc/edgewatch/model-keys",
            "EDGEWATCH_MODEL_RELEASES_ROOT": "/opt/edgewatch/models/releases",
            "EDGEWATCH_CURRENT_SYMLINK": "/opt/edgewatch/current",
            "EDGEWATCH_RELEASES_ROOT": "/opt/edgewatch/releases",
            "EDGEWATCH_SATELLITE_EVIDENCE_DIR": "/var/lib/edgewatch-media/evidence",
            "EDGEWATCH_SATELLITE_GATE_STATE_PATH": ("/var/lib/edgewatch-camera-satellite/alert-gate.json"),
            "EDGEWATCH_SATELLITE_LOCK_PATH": "/run/edgewatch-camera-satellite/run.lock",
            "EDGEWATCH_SATELLITE_POWEROFF_REQUEST_PATH": ("/run/edgewatch-camera-satellite/poweroff.request"),
            "EDGEWATCH_SATELLITE_READY_PATH": "/var/lib/edgewatch-camera-satellite/ready.json",
            "EDGEWATCH_SATELLITE_RESULT_PATH": "/var/lib/edgewatch-camera-satellite/result.json",
            media_credentials_key: f"/etc/edgewatch/camera-{camera_id}.json",
        }
    )
    if values["EDGEWATCH_INFERENCE_MODE"].strip().lower() != "shadow":
        raise ProvisioningError("camera first boot must begin in shadow inference mode")
    try:
        config = SatelliteConfig.from_env(values)
        FFmpegRtspBackend(
            {
                config.camera_id: RtspCameraConfig(
                    endpoint=config.rtsp_endpoint,
                    credentials_path=config.rtsp_credentials_path,
                    require_audio=True,
                )
            }
        )
    except (SatelliteConfigError, RtspConfigurationError) as exc:
        raise ProvisioningError("camera runtime environment is invalid") from exc
    return (
        _render_env(values, header="# EdgeWatch camera-satellite runtime configuration."),
        credentials_payload,
    )


def _read_initial_model_bundle(path: Path) -> bytes:
    payload = _read_private_file(
        path,
        label="initial signed model bundle",
        maximum_bytes=512 * 1024 * 1024,
    )
    try:
        with tarfile.open(path, mode="r:*") as archive:
            names = {member.name for member in archive.getmembers() if member.isfile()}
    except (OSError, tarfile.TarError) as exc:
        raise ProvisioningError("initial signed model bundle must be a readable tar archive") from exc
    if "manifest.json" not in names:
        raise ProvisioningError("initial signed model bundle must contain manifest.json at its root")
    return payload


def _read_ssh_public_key(path: Path) -> str:
    if not path.is_file():
        raise ProvisioningError("SSH public key file must be an existing regular file")
    try:
        raw_key = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ProvisioningError("SSH public key file could not be read as UTF-8 text") from exc
    if "PRIVATE KEY" in raw_key.upper():
        raise ProvisioningError("SSH public key file must not contain private-key material")
    lines = raw_key.splitlines()
    if len(lines) != 1 or not lines[0].strip():
        raise ProvisioningError("SSH public key file must contain exactly one nonempty line")
    public_key = lines[0]
    if any(ord(character) < 32 or ord(character) == 127 for character in public_key):
        raise ProvisioningError("SSH public key must not contain control characters")
    parts = public_key.split()
    if len(parts) < 2:
        raise ProvisioningError("SSH public key must be an OpenSSH public-key line")
    key_type, encoded_key = parts[:2]
    if key_type not in {"ssh-ed25519", "ssh-rsa"} and not ECDSA_KEY_TYPE_PATTERN.fullmatch(key_type):
        raise ProvisioningError("SSH public key type must be ssh-ed25519, ssh-rsa, or ecdsa-sha2-*")
    try:
        decoded_key = base64.b64decode(encoded_key, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProvisioningError("SSH public key payload must be valid base64") from exc
    try:
        _validate_ssh_key_blob(key_type, decoded_key)
    except ValueError as exc:
        raise ProvisioningError("SSH public key payload is not a valid OpenSSH key") from exc
    return public_key


def _read_ota_public_key(path: Path) -> str:
    if not path.is_file():
        raise ProvisioningError("OTA public key file must be an existing regular file")
    try:
        raw = path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise ProvisioningError("OTA public key file could not be read as ASCII PEM") from exc
    if "PRIVATE KEY" in raw or len(raw.encode("ascii")) > 64 * 1024:
        raise ProvisioningError("OTA public key file must contain only a bounded public key")
    if raw.count("-----BEGIN PUBLIC KEY-----") != 1 or raw.count("-----END PUBLIC KEY-----") != 1:
        raise ProvisioningError("OTA public key file must use PEM PUBLIC KEY format")
    try:
        completed = subprocess.run(
            ["openssl", "pkey", "-pubin", "-in", str(path), "-noout"],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ProvisioningError("OpenSSL is required to validate the OTA public key") from exc
    if completed.returncode != 0:
        raise ProvisioningError("OTA public key file is not a valid OpenSSL public key")
    return raw.rstrip() + "\n"


def _ssh_blob_field(blob: bytes, offset: int) -> tuple[bytes, int]:
    if offset + 4 > len(blob):
        raise ValueError("truncated SSH field length")
    length = int.from_bytes(blob[offset : offset + 4], "big")
    start = offset + 4
    end = start + length
    if length <= 0 or end > len(blob):
        raise ValueError("invalid SSH field length")
    return blob[start:end], end


def _validate_ssh_key_blob(key_type: str, blob: bytes) -> None:
    encoded_type, offset = _ssh_blob_field(blob, 0)
    try:
        embedded_type = encoded_type.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("SSH key type is not ASCII") from exc
    if embedded_type != key_type:
        raise ValueError("SSH key type does not match payload")

    if key_type == "ssh-ed25519":
        key_material, offset = _ssh_blob_field(blob, offset)
        if len(key_material) != 32:
            raise ValueError("invalid Ed25519 key length")
    elif key_type == "ssh-rsa":
        _exponent, offset = _ssh_blob_field(blob, offset)
        _modulus, offset = _ssh_blob_field(blob, offset)
    else:
        curve, offset = _ssh_blob_field(blob, offset)
        _point, offset = _ssh_blob_field(blob, offset)
        expected_curve = key_type.removeprefix("ecdsa-sha2-").encode("ascii")
        if curve != expected_curve:
            raise ValueError("ECDSA curve does not match key type")

    if offset != len(blob):
        raise ValueError("SSH key payload has trailing data")


def _validated_output_dir(output_dir: Path) -> Path:
    expanded = output_dir.expanduser()
    if expanded.exists() and expanded.is_symlink():
        raise ProvisioningError("output directory must not be a symbolic link")
    resolved = expanded.resolve()
    if resolved == Path(resolved.anchor):
        raise ProvisioningError("output directory must not be a filesystem root")
    if resolved.exists() and not resolved.is_dir():
        raise ProvisioningError("output path exists and is not a directory")
    return resolved


def _validate_replace_target(output_dir: Path, target: Path) -> None:
    if target.name != BOOT_EDGEWATCH_DIR.name or target.parent != output_dir:
        raise ProvisioningError("refusing to replace anything except the exact output/edgewatch directory")
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise ProvisioningError("existing output/edgewatch must be a real directory")


def _backup_target(output_dir: Path) -> Path:
    while True:
        backup = output_dir / f".edgewatch-backup-{uuid.uuid4().hex}"
        if not backup.exists() and not backup.is_symlink():
            return backup


def _validate_backup_target(output_dir: Path, backup: Path) -> None:
    if backup.parent != output_dir or not backup.name.startswith(".edgewatch-backup-"):
        raise ProvisioningError("refusing to manage an invalid edgewatch backup path")
    if backup.is_symlink() or (backup.exists() and not backup.is_dir()):
        raise ProvisioningError("edgewatch backup must be a real directory")


def _manifest(
    *,
    device_id: str,
    profile: str,
    power_profile: str,
    bootstrap_env: str,
    ota_public_key_sha256: str | None,
    ota_public_key_id: str | None,
    model_public_key_id: str | None,
    files: dict[str, str],
) -> dict[str, object]:
    return {
        "bootstrap_env_sha256": hashlib.sha256(bootstrap_env.encode("utf-8")).hexdigest(),
        "device_id": device_id,
        "files": dict(sorted(files.items())),
        "image_family": "fleet-image-v1",
        "image_profile": profile,
        "manifest_contains_secrets": False,
        "model_public_key_id": model_public_key_id,
        "ota_public_key_id": ota_public_key_id,
        "ota_public_key_sha256": ota_public_key_sha256,
        "power_profile": power_profile if profile != "camera-satellite" else None,
        "schema_version": 1,
        "telemetry_transport": "none" if profile == "camera-satellite" else "telegram",
    }


def generate_bundle(
    *,
    device_id: str,
    telegram_chat_id: str | None = None,
    bot_token_file: Path | None = None,
    ssh_public_key_file: Path | None = None,
    control_ssh_public_key_file: Path | None = None,
    output_dir: Path,
    ota_public_key_file: Path | None = None,
    ota_key_id: str = "edgewatch-release",
    power_profile: str = "continuous",
    force: bool = False,
    repo_dir: Path = DEFAULT_REPO_DIR,
    lte_apn: str = DEFAULT_LTE_APN,
    profile: str = "standalone",
    lorawan_gateway_config_file: Path | None = None,
    lorawan_registry_file: Path | None = None,
    lorawan_radio_ingress_file: Path | None = None,
    lorawan_vendor_config_file: Path | None = None,
    gateway_power_env_file: Path | None = None,
    camera_runtime_env_file: Path | None = None,
    camera_credentials_file: Path | None = None,
    model_public_key_file: Path | None = None,
    model_key_id: str = "edgewatch-models",
    initial_model_bundle_file: Path | None = None,
    ota_gateway_cache_url: str = DEFAULT_OTA_GATEWAY_CACHE_URL,
) -> Path:
    """Generate the ``edgewatch`` boot-partition subtree and return its path."""

    device_id = validate_device_id(device_id)
    if profile not in PROFILES:
        raise ProvisioningError(f"profile must be one of: {', '.join(PROFILES)}")
    token: str | None = None
    if profile in {"standalone", "gateway"}:
        if telegram_chat_id is None or bot_token_file is None:
            raise ProvisioningError("standalone and gateway profiles require Telegram chat and token inputs")
        token = _read_token(bot_token_file.expanduser())
    elif telegram_chat_id is not None or bot_token_file is not None:
        raise ProvisioningError("camera-satellite profiles must not receive Telegram credentials")

    ssh_public_key = (
        _read_ssh_public_key(ssh_public_key_file.expanduser()) if ssh_public_key_file is not None else None
    )
    control_ssh_public_key = (
        _read_ssh_public_key(control_ssh_public_key_file.expanduser())
        if control_ssh_public_key_file is not None
        else None
    )
    if profile == "standalone" and (ssh_public_key is None or control_ssh_public_key is None):
        raise ProvisioningError("standalone profile requires operator and controller SSH public keys")
    if profile == "gateway" and ssh_public_key is None:
        raise ProvisioningError("gateway profile requires an operator SSH public key")
    if profile == "camera-satellite" and control_ssh_public_key is None:
        raise ProvisioningError("camera-satellite profile requires the gateway controller SSH public key")
    if (
        control_ssh_public_key is not None
        and ssh_public_key is not None
        and control_ssh_public_key.split()[:2] == ssh_public_key.split()[:2]
    ):
        raise ProvisioningError("controller and operator SSH public keys must use different key material")
    ota_public_key = (
        _read_ota_public_key(ota_public_key_file.expanduser()) if ota_public_key_file is not None else None
    )
    if ota_public_key is None:
        raise ProvisioningError(f"{profile} profile requires an OTA public trust key")
    gateway_config: str | None = None
    gateway_registry: bytes | None = None
    gateway_radio: bytes | None = None
    gateway_vendor: bytes | None = None
    gateway_power: str | None = None
    if profile == "gateway":
        if not all(
            (
                lorawan_gateway_config_file,
                lorawan_registry_file,
                lorawan_radio_ingress_file,
                lorawan_vendor_config_file,
                gateway_power_env_file,
            )
        ):
            raise ProvisioningError(
                "gateway profile requires LoRaWAN gateway, registry, radio, vendor, and power files"
            )
        assert telegram_chat_id is not None
        assert lorawan_gateway_config_file is not None
        assert lorawan_registry_file is not None
        assert lorawan_radio_ingress_file is not None
        assert lorawan_vendor_config_file is not None
        assert gateway_power_env_file is not None
        gateway_config, gateway_registry, gateway_power, gateway_radio, gateway_vendor = (
            _prepare_gateway_inputs(
                config_file=lorawan_gateway_config_file.expanduser(),
                registry_file=lorawan_registry_file.expanduser(),
                radio_ingress_file=lorawan_radio_ingress_file.expanduser(),
                vendor_config_file=lorawan_vendor_config_file.expanduser(),
                power_env_file=gateway_power_env_file.expanduser(),
                telegram_chat_id=telegram_chat_id,
            )
        )
    elif any(
        (
            lorawan_gateway_config_file,
            lorawan_registry_file,
            lorawan_radio_ingress_file,
            lorawan_vendor_config_file,
            gateway_power_env_file,
        )
    ):
        raise ProvisioningError("LoRaWAN gateway inputs are valid only for the gateway profile")

    camera_runtime: str | None = None
    camera_credentials: bytes | None = None
    model_public_key: str | None = None
    initial_model_bundle: bytes | None = None
    if profile == "camera-satellite":
        if not all(
            (
                camera_runtime_env_file,
                camera_credentials_file,
                model_public_key_file,
                initial_model_bundle_file,
            )
        ):
            raise ProvisioningError(
                "camera-satellite profile requires runtime env, RTSP credentials, model public key, "
                "and initial signed model bundle"
            )
        assert camera_runtime_env_file is not None
        assert camera_credentials_file is not None
        assert model_public_key_file is not None
        assert initial_model_bundle_file is not None
        camera_runtime, camera_credentials = _prepare_camera_inputs(
            device_id=device_id,
            runtime_env_file=camera_runtime_env_file.expanduser(),
            credentials_file=camera_credentials_file.expanduser(),
        )
        model_public_key = _read_ota_public_key(model_public_key_file.expanduser())
        initial_model_bundle = _read_initial_model_bundle(initial_model_bundle_file.expanduser())
    elif any(
        (
            camera_runtime_env_file,
            camera_credentials_file,
            model_public_key_file,
            initial_model_bundle_file,
        )
    ):
        raise ProvisioningError("camera inputs are valid only for the camera-satellite profile")

    bootstrap_env = render_bootstrap_env(
        device_id=device_id,
        telegram_chat_id=telegram_chat_id,
        repo_dir=repo_dir,
        lte_apn=lte_apn,
        power_profile=power_profile,
        ota_key_id=ota_key_id if ota_public_key is not None else None,
        profile=profile,
        model_key_id=model_key_id if model_public_key is not None else None,
        has_initial_model_bundle=initial_model_bundle is not None,
        has_ssh_authorized_key=ssh_public_key is not None,
        has_control_ssh_authorized_key=control_ssh_public_key is not None,
        ota_gateway_cache_url=ota_gateway_cache_url,
    )
    output_dir = _validated_output_dir(output_dir)

    if output_dir.exists() and any(output_dir.iterdir()) and not force:
        raise ProvisioningError("output directory is not empty; pass --force to replace output/edgewatch")
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / BOOT_EDGEWATCH_DIR
    _validate_replace_target(output_dir, target)

    with tempfile.TemporaryDirectory(prefix=".edgewatch-provision-", dir=output_dir) as temp_name:
        staged = Path(temp_name) / BOOT_EDGEWATCH_DIR
        staged.mkdir(mode=0o700)

        bootstrap_path = staged / BOOTSTRAP_ENV_NAME
        bootstrap_path.write_text(bootstrap_env, encoding="utf-8")
        bootstrap_path.chmod(0o600)

        manifest_files = {"bootstrap_env": "edgewatch/bootstrap.env"}
        if token is not None:
            token_path = staged / TELEGRAM_TOKEN_NAME
            token_path.write_text(f"{token}\n", encoding="utf-8")
            token_path.chmod(0o600)
            manifest_files["telegram_bot_token"] = "edgewatch/telegram_bot_token"

        if ssh_public_key is not None:
            authorized_key_path = staged / SSH_AUTHORIZED_KEY_NAME
            authorized_key_path.write_text(f"{ssh_public_key}\n", encoding="utf-8")
            authorized_key_path.chmod(0o644)
            manifest_files["authorized_key"] = "edgewatch/authorized_key"

        if control_ssh_public_key is not None:
            control_authorized_key_path = staged / CONTROL_SSH_AUTHORIZED_KEY_NAME
            control_authorized_key_path.write_text(f"{control_ssh_public_key}\n", encoding="utf-8")
            control_authorized_key_path.chmod(0o644)
            manifest_files["control_authorized_key"] = "edgewatch/control_authorized_key"

        if ota_public_key is not None:
            ota_key_dir = staged / OTA_KEYS_DIR_NAME
            ota_key_dir.mkdir(mode=0o755)
            ota_key_path = ota_key_dir / f"{ota_key_id}.pem"
            ota_key_path.write_text(ota_public_key, encoding="ascii")
            ota_key_path.chmod(0o644)
            manifest_files["ota_public_key"] = f"edgewatch/{OTA_KEYS_DIR_NAME}/{ota_key_id}.pem"

        if all(
            value is not None
            for value in (
                gateway_config,
                gateway_registry,
                gateway_power,
                gateway_radio,
                gateway_vendor,
            )
        ):
            assert gateway_config is not None
            assert gateway_registry is not None
            assert gateway_power is not None
            assert gateway_radio is not None
            assert gateway_vendor is not None
            (staged / LORAWAN_GATEWAY_CONFIG_NAME).write_text(gateway_config, encoding="utf-8")
            (staged / LORAWAN_REGISTRY_NAME).write_bytes(gateway_registry)
            (staged / LORAWAN_RADIO_INGRESS_NAME).write_bytes(gateway_radio)
            (staged / LORAWAN_VENDOR_CONFIG_NAME).write_bytes(gateway_vendor)
            (staged / GATEWAY_POWER_ENV_NAME).write_text(gateway_power, encoding="utf-8")
            for name in (
                LORAWAN_GATEWAY_CONFIG_NAME,
                LORAWAN_REGISTRY_NAME,
                LORAWAN_RADIO_INGRESS_NAME,
                LORAWAN_VENDOR_CONFIG_NAME,
                GATEWAY_POWER_ENV_NAME,
            ):
                (staged / name).chmod(0o600)
            manifest_files.update(
                {
                    "gateway_power_env": f"edgewatch/{GATEWAY_POWER_ENV_NAME}",
                    "lorawan_gateway_config": f"edgewatch/{LORAWAN_GATEWAY_CONFIG_NAME}",
                    "lorawan_radio_ingress": f"edgewatch/{LORAWAN_RADIO_INGRESS_NAME}",
                    "lorawan_registry": f"edgewatch/{LORAWAN_REGISTRY_NAME}",
                    "lorawan_vendor_config": f"edgewatch/{LORAWAN_VENDOR_CONFIG_NAME}",
                }
            )

        if camera_runtime is not None and camera_credentials is not None and model_public_key is not None:
            (staged / CAMERA_RUNTIME_ENV_NAME).write_text(camera_runtime, encoding="utf-8")
            (staged / CAMERA_CREDENTIALS_NAME).write_bytes(camera_credentials)
            (staged / CAMERA_RUNTIME_ENV_NAME).chmod(0o600)
            (staged / CAMERA_CREDENTIALS_NAME).chmod(0o600)
            model_key_dir = staged / MODEL_KEYS_DIR_NAME
            model_key_dir.mkdir(mode=0o755)
            model_key_path = model_key_dir / f"{model_key_id}.pem"
            model_key_path.write_text(model_public_key, encoding="ascii")
            model_key_path.chmod(0o644)
            manifest_files.update(
                {
                    "camera_credentials": f"edgewatch/{CAMERA_CREDENTIALS_NAME}",
                    "camera_runtime_env": f"edgewatch/{CAMERA_RUNTIME_ENV_NAME}",
                    "model_public_key": (f"edgewatch/{MODEL_KEYS_DIR_NAME}/{model_key_id}.pem"),
                }
            )
            if initial_model_bundle is not None:
                initial_model_path = staged / INITIAL_MODEL_BUNDLE_NAME
                initial_model_path.write_bytes(initial_model_bundle)
                initial_model_path.chmod(0o600)
                manifest_files["initial_model_bundle"] = f"edgewatch/{INITIAL_MODEL_BUNDLE_NAME}"

        manifest_path = staged / MANIFEST_NAME
        manifest_path.write_text(
            json.dumps(
                _manifest(
                    device_id=device_id,
                    profile=profile,
                    power_profile=power_profile,
                    bootstrap_env=bootstrap_env,
                    ota_public_key_sha256=(
                        hashlib.sha256(ota_public_key.encode("ascii")).hexdigest()
                        if ota_public_key is not None
                        else None
                    ),
                    ota_public_key_id=ota_key_id if ota_public_key is not None else None,
                    model_public_key_id=model_key_id if model_public_key is not None else None,
                    files=manifest_files,
                ),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        manifest_path.chmod(0o644)

        backup: Path | None = None
        if target.exists():
            _validate_replace_target(output_dir, target)
            backup = _backup_target(output_dir)
            _validate_backup_target(output_dir, backup)
            target.rename(backup)
        try:
            staged.rename(target)
        except OSError:
            if backup is not None:
                _validate_backup_target(output_dir, backup)
                backup.rename(target)
            raise
        if backup is not None:
            _validate_backup_target(output_dir, backup)
            shutil.rmtree(backup)

    if token is not None and stat.S_IMODE((target / TELEGRAM_TOKEN_NAME).stat().st_mode) != 0o600:
        raise ProvisioningError("generated token file does not have mode 0600")
    if (
        ssh_public_key is not None
        and stat.S_IMODE((target / SSH_AUTHORIZED_KEY_NAME).stat().st_mode) != 0o644
    ):
        raise ProvisioningError("generated SSH authorized key file does not have mode 0644")
    if (
        control_ssh_public_key is not None
        and stat.S_IMODE((target / CONTROL_SSH_AUTHORIZED_KEY_NAME).stat().st_mode) != 0o644
    ):
        raise ProvisioningError("generated controller SSH public key file does not have mode 0644")
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a fleet-image-v1 per-device boot-partition provisioning bundle."
    )
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--profile", choices=PROFILES, default="standalone")
    parser.add_argument("--telegram-chat-id")
    parser.add_argument("--bot-token-file", type=Path)
    parser.add_argument("--ssh-public-key-file", type=Path)
    parser.add_argument("--control-ssh-public-key-file", type=Path)
    parser.add_argument("--ota-public-key-file", type=Path)
    parser.add_argument("--ota-key-id", default="edgewatch-release")
    parser.add_argument("--lorawan-gateway-config-file", type=Path)
    parser.add_argument("--lorawan-registry-file", type=Path)
    parser.add_argument("--lorawan-radio-ingress-file", type=Path)
    parser.add_argument("--lorawan-vendor-config-file", type=Path)
    parser.add_argument("--gateway-power-env-file", type=Path)
    parser.add_argument("--camera-runtime-env-file", type=Path)
    parser.add_argument("--camera-credentials-file", type=Path)
    parser.add_argument("--model-public-key-file", type=Path)
    parser.add_argument("--model-key-id", default="edgewatch-models")
    parser.add_argument("--initial-model-bundle-file", type=Path)
    parser.add_argument(
        "--ota-gateway-cache-url",
        default=DEFAULT_OTA_GATEWAY_CACHE_URL,
        help="private maintenance-WLAN gateway cache URL for camera-satellite OTA",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--power-profile", choices=("continuous", "eco"), default="continuous")
    parser.add_argument("--repo-dir", type=Path, default=DEFAULT_REPO_DIR)
    parser.add_argument("--lte-apn", default=DEFAULT_LTE_APN)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        bundle_dir = generate_bundle(
            device_id=args.device_id,
            telegram_chat_id=args.telegram_chat_id,
            bot_token_file=args.bot_token_file,
            ssh_public_key_file=args.ssh_public_key_file,
            control_ssh_public_key_file=args.control_ssh_public_key_file,
            ota_public_key_file=args.ota_public_key_file,
            ota_key_id=args.ota_key_id,
            output_dir=args.output_dir,
            power_profile=args.power_profile,
            force=args.force,
            repo_dir=args.repo_dir,
            lte_apn=args.lte_apn,
            profile=args.profile,
            lorawan_gateway_config_file=args.lorawan_gateway_config_file,
            lorawan_registry_file=args.lorawan_registry_file,
            lorawan_radio_ingress_file=args.lorawan_radio_ingress_file,
            lorawan_vendor_config_file=args.lorawan_vendor_config_file,
            gateway_power_env_file=args.gateway_power_env_file,
            camera_runtime_env_file=args.camera_runtime_env_file,
            camera_credentials_file=args.camera_credentials_file,
            model_public_key_file=args.model_public_key_file,
            model_key_id=args.model_key_id,
            initial_model_bundle_file=args.initial_model_bundle_file,
            ota_gateway_cache_url=args.ota_gateway_cache_url,
        )
    except ProvisioningError as exc:
        parser.error(str(exc))
    print(f"Provisioning bundle written to {os.fspath(bundle_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
