#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import ipaddress
import json
import logging
import os
import pwd
import re
import shlex
import shutil
import socket
import ssl
import stat
import tarfile
import subprocess
import sys
import tempfile
import time
import uuid
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


DEFAULT_BOOT_CONFIG_CANDIDATES = (
    Path("/boot/firmware/edgewatch/bootstrap.env"),
    Path("/boot/edgewatch/bootstrap.env"),
)

DEFAULT_AGENT_ENV_PATH = "agent/.env"
DEFAULT_AGENT_SERVICE_PATH = Path("/etc/systemd/system/edgewatch-agent.service")
DEFAULT_FIRSTBOOT_MARKER = Path("/var/lib/edgewatch/bootstrap.complete")
DEFAULT_FIRSTBOOT_REPORT = Path("/var/lib/edgewatch/bootstrap-report.json")
DEFAULT_DATA_DIR = Path("/var/lib/edgewatch")
DEFAULT_AGENT_PYTHON = ".venv/bin/python"
DEFAULT_AGENT_ENTRYPOINT = "agent/edgewatch_agent.py"
DEFAULT_AGENT_WORKDIR = "agent"
DEFAULT_DEVICE_CONTROL_ENTRYPOINT = "scripts/edgewatch_device_control.py"
DEFAULT_CURRENT_SYMLINK = Path("/opt/edgewatch/current")
DEFAULT_AGENT_SERVICE_NAME = "edgewatch-agent"
DEFAULT_LTE_CONNECTION_NAME = "edgewatch-lte"
DEFAULT_LTE_IFNAME = "*"
DEFAULT_NETWORKMANAGER_CONNECTION_DIR = Path("/etc/NetworkManager/system-connections")
DEFAULT_SENSOR_CONFIG = "./agent/config/rpi.microphone.sensors.yaml"
DEFAULT_BUNDLE_INSTALL_DIR = ""
DEFAULT_BUNDLE_CACHE_DIR = Path("/var/lib/edgewatch/bootstrap-cache")
DEFAULT_RUNTIME_POWER_MODE = "continuous"
DEFAULT_DEEP_SLEEP_BACKEND = "auto"
DEFAULT_REMOTE_SHUTDOWN = "0"
DEFAULT_OTA_APPLY = "0"
DEFAULT_POWER_MGMT_ENABLED = "true"
DEFAULT_POWER_MGMT_MODE = "dual"
DEFAULT_TELEMETRY_TRANSPORT = "api"
DEFAULT_TELEGRAM_TOKEN_FILENAME = "telegram_bot_token"
DEFAULT_SSH_HARDENING_PATH = Path("/etc/ssh/sshd_config.d/01-edgewatch-publickey-only.conf")
DEFAULT_AGENT_READY_TIMEOUT_S = 45.0
DEFAULT_AGENT_STABILITY_S = 5.0
DEFAULT_IMAGE_PROFILE_PATH = Path("/etc/edgewatch-image-profile")
DEFAULT_GATEWAY_CONFIG_DIR = Path("/etc/edgewatch-controller")
DEFAULT_GATEWAY_STATE_DIR = Path("/var/lib/edgewatch-controller")
DEFAULT_GATEWAY_RADIO_STATE_DIR = Path("/var/lib/edgewatch-gateway")
DEFAULT_GATEWAY_SERVICE_PATH = Path("/etc/systemd/system/edgewatch-lorawan-gateway.service")
DEFAULT_RADIO_SERVICE_PATH = Path("/etc/systemd/system/edgewatch-lorawan-radio-ingress.service")
DEFAULT_CAMERA_CONFIG_DIR = Path("/etc/edgewatch")
DEFAULT_CAMERA_SERVICE_PATH = Path("/etc/systemd/system/edgewatch-camera-satellite@.service")
DEFAULT_CAMERA_WAKE_SERVICE_PATH = Path("/etc/systemd/system/edgewatch-camera-satellite-wake@.service")
DEFAULT_CAMERA_POWEROFF_SERVICE_PATH = Path("/etc/systemd/system/edgewatch-camera-satellite-poweroff.service")
DEFAULT_CAMERA_POWEROFF_PATH = Path("/etc/systemd/system/edgewatch-camera-satellite-poweroff.path")
DEFAULT_CAMERA_MODEL_RECOVERY_SERVICE_PATH = Path(
    "/etc/systemd/system/edgewatch-camera-model-recovery.service"
)
DEFAULT_MODEL_ROOT = Path("/opt/edgewatch/models")
PROFILES = frozenset({"standalone", "gateway", "camera-satellite"})
GATEWAY_SERVICE_NAME = "edgewatch-lorawan-gateway"
RADIO_SERVICE_NAME = "edgewatch-lorawan-radio-ingress"
CAMERA_CHECK_SERVICE_NAME = "edgewatch-camera-satellite@check.service"
CAMERA_MODEL_RECOVERY_SERVICE_NAME = "edgewatch-camera-model-recovery.service"
CAMERA_RUNTIME_USER = "edgewatch-camera"
CAMERA_ASSET_APPLY_CMD = (
    "/opt/edgewatch/app/.venv/bin/python /opt/edgewatch/current/scripts/apply_model_bundle.py"
)
CAMERA_OTA_POWER_STATE_PATH = "/var/lib/edgewatch-camera-satellite/ota-power-state.json"

GATEWAY_POWER_ENV_KEYS = frozenset(
    {
        "CELLULAR_INTERFACE",
        "EDGEWATCH_DEADMAN_BACKOFF_BASE_S",
        "EDGEWATCH_DEADMAN_HEARTBEAT_URL_FILE",
        "EDGEWATCH_DEADMAN_INTERVAL_S",
        "EDGEWATCH_DEADMAN_MAX_ATTEMPTS",
        "EDGEWATCH_DEADMAN_REQUEST_TIMEOUT_S",
        "EDGEWATCH_GATEWAY_LTE_HOLD_DIR",
        "EDGEWATCH_GATEWAY_LTE_MAX_WINDOW_S",
        "EDGEWATCH_GATEWAY_LTE_MAX_HELD_WINDOW_S",
        "EDGEWATCH_GATEWAY_LTE_MIN_WINDOW_S",
        "EDGEWATCH_GATEWAY_LTE_POWER_MODE",
        "EDGEWATCH_GATEWAY_LTE_POWER_STATE_PATH",
        "EDGEWATCH_GATEWAY_LTE_TRANSITION_TIMEOUT_S",
        "EDGEWATCH_GATEWAY_LTE_TRIGGER_PATH",
        "EDGEWATCH_GATEWAY_LTE_WINDOW_INTERVAL_S",
    }
)
CAMERA_RUNTIME_ENV_KEYS = frozenset(
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
        "EDGEWATCH_SATELLITE_POWEROFF_REQUEST_PATH",
        "EDGEWATCH_SATELLITE_PREPROCESS_TIMEOUT_S",
        "EDGEWATCH_SATELLITE_READINESS_TTL_S",
        "EDGEWATCH_SATELLITE_READY_PATH",
        "EDGEWATCH_SATELLITE_RESULT_PATH",
    }
)

AGENT_ENV_ALLOWLIST = {
    "EDGEWATCH_TELEMETRY_TRANSPORT",
    "EDGEWATCH_API_URL",
    "EDGEWATCH_ASSETS_ROOT",
    "EDGEWATCH_ASSET_BUNDLE_APPLY_CMD",
    "EDGEWATCH_DEVICE_ID",
    "EDGEWATCH_DEVICE_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_BOT_TOKEN_FILE",
    "TELEGRAM_TIMEOUT_S",
    "TELEGRAM_DISABLE_NOTIFICATION",
    "TELEGRAM_PROTECT_CONTENT",
    "TELEGRAM_BATCH_ENABLED",
    "TELEGRAM_BATCH_MAX_POINTS",
    "TELEGRAM_BATCH_MAX_BYTES",
    "TELEGRAM_BATCH_MAX_AGE_S",
    "SENSOR_CONFIG_PATH",
    "SENSOR_BACKEND",
    "SAMPLE_INTERVAL_S",
    "ALERT_SAMPLE_INTERVAL_S",
    "HEARTBEAT_INTERVAL_S",
    "ALERT_REPORT_INTERVAL_S",
    "MAX_POINTS_PER_BATCH",
    "BUFFER_DB_PATH",
    "BUFFER_MAX_POINTS",
    "BUFFER_MAX_AGE_S",
    "BUFFER_MAX_DB_BYTES",
    "BUFFER_SQLITE_JOURNAL_MODE",
    "BUFFER_SQLITE_SYNCHRONOUS",
    "BUFFER_SQLITE_TEMP_STORE",
    "BUFFER_EVICTION_BATCH_SIZE",
    "BUFFER_RECOVER_CORRUPTION",
    "BACKOFF_INITIAL_S",
    "BACKOFF_MAX_S",
    "MAX_BYTES_PER_DAY",
    "EDGEWATCH_COST_CAP_URGENT_RESERVE_BYTES",
    "MAX_SNAPSHOTS_PER_DAY",
    "MAX_MEDIA_UPLOADS_PER_DAY",
    "EDGEWATCH_COST_CAP_STATE_PATH",
    "EDGEWATCH_POLICY_CACHE_PATH",
    "EDGEWATCH_POWER_STATE_PATH",
    "EDGEWATCH_COMMAND_STATE_PATH",
    "EDGEWATCH_UPDATE_STATE_PATH",
    "EDGEWATCH_LOCAL_OTA_STATE_PATH",
    "EDGEWATCH_OTA_CACHE_DIR",
    "EDGEWATCH_OTA_KEYRING_DIR",
    "EDGEWATCH_RELEASES_ROOT",
    "EDGEWATCH_CURRENT_SYMLINK",
    "EDGEWATCH_RUNTIME_DEPENDENCY_PATH",
    "EDGEWATCH_OTA_POWER_EVIDENCE_MAX_AGE_S",
    "EDGEWATCH_OTA_GATEWAY_CACHE_URL",
    "EDGEWATCH_OTA_MAX_ARTIFACT_BYTES",
    "EDGEWATCH_OTA_RUNTIME_PROFILE",
    "EDGEWATCH_HARDWARE_MODEL",
    "EDGEWATCH_RELEASE_CHANNEL",
    "EDGEWATCH_SYSTEM_IMAGE_APPLY_ENABLED",
    "EDGEWATCH_LOW_POWER_STATE_PATH",
    "EDGEWATCH_DEADLETTER_PATH",
    "EDGEWATCH_READY_PATH",
    "RUNTIME_POWER_MODE",
    "DEEP_SLEEP_BACKEND",
    "SLEEP_POLL_INTERVAL_S",
    "EDGEWATCH_ALLOW_REMOTE_SHUTDOWN",
    "EDGEWATCH_ENABLE_OTA_APPLY",
    "POWER_MGMT_ENABLED",
    "POWER_MGMT_MODE",
    "POWER_INPUT_WARN_MIN_V",
    "POWER_INPUT_WARN_MAX_V",
    "POWER_INPUT_CRITICAL_MIN_V",
    "POWER_INPUT_CRITICAL_MAX_V",
    "POWER_SUSTAINABLE_INPUT_W",
    "POWER_UNSUSTAINABLE_WINDOW_S",
    "POWER_BATTERY_TREND_WINDOW_S",
    "POWER_BATTERY_DROP_WARN_V",
    "POWER_SAVER_SAMPLE_INTERVAL_S",
    "POWER_SAVER_HEARTBEAT_INTERVAL_S",
    "POWER_MEDIA_DISABLED_IN_SAVER",
    "CELLULAR_METRICS_ENABLED",
    "CELLULAR_WATCHDOG_ENABLED",
    "CELLULAR_INTERFACE",
    "CELLULAR_MODEM_ID",
    "CELLULAR_MMCLI_TIMEOUT_S",
    "CELLULAR_MODEM_POLL_INTERVAL_S",
    "CELLULAR_WATCHDOG_INTERVAL_S",
    "CELLULAR_WATCHDOG_DNS_HOST",
    "CELLULAR_WATCHDOG_HTTP_URL",
    "CELLULAR_WATCHDOG_TIMEOUT_S",
    "CELLULAR_USAGE_POLL_INTERVAL_S",
    "CELLULAR_USAGE_STATE_PATH",
    "MEDIA_ENABLED",
    "MEDIA_SNAPSHOT_INTERVAL_S",
    "MEDIA_CAPTURE_RETRY_S",
    "MEDIA_UPLOAD_RETRY_S",
    "MEDIA_UPLOAD_BACKOFF_MAX_S",
    "MEDIA_UPLOAD_TIMEOUT_S",
    "MEDIA_ALERT_TRANSITION_MIN_INTERVAL_S",
    "MEDIA_RING_DIR",
    "MEDIA_RING_MAX_BYTES",
    "MEDIA_CAPTURE_TIMEOUT_S",
    "MEDIA_CAPTURE_LOCK_TIMEOUT_S",
}

CONSUMED_BOOTSTRAP_SECRET_KEYS = {
    "BOOTSTRAP_TELEGRAM_BOT_TOKEN",
    "BOOTSTRAP_TAILSCALE_AUTH_KEY",
    "BOOTSTRAP_LTE_PASSWORD",
    "EDGEWATCH_DEVICE_TOKEN",
}


@dataclass(frozen=True)
class BootstrapConfig:
    repo_dir: Path
    data_dir: Path
    agent_env_path: Path
    agent_service_path: Path
    firstboot_marker: Path
    firstboot_report: Path
    device_id: str
    telemetry_transport: str
    api_url: str | None
    device_token: str | None
    telegram_chat_id: str | None
    telegram_bot_token_file: Path | None
    telegram_bot_token: str | None
    bootstrap_telegram_bot_token_file: Path | None
    ssh_user: str
    ssh_authorized_key_file: Path | None
    control_ssh_authorized_key_file: Path | None
    ota_public_key_file: Path | None
    ota_public_key_id: str | None
    sensor_config_path: str
    runtime_power_mode: str
    deep_sleep_backend: str
    allow_remote_shutdown: str
    enable_ota_apply: str
    power_mgmt_enabled: str
    power_mgmt_mode: str
    python_bin: Path
    agent_entrypoint: Path
    agent_workdir: Path
    current_symlink: Path | None
    tailscale_auth_key: str | None
    tailscale_required: bool
    tailscale_hostname: str | None
    tailscale_enable_ssh: bool
    bundle_uri: str | None
    bundle_sha256: str | None
    bundle_signature: str | None
    bundle_signature_scheme: str
    bundle_signature_key_id: str | None
    bundle_keyring_dir: Path | None
    bundle_install_dir: Path
    bundle_strip_components: int
    lte_apn: str | None
    lte_username: str | None
    lte_password: str | None
    lte_connection_name: str
    lte_ifname: str
    extra_agent_env: dict[str, str]
    profile: str = "standalone"
    image_profile_path: Path = DEFAULT_IMAGE_PROFILE_PATH
    lorawan_gateway_config_file: Path | None = None
    lorawan_registry_file: Path | None = None
    lorawan_radio_ingress_file: Path | None = None
    lorawan_vendor_config_file: Path | None = None
    gateway_power_env_file: Path | None = None
    gateway_config_dir: Path = DEFAULT_GATEWAY_CONFIG_DIR
    gateway_state_dir: Path = DEFAULT_GATEWAY_STATE_DIR
    gateway_radio_state_dir: Path = DEFAULT_GATEWAY_RADIO_STATE_DIR
    gateway_service_path: Path = DEFAULT_GATEWAY_SERVICE_PATH
    radio_service_path: Path = DEFAULT_RADIO_SERVICE_PATH
    camera_runtime_env_file: Path | None = None
    camera_credentials_file: Path | None = None
    model_public_key_file: Path | None = None
    model_public_key_id: str | None = None
    initial_model_bundle_file: Path | None = None
    camera_config_dir: Path = DEFAULT_CAMERA_CONFIG_DIR
    camera_service_path: Path = DEFAULT_CAMERA_SERVICE_PATH
    camera_wake_service_path: Path = DEFAULT_CAMERA_WAKE_SERVICE_PATH
    camera_poweroff_service_path: Path = DEFAULT_CAMERA_POWEROFF_SERVICE_PATH
    camera_poweroff_path: Path = DEFAULT_CAMERA_POWEROFF_PATH
    camera_model_recovery_service_path: Path = DEFAULT_CAMERA_MODEL_RECOVERY_SERVICE_PATH
    model_root: Path = DEFAULT_MODEL_ROOT


@dataclass(frozen=True)
class BundleActivation:
    install_dir: Path
    backup_dir: Path | None


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        tokens = shlex.split(line, comments=True, posix=True)
        if len(tokens) != 1 or "=" not in tokens[0]:
            continue
        key, value = tokens[0].split("=", 1)
        if key:
            values[key] = value
    return values


def parse_strict_env_file(path: Path, *, label: str) -> dict[str, str]:
    """Parse a closed provisioning env file without silently skipping malformed lines."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"{label} must be readable UTF-8 text") from exc
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            tokens = shlex.split(line, comments=True, posix=True)
        except ValueError as exc:
            raise ValueError(f"{label} line {line_number} is invalid") from exc
        if len(tokens) != 1 or "=" not in tokens[0]:
            raise ValueError(f"{label} line {line_number} must contain one NAME=value assignment")
        key, value = tokens[0].split("=", 1)
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is None or key in values:
            raise ValueError(f"{label} contains an invalid or duplicate setting: {key}")
        values[key] = value
    return values


def format_env_value(value: str) -> str:
    if value == "":
        return '""'
    if value.isalnum() or all(ch in "-_./:@+" for ch in value):
        return value
    return shlex.quote(value)


def write_text_if_changed(path: Path, content: str, mode: int | None = None) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    current = path.read_text() if path.exists() else None
    if current == content:
        if mode is not None:
            path.chmod(mode)
            _fsync_file(path)
            _fsync_directory(path.parent)
        return False
    temp_path = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"
    try:
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode or 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            temp_path.chmod(mode)
            _fsync_file(temp_path)
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    finally:
        temp_path.unlink(missing_ok=True)
    return True


def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _unlink_durable(path: Path) -> bool:
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    _fsync_directory(path.parent)
    return True


def _read_regular_boot_file(path: Path, *, label: str, maximum_bytes: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise FileNotFoundError(f"{label} not found: {path}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0 or metadata.st_size > maximum_bytes:
            raise ValueError(f"{label} must be a bounded regular file")
        payload = bytearray()
        while len(payload) <= maximum_bytes:
            chunk = os.read(descriptor, min(1024 * 1024, maximum_bytes + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
    finally:
        os.close(descriptor)
    if len(payload) > maximum_bytes:
        raise ValueError(f"{label} exceeds its size limit")
    return bytes(payload)


def write_bytes_if_changed(path: Path, content: bytes, mode: int) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    current = path.read_bytes() if path.exists() else None
    if current == content:
        path.chmod(mode)
        _fsync_file(path)
        _fsync_directory(path.parent)
        return False
    temporary = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex}"
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return True


def import_boot_file(
    source: Path,
    destination: Path,
    *,
    label: str,
    mode: int = 0o600,
    maximum_bytes: int = 1024 * 1024,
    private_source: bool = True,
) -> None:
    """Import a boot file idempotently; an installed destination supports retry."""

    if source.exists() or source.is_symlink():
        payload = _read_regular_boot_file(source, label=label, maximum_bytes=maximum_bytes)
        if private_source and stat.S_IMODE(source.lstat().st_mode) != 0o600:
            raise ValueError(f"{label} source must have mode 0600")
        write_bytes_if_changed(destination, payload, mode)
    elif not destination.is_file():
        raise FileNotFoundError(f"{label} not found: {source}")
    destination.chmod(mode)


def bool_from_text(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def validate_ota_gateway_cache_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError as exc:
        raise ValueError("EDGEWATCH_OTA_GATEWAY_CACHE_URL is invalid") from exc
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
        raise ValueError(
            "EDGEWATCH_OTA_GATEWAY_CACHE_URL must use a private maintenance IPv4 address and explicit HTTP port"
        )
    return value.rstrip("/")


def verify_image_profile(config: BootstrapConfig) -> bool:
    """Fail closed on a role/image mismatch; return whether an image marker existed."""

    path = config.image_profile_path
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"image profile marker must be a regular file: {path}")
    try:
        image_profile = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"image profile marker is unreadable: {path}") from exc
    if image_profile not in PROFILES:
        raise RuntimeError(f"image profile marker contains an unsupported profile: {image_profile}")
    if image_profile != config.profile:
        raise RuntimeError(
            f"provisioning profile {config.profile} does not match image profile {image_profile}"
        )
    return True


def required_text(config: dict[str, str], key: str) -> str:
    value = config.get(key)
    if not value:
        raise ValueError(f"missing required bootstrap setting: {key}")
    return value


def resolve_boot_config_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    for candidate in DEFAULT_BOOT_CONFIG_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "no bootstrap config found; expected one of "
        + ", ".join(str(candidate) for candidate in DEFAULT_BOOT_CONFIG_CANDIDATES)
    )


def _installed_agent_value(
    agent_env_path: Path,
    *,
    device_id: str,
    key: str,
) -> str | None:
    """Recover a persisted runtime value when a completed cleanup is retried."""

    try:
        installed = parse_env_file(agent_env_path)
    except (OSError, UnicodeError, ValueError):
        return None
    if installed.get("EDGEWATCH_DEVICE_ID") != device_id:
        return None
    value = installed.get(key, "").strip()
    return value or None


def build_config(raw: dict[str, str]) -> BootstrapConfig:
    repo_dir = Path(required_text(raw, "BOOTSTRAP_REPO_DIR")).expanduser()
    profile = raw.get("BOOTSTRAP_PROFILE", "standalone").strip().lower()
    if profile not in PROFILES:
        raise ValueError("BOOTSTRAP_PROFILE must be standalone, gateway, or camera-satellite")
    image_profile_path = Path(
        raw.get("BOOTSTRAP_IMAGE_PROFILE_PATH", str(DEFAULT_IMAGE_PROFILE_PATH))
    ).expanduser()
    data_dir = Path(raw.get("BOOTSTRAP_DATA_DIR", str(DEFAULT_DATA_DIR))).expanduser()
    agent_env_path = Path(
        raw.get("BOOTSTRAP_AGENT_ENV_PATH", str(repo_dir / DEFAULT_AGENT_ENV_PATH))
    ).expanduser()
    agent_service_path = Path(
        raw.get("BOOTSTRAP_AGENT_SERVICE_PATH", str(DEFAULT_AGENT_SERVICE_PATH))
    ).expanduser()
    firstboot_marker = Path(raw.get("BOOTSTRAP_FIRSTBOOT_MARKER", str(DEFAULT_FIRSTBOOT_MARKER))).expanduser()
    firstboot_report = Path(raw.get("BOOTSTRAP_FIRSTBOOT_REPORT", str(DEFAULT_FIRSTBOOT_REPORT))).expanduser()
    device_id = required_text(raw, "EDGEWATCH_DEVICE_ID")
    telemetry_transport = (
        raw.get("EDGEWATCH_TELEMETRY_TRANSPORT", DEFAULT_TELEMETRY_TRANSPORT).strip().lower()
    )
    allowed_transports = {"none"} if profile == "camera-satellite" else {"api", "telegram"}
    if telemetry_transport not in allowed_transports:
        choices = "'none'" if profile == "camera-satellite" else "'api' or 'telegram'"
        raise ValueError(f"EDGEWATCH_TELEMETRY_TRANSPORT must be {choices} for profile {profile}")
    api_url = raw.get("EDGEWATCH_API_URL")
    device_token = raw.get("EDGEWATCH_DEVICE_TOKEN")
    telegram_chat_id = raw.get("TELEGRAM_CHAT_ID")
    telegram_bot_token = raw.get("BOOTSTRAP_TELEGRAM_BOT_TOKEN")
    bootstrap_telegram_token_file_raw = raw.get("BOOTSTRAP_TELEGRAM_BOT_TOKEN_FILE")
    bootstrap_telegram_bot_token_file = (
        Path(bootstrap_telegram_token_file_raw).expanduser() if bootstrap_telegram_token_file_raw else None
    )
    telegram_token_file_raw = raw.get("TELEGRAM_BOT_TOKEN_FILE")
    if telemetry_transport == "api":
        api_url = required_text(raw, "EDGEWATCH_API_URL")
        device_token = device_token or _installed_agent_value(
            agent_env_path,
            device_id=device_id,
            key="EDGEWATCH_DEVICE_TOKEN",
        )
        if not device_token:
            raise ValueError("missing required bootstrap setting: EDGEWATCH_DEVICE_TOKEN")
    elif telemetry_transport == "telegram":
        telegram_chat_id = required_text(raw, "TELEGRAM_CHAT_ID")
        if not telegram_token_file_raw and (telegram_bot_token or bootstrap_telegram_bot_token_file):
            telegram_token_file_raw = str(data_dir / DEFAULT_TELEGRAM_TOKEN_FILENAME)
        if not telegram_token_file_raw:
            raise ValueError(
                "Telegram bootstrap requires TELEGRAM_BOT_TOKEN_FILE or a BOOTSTRAP_TELEGRAM_BOT_TOKEN source"
            )
    telegram_bot_token_file = Path(telegram_token_file_raw).expanduser() if telegram_token_file_raw else None
    if (
        bootstrap_telegram_bot_token_file
        and telegram_bot_token_file
        and bootstrap_telegram_bot_token_file.resolve() == telegram_bot_token_file.resolve()
    ):
        raise ValueError("BOOTSTRAP_TELEGRAM_BOT_TOKEN_FILE and TELEGRAM_BOT_TOKEN_FILE must differ")

    ssh_user = raw.get("BOOTSTRAP_SSH_USER", "ryne").strip()
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", ssh_user):
        raise ValueError("BOOTSTRAP_SSH_USER must be a valid Linux username")
    ssh_authorized_key_raw = raw.get("BOOTSTRAP_SSH_AUTHORIZED_KEY_FILE", "").strip()
    ssh_authorized_key_file = Path(ssh_authorized_key_raw).expanduser() if ssh_authorized_key_raw else None
    control_ssh_authorized_key_raw = raw.get("BOOTSTRAP_CONTROL_SSH_AUTHORIZED_KEY_FILE", "").strip()
    control_ssh_authorized_key_file = (
        Path(control_ssh_authorized_key_raw).expanduser() if control_ssh_authorized_key_raw else None
    )
    if (
        "BOOTSTRAP_PROFILE" in raw
        and profile == "standalone"
        and (ssh_authorized_key_file is None or control_ssh_authorized_key_file is None)
    ):
        raise ValueError("standalone profile requires operator and controller SSH public keys")
    if profile == "gateway" and ssh_authorized_key_file is None:
        raise ValueError("gateway profile requires an operator SSH public key")
    ota_public_key_raw = raw.get("BOOTSTRAP_OTA_PUBLIC_KEY_FILE", "").strip()
    ota_public_key_file = Path(ota_public_key_raw).expanduser() if ota_public_key_raw else None
    ota_public_key_id = raw.get("BOOTSTRAP_OTA_PUBLIC_KEY_ID", "").strip() or None
    if (ota_public_key_file is None) != (ota_public_key_id is None):
        raise ValueError(
            "BOOTSTRAP_OTA_PUBLIC_KEY_FILE and BOOTSTRAP_OTA_PUBLIC_KEY_ID must be configured together"
        )
    if ota_public_key_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", ota_public_key_id):
        raise ValueError("BOOTSTRAP_OTA_PUBLIC_KEY_ID is invalid")
    if ota_public_key_file is None and ("BOOTSTRAP_PROFILE" in raw or profile != "standalone"):
        raise ValueError(f"{profile} profile requires an OTA public trust key")

    python_bin = Path(raw.get("BOOTSTRAP_PYTHON_BIN", str(repo_dir / DEFAULT_AGENT_PYTHON))).expanduser()
    agent_entrypoint = Path(
        raw.get("BOOTSTRAP_AGENT_ENTRYPOINT", str(repo_dir / DEFAULT_AGENT_ENTRYPOINT))
    ).expanduser()
    agent_workdir = Path(
        raw.get("BOOTSTRAP_AGENT_WORKDIR", str(repo_dir / DEFAULT_AGENT_WORKDIR))
    ).expanduser()
    current_symlink_raw = raw.get("BOOTSTRAP_CURRENT_SYMLINK", "").strip()
    current_symlink = Path(current_symlink_raw).expanduser() if current_symlink_raw else None

    tailscale_auth_key = raw.get("BOOTSTRAP_TAILSCALE_AUTH_KEY")
    tailscale_required = bool(tailscale_auth_key) or bool_from_text(
        raw.get("BOOTSTRAP_TAILSCALE_ENROLLED"),
        default=False,
    )
    tailscale_hostname = raw.get("BOOTSTRAP_TAILSCALE_HOSTNAME", device_id)
    tailscale_enable_ssh = bool_from_text(raw.get("BOOTSTRAP_TAILSCALE_ENABLE_SSH"), default=False)

    bundle_uri = raw.get("BOOTSTRAP_BUNDLE_URI")
    bundle_sha256 = raw.get("BOOTSTRAP_BUNDLE_SHA256")
    bundle_signature = raw.get("BOOTSTRAP_BUNDLE_SIGNATURE")
    bundle_signature_scheme = raw.get("BOOTSTRAP_BUNDLE_SIGNATURE_SCHEME", "none")
    bundle_signature_key_id = raw.get("BOOTSTRAP_BUNDLE_SIGNATURE_KEY_ID")
    bundle_keyring_dir_raw = raw.get("BOOTSTRAP_BUNDLE_KEYRING_DIR")
    bundle_keyring_dir = Path(bundle_keyring_dir_raw).expanduser() if bundle_keyring_dir_raw else None
    bundle_install_dir_raw = raw.get("BOOTSTRAP_BUNDLE_INSTALL_DIR", str(repo_dir))
    bundle_install_dir = Path(bundle_install_dir_raw).expanduser()
    bundle_strip_components = int(raw.get("BOOTSTRAP_BUNDLE_STRIP_COMPONENTS", "1"))

    lte_apn = raw.get("BOOTSTRAP_LTE_APN")
    lte_username = raw.get("BOOTSTRAP_LTE_USERNAME")
    lte_password = raw.get("BOOTSTRAP_LTE_PASSWORD")
    lte_connection_name = raw.get("BOOTSTRAP_LTE_CONNECTION_NAME", DEFAULT_LTE_CONNECTION_NAME)
    lte_ifname = raw.get("BOOTSTRAP_LTE_IFNAME", DEFAULT_LTE_IFNAME)

    if profile == "gateway" and telemetry_transport != "telegram":
        raise ValueError("gateway profile must retain the existing Telegram telemetry transport")
    if profile == "camera-satellite":
        forbidden_camera_settings = sorted(
            key
            for key, value in raw.items()
            if value.strip()
            and (
                key.startswith("TELEGRAM_")
                or key.startswith("BOOTSTRAP_TELEGRAM_")
                or key.startswith("BOOTSTRAP_LTE_")
                or key in {"EDGEWATCH_API_URL", "EDGEWATCH_DEVICE_TOKEN"}
            )
        )
        if forbidden_camera_settings:
            raise ValueError(
                "camera-satellite profile must not contain Telegram, API, or LTE settings: "
                + ", ".join(forbidden_camera_settings)
            )
        lte_apn = None
        lte_username = None
        lte_password = None
        if control_ssh_authorized_key_file is None:
            raise ValueError("camera-satellite profile requires the gateway controller SSH public key")
        validate_ota_gateway_cache_url(required_text(raw, "EDGEWATCH_OTA_GATEWAY_CACHE_URL"))

    def optional_boot_path(name: str) -> Path | None:
        value = raw.get(name, "").strip()
        return Path(value).expanduser() if value else None

    lorawan_gateway_config_file = optional_boot_path("BOOTSTRAP_LORAWAN_GATEWAY_CONFIG_FILE")
    lorawan_registry_file = optional_boot_path("BOOTSTRAP_LORAWAN_REGISTRY_FILE")
    lorawan_radio_ingress_file = optional_boot_path("BOOTSTRAP_LORAWAN_RADIO_INGRESS_FILE")
    lorawan_vendor_config_file = optional_boot_path("BOOTSTRAP_LORAWAN_VENDOR_CONFIG_FILE")
    gateway_power_env_file = optional_boot_path("BOOTSTRAP_GATEWAY_POWER_ENV_FILE")
    gateway_inputs = (
        lorawan_gateway_config_file,
        lorawan_registry_file,
        lorawan_radio_ingress_file,
        lorawan_vendor_config_file,
        gateway_power_env_file,
    )
    if profile == "gateway" and not all(gateway_inputs):
        raise ValueError("gateway profile requires LoRaWAN gateway, registry, radio, vendor, and power files")
    if profile != "gateway" and any(gateway_inputs):
        raise ValueError("LoRaWAN bootstrap inputs are valid only for the gateway profile")

    camera_runtime_env_file = optional_boot_path("BOOTSTRAP_CAMERA_RUNTIME_ENV_FILE")
    camera_credentials_file = optional_boot_path("BOOTSTRAP_CAMERA_CREDENTIALS_FILE")
    model_public_key_file = optional_boot_path("BOOTSTRAP_MODEL_PUBLIC_KEY_FILE")
    model_public_key_id = raw.get("BOOTSTRAP_MODEL_PUBLIC_KEY_ID", "").strip() or None
    initial_model_bundle_file = optional_boot_path("BOOTSTRAP_INITIAL_MODEL_BUNDLE_FILE")
    camera_inputs = (camera_runtime_env_file, camera_credentials_file, model_public_key_file)
    if profile == "camera-satellite" and (
        not all(camera_inputs) or model_public_key_id is None or initial_model_bundle_file is None
    ):
        raise ValueError(
            "camera-satellite profile requires runtime env, RTSP credentials, model trust key, "
            "and initial signed model bundle"
        )
    if profile != "camera-satellite" and (
        any(camera_inputs) or model_public_key_id is not None or initial_model_bundle_file is not None
    ):
        raise ValueError("camera bootstrap inputs are valid only for the camera-satellite profile")
    if model_public_key_id and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", model_public_key_id) is None:
        raise ValueError("BOOTSTRAP_MODEL_PUBLIC_KEY_ID is invalid")

    gateway_config_dir = Path(
        raw.get("BOOTSTRAP_GATEWAY_CONFIG_DIR", str(DEFAULT_GATEWAY_CONFIG_DIR))
    ).expanduser()
    gateway_state_dir = Path(
        raw.get("BOOTSTRAP_GATEWAY_STATE_DIR", str(DEFAULT_GATEWAY_STATE_DIR))
    ).expanduser()
    gateway_radio_state_dir = Path(
        raw.get("BOOTSTRAP_GATEWAY_RADIO_STATE_DIR", str(DEFAULT_GATEWAY_RADIO_STATE_DIR))
    ).expanduser()
    gateway_service_path = Path(
        raw.get("BOOTSTRAP_GATEWAY_SERVICE_PATH", str(DEFAULT_GATEWAY_SERVICE_PATH))
    ).expanduser()
    radio_service_path = Path(
        raw.get("BOOTSTRAP_RADIO_SERVICE_PATH", str(DEFAULT_RADIO_SERVICE_PATH))
    ).expanduser()
    camera_config_dir = Path(
        raw.get("BOOTSTRAP_CAMERA_CONFIG_DIR", str(DEFAULT_CAMERA_CONFIG_DIR))
    ).expanduser()
    camera_service_path = Path(
        raw.get("BOOTSTRAP_CAMERA_SERVICE_PATH", str(DEFAULT_CAMERA_SERVICE_PATH))
    ).expanduser()
    camera_wake_service_path = Path(
        raw.get("BOOTSTRAP_CAMERA_WAKE_SERVICE_PATH", str(DEFAULT_CAMERA_WAKE_SERVICE_PATH))
    ).expanduser()
    camera_poweroff_service_path = Path(
        raw.get(
            "BOOTSTRAP_CAMERA_POWEROFF_SERVICE_PATH",
            str(DEFAULT_CAMERA_POWEROFF_SERVICE_PATH),
        )
    ).expanduser()
    camera_poweroff_path = Path(
        raw.get("BOOTSTRAP_CAMERA_POWEROFF_PATH", str(DEFAULT_CAMERA_POWEROFF_PATH))
    ).expanduser()
    camera_model_recovery_service_path = Path(
        raw.get(
            "BOOTSTRAP_CAMERA_MODEL_RECOVERY_SERVICE_PATH",
            str(DEFAULT_CAMERA_MODEL_RECOVERY_SERVICE_PATH),
        )
    ).expanduser()
    model_root = Path(raw.get("BOOTSTRAP_MODEL_ROOT", str(DEFAULT_MODEL_ROOT))).expanduser()

    extra_agent_env = {
        key: value
        for key, value in raw.items()
        if not key.startswith("BOOTSTRAP_") and key in AGENT_ENV_ALLOWLIST
    }

    return BootstrapConfig(
        repo_dir=repo_dir,
        data_dir=data_dir,
        agent_env_path=agent_env_path,
        agent_service_path=agent_service_path,
        firstboot_marker=firstboot_marker,
        firstboot_report=firstboot_report,
        device_id=device_id,
        telemetry_transport=telemetry_transport,
        api_url=api_url,
        device_token=device_token,
        telegram_chat_id=telegram_chat_id,
        telegram_bot_token_file=telegram_bot_token_file,
        telegram_bot_token=telegram_bot_token,
        bootstrap_telegram_bot_token_file=bootstrap_telegram_bot_token_file,
        ssh_user=ssh_user,
        ssh_authorized_key_file=ssh_authorized_key_file,
        control_ssh_authorized_key_file=control_ssh_authorized_key_file,
        ota_public_key_file=ota_public_key_file,
        ota_public_key_id=ota_public_key_id,
        sensor_config_path=raw.get("SENSOR_CONFIG_PATH", DEFAULT_SENSOR_CONFIG),
        runtime_power_mode=raw.get("RUNTIME_POWER_MODE", DEFAULT_RUNTIME_POWER_MODE),
        deep_sleep_backend=raw.get("DEEP_SLEEP_BACKEND", DEFAULT_DEEP_SLEEP_BACKEND),
        allow_remote_shutdown=raw.get("EDGEWATCH_ALLOW_REMOTE_SHUTDOWN", DEFAULT_REMOTE_SHUTDOWN),
        enable_ota_apply=raw.get("EDGEWATCH_ENABLE_OTA_APPLY", DEFAULT_OTA_APPLY),
        power_mgmt_enabled=raw.get("POWER_MGMT_ENABLED", DEFAULT_POWER_MGMT_ENABLED),
        power_mgmt_mode=raw.get("POWER_MGMT_MODE", DEFAULT_POWER_MGMT_MODE),
        python_bin=python_bin,
        agent_entrypoint=agent_entrypoint,
        agent_workdir=agent_workdir,
        current_symlink=current_symlink,
        tailscale_auth_key=tailscale_auth_key,
        tailscale_required=tailscale_required,
        tailscale_hostname=tailscale_hostname,
        tailscale_enable_ssh=tailscale_enable_ssh,
        bundle_uri=bundle_uri,
        bundle_sha256=bundle_sha256,
        bundle_signature=bundle_signature,
        bundle_signature_scheme=bundle_signature_scheme,
        bundle_signature_key_id=bundle_signature_key_id,
        bundle_keyring_dir=bundle_keyring_dir,
        bundle_install_dir=bundle_install_dir,
        bundle_strip_components=bundle_strip_components,
        lte_apn=lte_apn,
        lte_username=lte_username,
        lte_password=lte_password,
        lte_connection_name=lte_connection_name,
        lte_ifname=lte_ifname,
        extra_agent_env=extra_agent_env,
        profile=profile,
        image_profile_path=image_profile_path,
        lorawan_gateway_config_file=lorawan_gateway_config_file,
        lorawan_registry_file=lorawan_registry_file,
        lorawan_radio_ingress_file=lorawan_radio_ingress_file,
        lorawan_vendor_config_file=lorawan_vendor_config_file,
        gateway_power_env_file=gateway_power_env_file,
        gateway_config_dir=gateway_config_dir,
        gateway_state_dir=gateway_state_dir,
        gateway_radio_state_dir=gateway_radio_state_dir,
        gateway_service_path=gateway_service_path,
        radio_service_path=radio_service_path,
        camera_runtime_env_file=camera_runtime_env_file,
        camera_credentials_file=camera_credentials_file,
        model_public_key_file=model_public_key_file,
        model_public_key_id=model_public_key_id,
        initial_model_bundle_file=initial_model_bundle_file,
        camera_config_dir=camera_config_dir,
        camera_service_path=camera_service_path,
        camera_wake_service_path=camera_wake_service_path,
        camera_poweroff_service_path=camera_poweroff_service_path,
        camera_poweroff_path=camera_poweroff_path,
        camera_model_recovery_service_path=camera_model_recovery_service_path,
        model_root=model_root,
    )


def _agent_ready_path(config: BootstrapConfig) -> Path:
    configured = config.extra_agent_env.get("EDGEWATCH_READY_PATH", "").strip()
    return Path(configured) if configured else config.data_dir / f"ready_{config.device_id}.json"


def render_agent_env(config: BootstrapConfig, *, redact_secrets: bool = False) -> str:
    env: dict[str, str] = {
        "EDGEWATCH_TELEMETRY_TRANSPORT": config.telemetry_transport,
        "EDGEWATCH_DEVICE_ID": config.device_id,
        "SENSOR_CONFIG_PATH": config.sensor_config_path,
        "BUFFER_DB_PATH": str(config.data_dir / "telemetry_buffer.sqlite"),
        "EDGEWATCH_COST_CAP_STATE_PATH": str(config.data_dir / f"cost_caps_{config.device_id}.json"),
        "EDGEWATCH_POLICY_CACHE_PATH": str(config.data_dir / f"policy_cache_{config.device_id}.json"),
        "EDGEWATCH_POWER_STATE_PATH": str(config.data_dir / f"power_state_{config.device_id}.json"),
        "EDGEWATCH_COMMAND_STATE_PATH": str(config.data_dir / f"command_state_{config.device_id}.json"),
        "EDGEWATCH_UPDATE_STATE_PATH": str(config.data_dir / f"update_state_{config.device_id}.json"),
        "EDGEWATCH_LOW_POWER_STATE_PATH": str(config.data_dir / f"low_power_state_{config.device_id}.json"),
        "EDGEWATCH_DEADLETTER_PATH": str(config.data_dir / f"deadletter_{config.device_id}.jsonl"),
        "EDGEWATCH_READY_PATH": str(_agent_ready_path(config)),
        "RUNTIME_POWER_MODE": config.runtime_power_mode,
        "DEEP_SLEEP_BACKEND": config.deep_sleep_backend,
        "EDGEWATCH_ALLOW_REMOTE_SHUTDOWN": config.allow_remote_shutdown,
        "EDGEWATCH_ENABLE_OTA_APPLY": config.enable_ota_apply,
        "POWER_MGMT_ENABLED": config.power_mgmt_enabled,
        "POWER_MGMT_MODE": config.power_mgmt_mode,
    }
    if config.telemetry_transport == "api":
        env["EDGEWATCH_API_URL"] = config.api_url or ""
        env["EDGEWATCH_DEVICE_TOKEN"] = "REDACTED" if redact_secrets else config.device_token or ""
    elif config.telemetry_transport == "telegram":
        env["TELEGRAM_CHAT_ID"] = config.telegram_chat_id or ""
        env["TELEGRAM_BOT_TOKEN_FILE"] = str(config.telegram_bot_token_file)
    env.update(config.extra_agent_env)
    if config.telemetry_transport != "api":
        env.pop("EDGEWATCH_API_URL", None)
        env.pop("EDGEWATCH_DEVICE_TOKEN", None)
    if "CELLULAR_METRICS_ENABLED" in env and "CELLULAR_INTERFACE" not in env:
        env["CELLULAR_INTERFACE"] = "wwan0"
    if "CELLULAR_WATCHDOG_ENABLED" in env and "CELLULAR_WATCHDOG_DNS_HOST" not in env:
        env["CELLULAR_WATCHDOG_DNS_HOST"] = "www.gstatic.com"
    if "CELLULAR_METRICS_ENABLED" in env and "CELLULAR_USAGE_STATE_PATH" not in env:
        env["CELLULAR_USAGE_STATE_PATH"] = str(config.data_dir / f"cellular_usage_{config.device_id}.json")

    lines = [
        "# EdgeWatch agent environment generated by rpi_bootstrap.py",
        "# Manual edits are allowed, but the first-boot bootstrap will recreate this file if rerun.",
        "",
    ]
    for key in sorted(env):
        lines.append(f"{key}={format_env_value(env[key])}")
    lines.append("")
    return "\n".join(lines)


def render_agent_service(config: BootstrapConfig) -> str:
    return (
        "[Unit]\n"
        "Description=EdgeWatch Agent\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "StartLimitIntervalSec=300\n"
        "StartLimitBurst=10\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={config.agent_workdir}\n"
        f"EnvironmentFile={config.agent_env_path}\n"
        f"ExecStartPre=/usr/bin/rm -f {_agent_ready_path(config)}\n"
        f"ExecStart={config.python_bin} {config.agent_entrypoint}\n"
        "Restart=always\n"
        "RestartSec=5\n"
        "TimeoutStopSec=30\n"
        "UMask=0077\n\n"
        "# Hardening\n"
        "NoNewPrivileges=true\n"
        "PrivateTmp=true\n"
        "ProtectSystem=strict\n"
        "ProtectHome=read-only\n"
        f"ReadWritePaths={config.data_dir}\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _download_to_path(uri: str, dest: Path) -> None:
    if uri.startswith("file://"):
        source = Path(uri.removeprefix("file://"))
        if not source.exists():
            raise FileNotFoundError(f"bundle source missing: {source}")
        dest.write_bytes(source.read_bytes())
        return
    with urllib.request.urlopen(uri, timeout=60) as response, dest.open("wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def _verify_bundle_signature(
    *,
    artifact_path: Path,
    signature: str,
    signature_scheme: str,
    signature_key_id: str,
    keyring_dir: Path,
) -> tuple[bool, str]:
    scheme = signature_scheme.strip().lower()
    if scheme == "none":
        return True, "signature verification disabled"
    if scheme != "openssl_rsa_sha256":
        return False, f"unsupported_signature_scheme={scheme}"
    pubkey = keyring_dir / f"{signature_key_id}.pem"
    if not pubkey.exists():
        return False, f"missing_signature_key={pubkey}"
    try:
        sig_bytes = base64.b64decode(signature)
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        return False, f"invalid_signature_encoding: {exc!r}"
    with NamedTemporaryFile(suffix=".sig", delete=True) as sigfile:
        sigfile.write(sig_bytes)
        sigfile.flush()
        proc = subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-verify",
                str(pubkey),
                "-signature",
                sigfile.name,
                str(artifact_path),
            ],
            capture_output=True,
            text=True,
        )
    if proc.returncode != 0:
        out = (proc.stdout or proc.stderr or "").strip()
        return False, f"artifact_signature_verification_failed: {out[:240]}"
    return True, "signature verified"


def _strip_components(parts: tuple[str, ...], count: int) -> tuple[str, ...]:
    if count <= 0:
        return parts
    if len(parts) <= count:
        return ()
    return parts[count:]


def _clean_extract_path(base_dir: Path, relative_parts: tuple[str, ...]) -> Path:
    target = base_dir.joinpath(*relative_parts)
    target_resolved = target.resolve()
    base_resolved = base_dir.resolve()
    if base_resolved not in target_resolved.parents and target_resolved != base_resolved:
        raise ValueError(f"refusing to extract outside target directory: {target}")
    return target


def _extract_zip(archive_path: Path, dest_dir: Path, strip_components: int) -> None:
    with zipfile.ZipFile(archive_path) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            rel = Path(member.filename)
            stripped = _strip_components(rel.parts, strip_components)
            if not stripped:
                continue
            target = _clean_extract_path(dest_dir, stripped)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, target.open("wb") as dst:
                dst.write(src.read())


def _extract_tar(archive_path: Path, dest_dir: Path, strip_components: int) -> None:
    with tarfile.open(archive_path) as tf:
        for member in tf.getmembers():
            if member.isdir():
                continue
            rel = Path(member.name)
            stripped = _strip_components(rel.parts, strip_components)
            if not stripped:
                continue
            target = _clean_extract_path(dest_dir, stripped)
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = tf.extractfile(member)
            if extracted is None:
                continue
            with extracted, target.open("wb") as dst:
                shutil.copyfileobj(extracted, dst)
            target.chmod(member.mode & 0o777)


def _extract_bundle(archive_path: Path, dest_dir: Path, strip_components: int) -> None:
    suffixes = [suffix.lower() for suffix in archive_path.suffixes]
    if suffixes[-1:] == [".zip"]:
        _extract_zip(archive_path, dest_dir, strip_components)
        return
    if suffixes[-2:] == [".tar", ".gz"] or suffixes[-1:] in ([".tgz"], [".tar"], [".xz"]):
        _extract_tar(archive_path, dest_dir, strip_components)
        return
    raise ValueError(f"unsupported bundle format: {archive_path.name}")


def _bundle_relative_path(path: Path, repo_dir: Path, *, setting: str) -> Path:
    try:
        return path.resolve().relative_to(repo_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"{setting} must be inside BOOTSTRAP_REPO_DIR for bundle installs") from exc


def _prepare_staged_bundle(config: BootstrapConfig, staging_dir: Path) -> None:
    """Preserve the image-provided venv and prove the staged runtime is complete."""

    live_venv = config.bundle_install_dir / ".venv"
    staged_venv = staging_dir / ".venv"
    if not staged_venv.exists() and live_venv.is_dir():
        shutil.copytree(live_venv, staged_venv, symlinks=True)

    expected = {
        "agent python binary": staging_dir
        / _bundle_relative_path(config.python_bin, config.repo_dir, setting="BOOTSTRAP_PYTHON_BIN"),
        "agent entrypoint": staging_dir
        / _bundle_relative_path(
            config.agent_entrypoint,
            config.repo_dir,
            setting="BOOTSTRAP_AGENT_ENTRYPOINT",
        ),
        "agent workdir": staging_dir
        / _bundle_relative_path(
            config.agent_workdir,
            config.repo_dir,
            setting="BOOTSTRAP_AGENT_WORKDIR",
        ),
    }
    missing = [label for label, path in expected.items() if not path.exists()]
    if missing:
        raise ValueError("deployment bundle is missing required runtime paths: " + ", ".join(missing))


def _activate_staged_bundle(
    *,
    staging_dir: Path,
    install_dir: Path,
    logger: logging.Logger,
) -> BundleActivation:
    """Atomically replace the live tree and restore it if activation fails."""

    backup_dir = install_dir.parent / f".{install_dir.name}.backup-{uuid.uuid4().hex}"
    had_live_install = install_dir.exists()
    if had_live_install:
        os.replace(install_dir, backup_dir)
    try:
        os.replace(staging_dir, install_dir)
    except Exception:
        if had_live_install and backup_dir.exists() and not install_dir.exists():
            os.replace(backup_dir, install_dir)
        raise

    return BundleActivation(
        install_dir=install_dir,
        backup_dir=backup_dir if had_live_install else None,
    )


def _commit_bundle_activation(activation: BundleActivation, logger: logging.Logger) -> None:
    if activation.backup_dir is None or not activation.backup_dir.exists():
        return
    try:
        shutil.rmtree(activation.backup_dir)
    except OSError as exc:  # pragma: no cover - cleanup is best effort after a healthy activation
        logger.warning("could not remove previous deployment backup %s: %s", activation.backup_dir, exc)


def _rollback_bundle_activation(activation: BundleActivation, logger: logging.Logger) -> None:
    install_dir = activation.install_dir
    backup_dir = activation.backup_dir
    if backup_dir is None:
        if install_dir.exists():
            shutil.rmtree(install_dir)
        return
    if not backup_dir.exists():
        raise RuntimeError(f"deployment rollback backup is missing: {backup_dir}")

    failed_dir = install_dir.parent / f".{install_dir.name}.failed-{uuid.uuid4().hex}"
    if install_dir.exists():
        os.replace(install_dir, failed_dir)
    try:
        os.replace(backup_dir, install_dir)
    except Exception:
        if failed_dir.exists() and not install_dir.exists():
            os.replace(failed_dir, install_dir)
        raise
    if failed_dir.exists():
        try:
            shutil.rmtree(failed_dir)
        except OSError as exc:  # pragma: no cover - cleanup is best effort after restoration
            logger.warning("could not remove failed deployment tree %s: %s", failed_dir, exc)


def _restart_restored_agent(activation: BundleActivation) -> None:
    if activation.backup_dir is None:
        return
    run_required(["systemctl", "daemon-reload"], "reload systemd after deployment rollback")
    run_required(
        ["systemctl", "restart", DEFAULT_AGENT_SERVICE_NAME],
        "restart restored edgewatch-agent",
    )
    run_required(
        ["systemctl", "is-active", "--quiet", DEFAULT_AGENT_SERVICE_NAME],
        "verify restored edgewatch-agent health",
    )


def install_bundle(
    config: BootstrapConfig,
    logger: logging.Logger,
    *,
    retain_previous: bool = False,
) -> BundleActivation | None:
    if not config.bundle_uri:
        logger.info("bundle URI not provided; skipping deployment bundle install")
        return None
    config.bundle_install_dir.parent.mkdir(parents=True, exist_ok=True)
    cache_dir = DEFAULT_BUNDLE_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive_name = Path(urllib.parse.urlparse(config.bundle_uri).path).name or "edgewatch-bundle.tar.gz"
    archive_path = cache_dir / archive_name
    _download_to_path(config.bundle_uri, archive_path)

    expected_sha = (config.bundle_sha256 or "").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise ValueError("BOOTSTRAP_BUNDLE_SHA256 is required and must be 64 lowercase hex characters")
    actual_sha = _sha256_file(archive_path)
    if actual_sha != expected_sha:
        raise ValueError(f"bundle sha256 mismatch expected={expected_sha} actual={actual_sha}")

    signature_fields = (
        bool(config.bundle_signature),
        bool(config.bundle_signature_key_id),
        config.bundle_keyring_dir is not None,
    )
    if any(signature_fields) and not all(signature_fields):
        raise ValueError(
            "bundle signature, signature key id, and keyring directory must be configured together"
        )
    signature_scheme = config.bundle_signature_scheme.strip().lower()
    if all(signature_fields) and signature_scheme == "none":
        raise ValueError(
            "BOOTSTRAP_BUNDLE_SIGNATURE_SCHEME cannot be 'none' when bundle signature fields are configured"
        )
    if all(signature_fields):
        assert config.bundle_signature is not None
        assert config.bundle_signature_key_id is not None
        assert config.bundle_keyring_dir is not None
        ok, reason = _verify_bundle_signature(
            artifact_path=archive_path,
            signature=config.bundle_signature,
            signature_scheme=config.bundle_signature_scheme,
            signature_key_id=config.bundle_signature_key_id,
            keyring_dir=config.bundle_keyring_dir,
        )
        if not ok:
            raise ValueError(reason)

    staging_dir = (
        config.bundle_install_dir.parent / f".{config.bundle_install_dir.name}.staging-{uuid.uuid4().hex}"
    )
    staging_dir.mkdir(mode=0o755)
    try:
        _extract_bundle(archive_path, staging_dir, config.bundle_strip_components)
        _prepare_staged_bundle(config, staging_dir)
        activation = _activate_staged_bundle(
            staging_dir=staging_dir,
            install_dir=config.bundle_install_dir,
            logger=logger,
        )
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
    if not retain_previous:
        _commit_bundle_activation(activation, logger)
    logger.info("installed deployment bundle into %s", config.bundle_install_dir)
    return activation


def device_hostname(device_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", device_id.strip().lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")[:63].rstrip("-")
    if normalized:
        return normalized
    digest = hashlib.sha256(device_id.encode("utf-8")).hexdigest()[:12]
    return f"edgewatch-{digest}"


def configure_hostname(config: BootstrapConfig) -> None:
    run_required(
        ["hostnamectl", "set-hostname", device_hostname(config.device_id)],
        "set device hostname",
    )


def render_lte_connection(config: BootstrapConfig, *, redact_secrets: bool = False) -> str:
    if not config.lte_apn:
        raise ValueError("LTE APN is required to render a NetworkManager profile")
    connection_uuid = uuid.uuid5(
        uuid.NAMESPACE_URL, f"edgewatch:{config.device_id}:{config.lte_connection_name}"
    )
    lines = [
        "[connection]",
        f"id={config.lte_connection_name}",
        f"uuid={connection_uuid}",
        "type=gsm",
        "autoconnect=true",
        "",
        "[gsm]",
        f"apn={config.lte_apn}",
        "home-only=false",
    ]
    if config.lte_username:
        lines.append(f"username={config.lte_username}")
    if config.lte_password:
        password = "REDACTED" if redact_secrets else config.lte_password
        lines.append(f"password={password}")
    lines.extend(
        [
            "",
            "[ipv4]",
            "method=auto",
            "",
            "[ipv6]",
            "method=ignore",
            "",
        ]
    )
    return "\n".join(lines)


def write_lte_profile(config: BootstrapConfig, logger: logging.Logger) -> None:
    if not config.lte_apn:
        logger.info("LTE APN not provided; skipping NetworkManager profile generation")
        return
    profile_path = DEFAULT_NETWORKMANAGER_CONNECTION_DIR / f"{config.lte_connection_name}.nmconnection"
    render_config = config
    if config.lte_password is None and profile_path.is_file():
        current = profile_path.read_text(encoding="utf-8")
        existing_password = next(
            (
                line.split("=", 1)[1]
                for line in current.splitlines()
                if line.startswith("password=") and line.split("=", 1)[1]
            ),
            None,
        )
        if existing_password is not None:
            render_config = replace(config, lte_password=existing_password)
    content = render_lte_connection(render_config)
    write_text_if_changed(profile_path, content, mode=0o600)
    logger.info("wrote NetworkManager LTE profile: %s", profile_path)

    run_required(["nmcli", "connection", "reload"], "reload NetworkManager connections")
    run_required(["nmcli", "connection", "up", config.lte_connection_name], "activate LTE profile")


def write_tailscale_secret_file(config: BootstrapConfig) -> Path:
    secret_path = config.data_dir / ".tailscale-auth-key"
    write_text_if_changed(secret_path, f"{config.tailscale_auth_key}\n", mode=0o600)
    return secret_path


def run_required(command: list[str], description: str) -> None:
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"{description} failed: command not found ({command[0]})") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"{description} failed with exit code {exc.returncode}") from exc


def run_capture_required(command: list[str], description: str) -> str:
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"{description} failed: command not found ({command[0]})") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"{description} failed with exit code {exc.returncode}") from exc
    return (completed.stdout or "").strip()


def shutil_which(command: str) -> str | None:
    from shutil import which

    return which(command)


def write_systemd_service(config: BootstrapConfig, logger: logging.Logger) -> None:
    write_text_if_changed(config.agent_service_path, render_agent_service(config), mode=0o644)
    logger.info("wrote systemd service: %s", config.agent_service_path)


def ensure_current_release_symlink(config: BootstrapConfig) -> None:
    """Create the stable runtime link used by application-bundle OTA."""

    current = config.current_symlink
    if current is None:
        return
    current.parent.mkdir(parents=True, exist_ok=True)
    expected = config.repo_dir.resolve()
    if current.is_symlink():
        target = Path(os.readlink(current))
        resolved = (current.parent / target).resolve() if not target.is_absolute() else target.resolve()
        if resolved != expected:
            raise RuntimeError(f"current release symlink points to an unexpected target: {current}")
        return
    if current.exists():
        raise RuntimeError(f"current release path must be absent or a symbolic link: {current}")
    temp = current.parent / f".{current.name}.tmp-{uuid.uuid4().hex}"
    try:
        temp.symlink_to(expected, target_is_directory=True)
        os.replace(temp, current)
        _fsync_directory(current.parent)
    finally:
        temp.unlink(missing_ok=True)


def install_agent_service(config: BootstrapConfig, logger: logging.Logger) -> None:
    if not config.python_bin.exists():
        raise FileNotFoundError(f"agent python binary not found: {config.python_bin}")
    if not config.agent_entrypoint.exists():
        raise FileNotFoundError(f"agent entrypoint not found: {config.agent_entrypoint}")
    if not config.agent_workdir.exists():
        raise FileNotFoundError(f"agent workdir not found: {config.agent_workdir}")

    write_text_if_changed(config.agent_env_path, render_agent_env(config), mode=0o600)
    write_systemd_service(config, logger)
    run_required(["systemctl", "daemon-reload"], "reload systemd")
    run_required(["systemctl", "enable", DEFAULT_AGENT_SERVICE_NAME], "enable edgewatch-agent")
    run_required(["systemctl", "restart", DEFAULT_AGENT_SERVICE_NAME], "restart edgewatch-agent")


def ensure_service_account(username: str, *, state_dir: Path) -> None:
    if re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username) is None:
        raise ValueError("service account name is invalid")
    try:
        pwd.getpwnam(username)
        return
    except KeyError:
        pass
    run_required(
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
        f"create {username} service account",
    )


def _chown(path: Path, owner: str) -> None:
    run_required(["/usr/bin/chown", f"{owner}:{owner}", str(path)], f"secure {path.name} ownership")


def _chgrp(path: Path, group: str) -> None:
    run_required(["/usr/bin/chown", f"root:{group}", str(path)], f"secure {path.name} ownership")


def render_gateway_radio_service(config: BootstrapConfig) -> str:
    python = config.python_bin
    return f"""[Unit]
Description=EdgeWatch pinned SX1302/SX1303 radio and ChirpStack ingress adapter
After=network-online.target mosquitto.service
Wants=network-online.target
Requires=mosquitto.service
Before={GATEWAY_SERVICE_NAME}.service
ConditionPathExists={config.gateway_config_dir / "lorawan-radio-ingress.yaml"}
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=edgewatch-controller
Group=edgewatch-controller
SupplementaryGroups=spi gpio
WorkingDirectory={config.current_symlink or config.repo_dir}
ExecStart={python} -m agent.lorawan.radio_cli run --config {config.gateway_config_dir / "lorawan-radio-ingress.yaml"}
ExecStartPost={python} -m agent.lorawan.radio_cli check --config {config.gateway_config_dir / "lorawan-radio-ingress.yaml"}
Restart=on-failure
RestartSec=10
TimeoutStartSec=620
TimeoutStopSec=30
UMask=0077
Environment=PYTHONUNBUFFERED=1
RuntimeDirectory=edgewatch-lorawan-radio
RuntimeDirectoryMode=0700
NoNewPrivileges=true
PrivateDevices=false
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
DevicePolicy=closed
DeviceAllow=/dev/spidev0.0 rw
DeviceAllow=/dev/gpiochip0 rw
ReadWritePaths={config.gateway_radio_state_dir} /run/edgewatch-lorawan-radio

[Install]
WantedBy=multi-user.target
"""


def render_gateway_service(config: BootstrapConfig) -> str:
    return f"""[Unit]
Description=EdgeWatch LoRaWAN ingest and durable telemetry delivery
After=network-online.target mosquitto.service redis-server.service chirpstack.service {RADIO_SERVICE_NAME}.service
Wants=network-online.target
Requires=mosquitto.service {RADIO_SERVICE_NAME}.service
BindsTo={RADIO_SERVICE_NAME}.service
ConditionPathExists={config.gateway_config_dir / "lorawan-gateway.yaml"}
StartLimitIntervalSec=300
StartLimitBurst=10

[Service]
Type=simple
User=edgewatch-controller
Group=edgewatch-controller
WorkingDirectory={config.current_symlink or config.repo_dir}
ExecStart={config.python_bin} -m agent.lorawan --config {config.gateway_config_dir / "lorawan-gateway.yaml"}
Restart=always
RestartSec=5
TimeoutStopSec=30
UMask=0077
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-{config.gateway_config_dir / "gateway-power.env"}
NoNewPrivileges=true
PrivateDevices=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadWritePaths={config.gateway_state_dir} {config.gateway_radio_state_dir}

[Install]
WantedBy=multi-user.target
"""


def install_gateway_runtime(config: BootstrapConfig, logger: logging.Logger) -> None:
    sources = {
        "lorawan-gateway.yaml": config.lorawan_gateway_config_file,
        "lorawan-registry.yaml": config.lorawan_registry_file,
        "lorawan-radio-ingress.yaml": config.lorawan_radio_ingress_file,
        "sx1302-adapter.yaml": config.lorawan_vendor_config_file,
        "gateway-power.env": config.gateway_power_env_file,
    }
    if any(source is None for source in sources.values()):
        raise ValueError("gateway bootstrap inputs are incomplete")
    ensure_service_account("edgewatch-controller", state_dir=config.gateway_state_dir)
    config.gateway_config_dir.mkdir(parents=True, exist_ok=True)
    config.gateway_config_dir.chmod(0o750)
    _chgrp(config.gateway_config_dir, "edgewatch-controller")
    config.gateway_state_dir.mkdir(parents=True, exist_ok=True)
    config.gateway_state_dir.chmod(0o700)
    _chown(config.gateway_state_dir, "edgewatch-controller")
    radio_state_dir = config.gateway_radio_state_dir
    radio_state_dir.mkdir(parents=True, exist_ok=True)
    radio_state_dir.chmod(0o700)
    _chown(radio_state_dir, "edgewatch-controller")
    for name, source in sources.items():
        assert source is not None
        destination = config.gateway_config_dir / name
        import_boot_file(source, destination, label=f"gateway {name}")
        _chown(destination, "edgewatch-controller")
    if config.telegram_bot_token_file is None:
        raise ValueError("gateway Telegram token destination is unavailable")
    _chown(config.telegram_bot_token_file, "edgewatch-controller")

    # The production loader validates the closed schema and every installed private path.
    from agent.lorawan.service import load_gateway_service_config
    from gateway_runtime.lte_power import load_gateway_power_config

    load_gateway_service_config(config.gateway_config_dir / "lorawan-gateway.yaml")
    power_values = parse_strict_env_file(
        config.gateway_config_dir / "gateway-power.env",
        label="gateway power environment",
    )
    unknown_power_keys = sorted(set(power_values) - GATEWAY_POWER_ENV_KEYS)
    if unknown_power_keys:
        raise ValueError(
            "gateway power environment contains unsupported settings: " + ", ".join(unknown_power_keys)
        )
    load_gateway_power_config(power_values)
    write_text_if_changed(config.radio_service_path, render_gateway_radio_service(config), mode=0o644)
    write_text_if_changed(config.gateway_service_path, render_gateway_service(config), mode=0o644)
    run_required(["systemctl", "daemon-reload"], "reload gateway systemd units")
    run_required(["systemctl", "enable", RADIO_SERVICE_NAME], "enable LoRaWAN radio ingress")
    run_required(["systemctl", "enable", GATEWAY_SERVICE_NAME], "enable LoRaWAN gateway")
    run_required(["systemctl", "restart", RADIO_SERVICE_NAME], "start pinned LoRaWAN radio ingress")
    run_required(["systemctl", "restart", GATEWAY_SERVICE_NAME], "start LoRaWAN gateway")
    logger.info("installed fail-closed LoRaWAN gateway and radio supervisor")


def render_camera_check_service(config: BootstrapConfig) -> str:
    runtime_env = config.camera_config_dir / "camera-satellite.env"
    return f"""[Unit]
Description=EdgeWatch camera satellite local %i cycle
After=network-online.target {CAMERA_MODEL_RECOVERY_SERVICE_NAME}
Wants=network-online.target
Requires={CAMERA_MODEL_RECOVERY_SERVICE_NAME}
ConditionPathExists={runtime_env}
ConditionPathExists={config.model_root / "current"}
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=oneshot
User=edgewatch-camera
Group=edgewatch-camera
WorkingDirectory={config.current_symlink or config.repo_dir}
EnvironmentFile={runtime_env}
ExecCondition=/usr/bin/test %i = check
ExecStart={config.python_bin} -m agent.camera_satellite_runner --mode %i
TimeoutStartSec=180
RuntimeMaxSec=180
UMask=0077
StateDirectory=edgewatch-camera-satellite edgewatch-media
StateDirectoryMode=0700
RuntimeDirectory=edgewatch-camera-satellite
RuntimeDirectoryMode=0700
RuntimeDirectoryPreserve=yes
NoNewPrivileges=true
PrivateDevices=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
MemoryMax=384M
TasksMax=64
"""


def render_camera_wake_service(config: BootstrapConfig) -> str:
    runtime_env = config.camera_config_dir / "camera-satellite.env"
    return f"""[Unit]
Description=EdgeWatch camera satellite MCU wake %i cycle with clean poweroff
After=network-online.target edgewatch-camera-satellite-poweroff.path {CAMERA_MODEL_RECOVERY_SERVICE_NAME}
Wants=network-online.target edgewatch-camera-satellite-poweroff.path
Requires={CAMERA_MODEL_RECOVERY_SERVICE_NAME}
ConditionPathExists={runtime_env}
ConditionPathExists={config.model_root / "current"}

[Service]
Type=oneshot
User=edgewatch-camera
Group=edgewatch-camera
WorkingDirectory={config.current_symlink or config.repo_dir}
EnvironmentFile={runtime_env}
ExecStart={config.python_bin} -m agent.camera_satellite_runner --mode %i --poweroff-on-success
TimeoutStartSec=180
RuntimeMaxSec=180
UMask=0077
StateDirectory=edgewatch-camera-satellite edgewatch-media
StateDirectoryMode=0700
RuntimeDirectory=edgewatch-camera-satellite
RuntimeDirectoryMode=0700
RuntimeDirectoryPreserve=yes
NoNewPrivileges=true
PrivateDevices=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
MemoryMax=384M
TasksMax=64
"""


def render_camera_poweroff_service() -> str:
    return """[Unit]
Description=Consume EdgeWatch satellite request and schedule clean Linux poweroff
ConditionPathExists=/run/edgewatch-camera-satellite/poweroff.request

[Service]
Type=oneshot
ExecStart=/usr/bin/rm -f /run/edgewatch-camera-satellite/poweroff.request
ExecStart=/usr/bin/systemctl poweroff --no-wall
TimeoutStartSec=30
UMask=0077
NoNewPrivileges=true
PrivateDevices=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/run/edgewatch-camera-satellite
RestrictAddressFamilies=AF_UNIX
"""


def render_camera_poweroff_path() -> str:
    return """[Unit]
Description=Watch for a completed EdgeWatch satellite wake cycle

[Path]
PathExists=/run/edgewatch-camera-satellite/poweroff.request
Unit=edgewatch-camera-satellite-poweroff.service
MakeDirectory=true

[Install]
WantedBy=multi-user.target
"""


def render_camera_model_recovery_service(config: BootstrapConfig) -> str:
    runtime_env = config.camera_config_dir / "camera-satellite.env"
    return f"""[Unit]
Description=Recover interrupted EdgeWatch camera model activation
After=local-fs.target
Before=edgewatch-camera-satellite@check.service edgewatch-camera-satellite-wake@event.service edgewatch-camera-satellite-wake@daily.service
ConditionPathExists={runtime_env}
ConditionPathExists={config.model_root}

[Service]
Type=oneshot
User=root
Group=root
WorkingDirectory={config.current_symlink or config.repo_dir}
EnvironmentFile={runtime_env}
ExecStart={config.python_bin} {config.current_symlink or config.repo_dir}/scripts/apply_model_bundle.py --recover-only
TimeoutStartSec=60
UMask=0077
NoNewPrivileges=true
PrivateDevices=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths={config.model_root}
RestrictAddressFamilies=AF_UNIX
CapabilityBoundingSet=

[Install]
WantedBy=multi-user.target
"""


def _install_model_public_key(config: BootstrapConfig, runtime_values: dict[str, str]) -> Path:
    if config.model_public_key_file is None or config.model_public_key_id is None:
        raise ValueError("camera model trust configuration is incomplete")
    keyring = Path(runtime_values["EDGEWATCH_MODEL_KEYRING_DIR"])
    keyring.mkdir(parents=True, exist_ok=True)
    keyring.chmod(0o755)
    destination = keyring / f"{config.model_public_key_id}.pem"
    import_boot_file(
        config.model_public_key_file,
        destination,
        label="model public trust key",
        mode=0o644,
        maximum_bytes=64 * 1024,
        private_source=False,
    )
    try:
        public_key = destination.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise ValueError("model public trust key is not readable ASCII PEM") from exc
    if (
        "PRIVATE KEY" in public_key
        or public_key.count("-----BEGIN PUBLIC KEY-----") != 1
        or public_key.count("-----END PUBLIC KEY-----") != 1
    ):
        raise ValueError("model trust key must contain one PEM public key")
    run_required(
        ["openssl", "pkey", "-pubin", "-in", str(destination), "-noout"],
        "validate model public trust key",
    )
    return destination


def _make_model_tree_readable(releases_root: Path) -> None:
    if releases_root.is_symlink() or not releases_root.is_dir():
        raise RuntimeError("model releases root must be a real directory")
    for path in [releases_root, *releases_root.rglob("*")]:
        if path.is_symlink():
            raise RuntimeError("model releases must not contain symbolic links")
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            path.chmod(0o644)
        else:
            raise RuntimeError("model releases contain an unsupported filesystem entry")


def install_initial_model(config: BootstrapConfig, runtime_values: dict[str, str]) -> None:
    from agent.inference.bundle import ModelBundleManager

    releases_root = Path(runtime_values["EDGEWATCH_MODEL_RELEASES_ROOT"])
    current_symlink = Path(runtime_values["EDGEWATCH_MODEL_CURRENT_SYMLINK"])
    keyring_dir = Path(runtime_values["EDGEWATCH_MODEL_KEYRING_DIR"])
    manager = ModelBundleManager(
        releases_root=releases_root,
        current_symlink=current_symlink,
        keyring_dir=keyring_dir,
        hardware_model=runtime_values.get("EDGEWATCH_HARDWARE_MODEL", "raspberry-pi-zero-2"),
        litert_version=runtime_values.get("EDGEWATCH_MODEL_LITERT_VERSION", "2.1.6"),
    )
    source = config.initial_model_bundle_file
    if source is None:
        raise ValueError("camera-satellite bootstrap requires an initial signed model bundle")
    if source.exists() or source.is_symlink():
        _read_regular_boot_file(
            source,
            label="initial signed model bundle",
            maximum_bytes=512 * 1024 * 1024,
        )
        if stat.S_IMODE(source.lstat().st_mode) != 0o600:
            raise ValueError("initial signed model bundle source must have mode 0600")
        releases_root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".initial-model-",
            dir=releases_root.parent,
        ) as temporary_name:
            extracted = Path(temporary_name) / "bundle"
            extracted.mkdir(mode=0o700)
            _extract_bundle(source, extracted, 0)
            staged = manager.stage(extracted)
            manager.activate(staged.manifest.version)
    else:
        raise ValueError("initial signed model bundle source is missing")
    _make_model_tree_readable(releases_root)


def install_camera_runtime(config: BootstrapConfig, logger: logging.Logger) -> None:
    if config.camera_runtime_env_file is None or config.camera_credentials_file is None:
        raise ValueError("camera bootstrap inputs are incomplete")
    ensure_service_account("edgewatch-camera", state_dir=Path("/var/lib/edgewatch-camera-satellite"))
    config.camera_config_dir.mkdir(parents=True, exist_ok=True)
    config.camera_config_dir.chmod(0o750)
    _chgrp(config.camera_config_dir, "edgewatch-camera")
    runtime_destination = config.camera_config_dir / "camera-satellite.env"
    import_boot_file(
        config.camera_runtime_env_file,
        runtime_destination,
        label="camera runtime environment",
        mode=0o640,
    )
    _chgrp(runtime_destination, "edgewatch-camera")
    runtime_values = parse_strict_env_file(
        runtime_destination,
        label="camera runtime environment",
    )
    if runtime_values.get("EDGEWATCH_DEVICE_ID") != config.device_id:
        raise ValueError("camera runtime environment device ID does not match bootstrap identity")
    if any(
        key.startswith(("TELEGRAM_", "BOOTSTRAP_LTE_", "CELLULAR_"))
        or key in {"EDGEWATCH_API_URL", "EDGEWATCH_DEVICE_TOKEN"}
        for key in runtime_values
    ):
        raise ValueError("camera runtime environment contains forbidden cloud or cellular settings")

    camera_id = runtime_values.get("EDGEWATCH_CAMERA_ID", "cam1").strip().lower()
    media_url_setting = f"MEDIA_RTSP_{camera_id.upper()}_URL"
    credential_setting = f"MEDIA_RTSP_{camera_id.upper()}_CREDENTIALS_FILE"
    unknown_runtime_keys = sorted(
        set(runtime_values) - CAMERA_RUNTIME_ENV_KEYS - {media_url_setting, credential_setting}
    )
    if unknown_runtime_keys:
        raise ValueError(
            "camera runtime environment contains unsupported settings: " + ", ".join(unknown_runtime_keys)
        )
    credential_destination = Path(required_text(runtime_values, credential_setting))
    if credential_destination.parent != config.camera_config_dir:
        raise ValueError("camera credential destination must remain in the camera config directory")
    import_boot_file(
        config.camera_credentials_file,
        credential_destination,
        label="RTSP credentials",
        maximum_bytes=4096,
    )
    _chown(credential_destination, "edgewatch-camera")
    try:
        credentials = json.loads(credential_destination.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("RTSP credentials must contain valid UTF-8 JSON") from exc
    if not isinstance(credentials, dict) or set(credentials) != {"username", "password"}:
        raise ValueError("RTSP credentials must contain exactly username and password")
    if any(
        not isinstance(credentials[field], str)
        or not credentials[field]
        or len(credentials[field]) > 256
        or any(ord(character) < 32 for character in credentials[field])
        for field in ("username", "password")
    ):
        raise ValueError("RTSP credentials contain an invalid username or password")

    from agent.camera_satellite_runner import SatelliteConfig, SatelliteConfigError
    from agent.media.rtsp import FFmpegRtspBackend, RtspCameraConfig, RtspConfigurationError

    try:
        satellite = SatelliteConfig.from_env(runtime_values)
        if satellite.poweroff_request_path != Path("/run/edgewatch-camera-satellite/poweroff.request"):
            raise SatelliteConfigError(
                "camera poweroff request path must match the installed systemd path unit"
            )
        FFmpegRtspBackend(
            {
                satellite.camera_id: RtspCameraConfig(
                    endpoint=satellite.rtsp_endpoint,
                    credentials_path=satellite.rtsp_credentials_path,
                    require_audio=True,
                )
            }
        )
    except (SatelliteConfigError, RtspConfigurationError) as exc:
        raise ValueError("camera runtime environment is invalid") from exc
    _install_model_public_key(config, runtime_values)
    install_initial_model(config, runtime_values)
    validate_ota_gateway_cache_url(required_text(config.extra_agent_env, "EDGEWATCH_OTA_GATEWAY_CACHE_URL"))
    camera_ota_env = dict(config.extra_agent_env)
    camera_ota_env.update(
        {
            "EDGEWATCH_ASSETS_ROOT": "/opt/edgewatch/assets",
            "EDGEWATCH_ASSET_BUNDLE_APPLY_CMD": CAMERA_ASSET_APPLY_CMD,
            "EDGEWATCH_ENABLE_OTA_APPLY": config.enable_ota_apply,
            "EDGEWATCH_POWER_STATE_PATH": CAMERA_OTA_POWER_STATE_PATH,
        }
    )
    write_text_if_changed(
        config.agent_env_path,
        render_agent_env(replace(config, extra_agent_env=camera_ota_env)),
        mode=0o600,
    )

    write_text_if_changed(
        config.camera_service_path,
        render_camera_check_service(config),
        mode=0o644,
    )
    write_text_if_changed(
        config.camera_wake_service_path,
        render_camera_wake_service(config),
        mode=0o644,
    )
    write_text_if_changed(
        config.camera_poweroff_service_path,
        render_camera_poweroff_service(),
        mode=0o644,
    )
    write_text_if_changed(
        config.camera_poweroff_path,
        render_camera_poweroff_path(),
        mode=0o644,
    )
    write_text_if_changed(
        config.camera_model_recovery_service_path,
        render_camera_model_recovery_service(config),
        mode=0o644,
    )
    run_required(["systemctl", "daemon-reload"], "reload camera-satellite systemd units")
    run_required(
        ["systemctl", "enable", "--now", CAMERA_MODEL_RECOVERY_SERVICE_NAME],
        "recover interrupted camera model activation",
    )
    run_required(
        ["systemctl", "enable", "--now", config.camera_poweroff_path.name],
        "enable camera-satellite clean-poweroff request watcher",
    )
    logger.info("installed camera-satellite check, wake, and clean-poweroff services")


def write_telegram_token_file(config: BootstrapConfig) -> None:
    if config.telemetry_transport != "telegram" or not config.telegram_bot_token_file:
        return
    if config.bootstrap_telegram_bot_token_file:
        source_path = config.bootstrap_telegram_bot_token_file
        if source_path.is_file():
            token = source_path.read_text().strip()
            if not token:
                raise ValueError(f"bootstrap Telegram token file is empty: {source_path}")
            write_text_if_changed(config.telegram_bot_token_file, f"{token}\n", mode=0o600)
        elif not config.telegram_bot_token_file.is_file():
            raise FileNotFoundError(f"bootstrap Telegram token file not found: {source_path}")
    elif config.telegram_bot_token:
        write_text_if_changed(config.telegram_bot_token_file, f"{config.telegram_bot_token}\n", mode=0o600)
    elif not config.telegram_bot_token_file.is_file():
        raise FileNotFoundError(f"Telegram bot token file not found: {config.telegram_bot_token_file}")
    config.telegram_bot_token_file.chmod(0o600)


def _read_ssh_public_key(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"bootstrap SSH public key file not found: {path}")
    return _validate_ssh_public_key_text(path.read_text(encoding="utf-8").strip())


def _validate_ssh_public_key_text(key: str) -> str:
    if "\n" in key or "\r" in key:
        raise ValueError("bootstrap SSH public key file must contain exactly one key")
    parts = key.split()
    allowed_type = bool(parts) and (
        parts[0] in {"ssh-ed25519", "ssh-rsa"} or parts[0].startswith("ecdsa-sha2-")
    )
    if len(parts) < 2 or not allowed_type:
        raise ValueError("bootstrap SSH public key must be an OpenSSH public key")
    try:
        decoded_key = base64.b64decode(parts[1], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("bootstrap SSH public key payload is invalid") from exc
    _validate_ssh_key_blob(parts[0], decoded_key)
    return key


def _ssh_blob_field(blob: bytes, offset: int) -> tuple[bytes, int]:
    if offset + 4 > len(blob):
        raise ValueError("bootstrap SSH public key payload is truncated")
    length = int.from_bytes(blob[offset : offset + 4], "big")
    start = offset + 4
    end = start + length
    if length <= 0 or end > len(blob):
        raise ValueError("bootstrap SSH public key field is invalid")
    return blob[start:end], end


def _validate_ssh_key_blob(key_type: str, blob: bytes) -> None:
    encoded_type, offset = _ssh_blob_field(blob, 0)
    try:
        embedded_type = encoded_type.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("bootstrap SSH key type is invalid") from exc
    if embedded_type != key_type:
        raise ValueError("bootstrap SSH key type does not match its payload")

    if key_type == "ssh-ed25519":
        key_material, offset = _ssh_blob_field(blob, offset)
        if len(key_material) != 32:
            raise ValueError("bootstrap Ed25519 public key length is invalid")
    elif key_type == "ssh-rsa":
        _exponent, offset = _ssh_blob_field(blob, offset)
        _modulus, offset = _ssh_blob_field(blob, offset)
    else:
        curve, offset = _ssh_blob_field(blob, offset)
        _point, offset = _ssh_blob_field(blob, offset)
        expected_curve = key_type.removeprefix("ecdsa-sha2-").encode("ascii")
        if curve != expected_curve:
            raise ValueError("bootstrap ECDSA curve does not match its key type")

    if offset != len(blob):
        raise ValueError("bootstrap SSH public key payload has trailing data")


def _ssh_key_identity(key: str) -> tuple[str, str]:
    parts = key.split()
    return parts[0], parts[1]


def _control_forced_command(config: BootstrapConfig) -> str:
    helper = config.repo_dir / DEFAULT_DEVICE_CONTROL_ENTRYPOINT
    argv = [
        "/usr/bin/sudo",
        "-n",
        "--",
        str(config.python_bin),
        str(helper),
        "--device-id",
        config.device_id,
        "--runtime-profile",
        config.profile,
        "--ssh-stdin",
    ]
    return " ".join(shlex.quote(value) for value in argv)


def _control_authorized_key_prefix(config: BootstrapConfig) -> str:
    command = _control_forced_command(config).replace("\\", "\\\\").replace('"', '\\"')
    return f'restrict,command="{command}" '


def _existing_managed_ssh_keys(
    authorized_keys: Path, config: BootstrapConfig
) -> tuple[str | None, str | None]:
    if not authorized_keys.is_file():
        return None, None
    prefix = _control_authorized_key_prefix(config)
    operator_key: str | None = None
    control_key: str | None = None
    for line in authorized_keys.read_text(encoding="utf-8").splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        if candidate.startswith(prefix):
            control_key = _validate_ssh_public_key_text(candidate.removeprefix(prefix))
        elif not candidate.startswith(("restrict,", "command=")):
            operator_key = _validate_ssh_public_key_text(candidate)
    return operator_key, control_key


def write_ssh_authorized_key(config: BootstrapConfig) -> None:
    if not config.ssh_authorized_key_file and not config.control_ssh_authorized_key_file:
        return
    try:
        account = pwd.getpwnam(config.ssh_user)
    except KeyError as exc:
        raise ValueError(f"bootstrap SSH user does not exist: {config.ssh_user}") from exc
    ssh_dir = Path(account.pw_dir) / ".ssh"
    ssh_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    ssh_dir.chmod(0o700)
    authorized_keys = ssh_dir / "authorized_keys"
    existing_operator, existing_control = _existing_managed_ssh_keys(authorized_keys, config)

    operator_key = existing_operator
    if config.ssh_authorized_key_file:
        if config.ssh_authorized_key_file.is_file():
            operator_key = _read_ssh_public_key(config.ssh_authorized_key_file)
        elif operator_key is None:
            raise FileNotFoundError(
                f"bootstrap SSH public key file not found: {config.ssh_authorized_key_file}"
            )

    control_key = existing_control
    if config.control_ssh_authorized_key_file:
        if config.control_ssh_authorized_key_file.is_file():
            control_key = _read_ssh_public_key(config.control_ssh_authorized_key_file)
        elif control_key is None:
            raise FileNotFoundError(
                "bootstrap controller SSH public key file not found: "
                f"{config.control_ssh_authorized_key_file}"
            )

    if operator_key and control_key and _ssh_key_identity(operator_key) == _ssh_key_identity(control_key):
        raise ValueError("controller and operator SSH public keys must use different key material")

    lines: list[str] = []
    if operator_key:
        lines.append(operator_key)
    if control_key:
        helper = config.repo_dir / DEFAULT_DEVICE_CONTROL_ENTRYPOINT
        if not helper.is_file():
            raise FileNotFoundError(f"typed device-control helper not found: {helper}")
        lines.append(f"{_control_authorized_key_prefix(config)}{control_key}")
    if not lines:
        raise ValueError("at least one SSH public key must be installed")
    write_text_if_changed(authorized_keys, "\n".join(lines) + "\n", mode=0o600)
    os.chown(ssh_dir, account.pw_uid, account.pw_gid)
    os.chown(authorized_keys, account.pw_uid, account.pw_gid)
    hardening = (
        "# Managed by EdgeWatch first-boot provisioning.\n"
        "PubkeyAuthentication yes\n"
        "AuthenticationMethods publickey\n"
        "PasswordAuthentication no\n"
        "KbdInteractiveAuthentication no\n"
        "PermitEmptyPasswords no\n"
        "PermitRootLogin no\n"
    )
    write_text_if_changed(DEFAULT_SSH_HARDENING_PATH, hardening, mode=0o644)
    run_required(["systemctl", "reload-or-restart", "ssh"], "apply SSH server hardening")


def install_ota_public_key(config: BootstrapConfig) -> None:
    if not config.ota_public_key_file or not config.ota_public_key_id:
        return
    keyring_dir = Path(
        config.extra_agent_env.get("EDGEWATCH_OTA_KEYRING_DIR", "/opt/edgewatch/keys")
    ).expanduser()
    keyring_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
    keyring_dir.chmod(0o755)
    destination = keyring_dir / f"{config.ota_public_key_id}.pem"
    if config.ota_public_key_file.is_file():
        try:
            public_key = config.ota_public_key_file.read_text(encoding="ascii")
        except (OSError, UnicodeError) as exc:
            raise ValueError("bootstrap OTA public key is not readable ASCII PEM") from exc
        if "PRIVATE KEY" in public_key or len(public_key.encode("ascii")) > 64 * 1024:
            raise ValueError("bootstrap OTA key must contain only a bounded public key")
        if (
            public_key.count("-----BEGIN PUBLIC KEY-----") != 1
            or public_key.count("-----END PUBLIC KEY-----") != 1
        ):
            raise ValueError("bootstrap OTA key must use PEM PUBLIC KEY format")
        write_text_if_changed(destination, public_key.rstrip() + "\n", mode=0o644)
    elif not destination.is_file():
        raise FileNotFoundError(f"bootstrap OTA public key file not found: {config.ota_public_key_file}")
    run_required(
        ["openssl", "pkey", "-pubin", "-in", str(destination), "-noout"],
        "validate OTA release public key",
    )


def verify_ssh_access(config: BootstrapConfig) -> None:
    if not config.ssh_authorized_key_file and not config.control_ssh_authorized_key_file:
        return
    run_required(["sshd", "-t"], "validate SSH server configuration")
    output = run_capture_required(
        [
            "sshd",
            "-T",
            "-C",
            f"user={config.ssh_user},host=localhost,addr=127.0.0.1",
        ],
        "inspect effective SSH configuration",
    )
    effective = {
        parts[0].lower(): " ".join(parts[1:]).lower()
        for line in output.splitlines()
        if (parts := line.split())
    }
    expected = {
        "authenticationmethods": "publickey",
        "kbdinteractiveauthentication": "no",
        "passwordauthentication": "no",
        "permitrootlogin": "no",
        "pubkeyauthentication": "yes",
    }
    mismatched = [key for key, value in expected.items() if effective.get(key) != value]
    if mismatched:
        raise RuntimeError("effective SSH configuration is not public-key-only: " + ", ".join(mismatched))
    run_required(["systemctl", "is-active", "--quiet", "ssh"], "verify SSH service health")


def verify_cellular_data_path(config: BootstrapConfig) -> None:
    if not config.lte_apn:
        return
    interface_name = config.extra_agent_env.get("CELLULAR_INTERFACE", "wwan0").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,32}", interface_name):
        raise ValueError("CELLULAR_INTERFACE is invalid for the LTE health probe")
    raw_url = config.extra_agent_env.get(
        "CELLULAR_WATCHDOG_HTTP_URL",
        "https://www.gstatic.com/generate_204",
    )
    parsed = urllib.parse.urlparse(raw_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("cellular health URL must be an HTTPS URL")
    host = parsed.hostname
    port = parsed.port or 443
    target = parsed.path or "/"
    if parsed.query:
        target += f"?{parsed.query}"

    last_error: Exception | None = None
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses.sort(key=lambda item: 0 if item[0] == socket.AF_INET else 1)
    for family, socktype, proto, _canonical_name, address in addresses:
        raw_socket = socket.socket(family, socktype, proto)
        try:
            raw_socket.settimeout(20.0)
            raw_socket.setsockopt(
                socket.SOL_SOCKET,
                getattr(socket, "SO_BINDTODEVICE", 25),
                interface_name.encode("utf-8") + b"\0",
            )
            raw_socket.connect(address)
            context = ssl.create_default_context()
            with context.wrap_socket(raw_socket, server_hostname=host) as tls_socket:
                request = (
                    f"GET {target} HTTP/1.1\r\n"
                    f"Host: {host}\r\n"
                    "Connection: close\r\n"
                    "User-Agent: edgewatch-bootstrap/1\r\n\r\n"
                ).encode("ascii")
                tls_socket.sendall(request)
                with tls_socket.makefile("rb") as response_file:
                    status_line = response_file.readline(4096).decode("ascii", errors="replace")
            parts = status_line.split()
            if len(parts) >= 2 and parts[0].startswith("HTTP/"):
                status = int(parts[1])
                if 200 <= status < 400:
                    return
                raise RuntimeError(f"cellular HTTPS probe returned status {status}")
            raise RuntimeError("cellular HTTPS probe returned an invalid response")
        except Exception as exc:
            last_error = exc
            try:
                raw_socket.close()
            except OSError:
                pass
    raise RuntimeError(f"cellular HTTPS data-path probe failed on interface {interface_name}") from last_error


def verify_telegram_delivery(config: BootstrapConfig) -> None:
    """Prove that the configured bot can post to the configured destination."""

    if (
        config.telemetry_transport != "telegram"
        or not config.telegram_bot_token_file
        or not config.telegram_chat_id
    ):
        return
    try:
        token = config.telegram_bot_token_file.read_text(encoding="utf-8").strip()
        body = urllib.parse.urlencode(
            {
                "chat_id": config.telegram_chat_id,
                "text": f"EdgeWatch {config.device_id} provisioning verified",
                "disable_notification": "true",
                "protect_content": "true",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
            status = int(getattr(response, "status", 200))
        if not 200 <= status < 300 or not isinstance(payload, dict) or payload.get("ok") is not True:
            raise RuntimeError("Telegram rejected the provisioning receipt")
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError("Telegram provisioning delivery check failed") from None


def _agent_readiness_snapshot(config: BootstrapConfig) -> tuple[int, str]:
    run_required(
        ["systemctl", "is-active", "--quiet", DEFAULT_AGENT_SERVICE_NAME],
        "verify edgewatch-agent health",
    )
    ready_path = _agent_ready_path(config)
    try:
        payload = json.loads(ready_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"agent readiness receipt is unavailable: {ready_path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("agent readiness receipt must be a JSON object")
    raw_pid = payload.get("pid")
    if isinstance(raw_pid, bool) or not isinstance(raw_pid, (int, str)):
        raise RuntimeError("agent readiness receipt has an invalid pid")
    try:
        pid = int(raw_pid)
    except ValueError as exc:
        raise RuntimeError("agent readiness receipt has an invalid pid") from exc
    session_id = str(payload.get("process_session_id") or "").strip()
    if (
        pid <= 0
        or not session_id
        or payload.get("device_id") != config.device_id
        or payload.get("transport") != config.telemetry_transport
    ):
        raise RuntimeError("agent readiness receipt does not match this provisioned device")
    raw_main_pid = run_capture_required(
        ["systemctl", "show", "--property=MainPID", "--value", DEFAULT_AGENT_SERVICE_NAME],
        "inspect edgewatch-agent main pid",
    )
    try:
        main_pid = int(raw_main_pid)
    except ValueError as exc:
        raise RuntimeError("systemd returned an invalid edgewatch-agent main pid") from exc
    if main_pid <= 0 or main_pid != pid:
        raise RuntimeError("agent readiness receipt belongs to a stale process")
    return pid, session_id


def verify_agent_readiness(
    config: BootstrapConfig,
    *,
    timeout_s: float = DEFAULT_AGENT_READY_TIMEOUT_S,
    stability_s: float = DEFAULT_AGENT_STABILITY_S,
    poll_s: float = 0.5,
) -> None:
    deadline = time.monotonic() + max(0.0, timeout_s)
    last_error: Exception | None = None
    while True:
        try:
            initial = _agent_readiness_snapshot(config)
            break
        except RuntimeError as exc:
            last_error = exc
            if time.monotonic() >= deadline:
                raise RuntimeError("edgewatch-agent did not become ready before the timeout") from last_error
            time.sleep(max(0.01, poll_s))

    if stability_s > 0:
        time.sleep(stability_s)
    stable = _agent_readiness_snapshot(config)
    if stable != initial:
        raise RuntimeError("edgewatch-agent restarted during the readiness stability window")


def verify_gateway_runtime(config: BootstrapConfig) -> None:
    for service in ("mosquitto", "redis-server", "chirpstack", RADIO_SERVICE_NAME, GATEWAY_SERVICE_NAME):
        run_required(
            ["systemctl", "is-active", "--quiet", service],
            f"verify {service} health",
        )
    run_required(
        [
            str(config.python_bin),
            "-m",
            "agent.lorawan.radio_cli",
            "check",
            "--config",
            str(config.gateway_config_dir / "lorawan-radio-ingress.yaml"),
        ],
        "verify concentrator detection and ChirpStack gateway-bridge connectivity",
    )


def verify_camera_runtime(config: BootstrapConfig) -> None:
    run_required(
        ["systemctl", "start", CAMERA_CHECK_SERVICE_NAME],
        "run camera-satellite signed-model and RTSP readiness check",
    )
    result = run_capture_required(
        ["systemctl", "show", "--property=Result", "--value", CAMERA_CHECK_SERVICE_NAME],
        "inspect camera-satellite check result",
    ).strip()
    if result != "success":
        raise RuntimeError("camera-satellite check service did not complete successfully")
    runtime_env = parse_env_file(config.camera_config_dir / "camera-satellite.env")
    ready_path = Path(required_text(runtime_env, "EDGEWATCH_SATELLITE_READY_PATH"))
    try:
        metadata = ready_path.stat()
        payload = json.loads(ready_path.read_text(encoding="utf-8"))
        camera_uid = pwd.getpwnam(CAMERA_RUNTIME_USER).pw_uid
    except (KeyError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("camera-satellite readiness receipt is unavailable") from exc
    if (
        ready_path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != camera_uid
        or not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("status") != "ready"
        or payload.get("device_id") != config.device_id
        or payload.get("known_answers_valid") is not True
        or payload.get("preprocessing_valid") is not True
        or payload.get("local_media_only") is not True
        or payload.get("application_target") != str((config.current_symlink or config.repo_dir).resolve())
        or payload.get("video_codec") != "h264"
        or payload.get("audio_codec") not in {"aac", "pcm_alaw", "pcm_mulaw"}
    ):
        raise RuntimeError("camera-satellite readiness receipt is invalid")
    try:
        valid_until = datetime.fromisoformat(str(payload["valid_until"]).replace("Z", "+00:00"))
    except (KeyError, ValueError) as exc:
        raise RuntimeError("camera-satellite readiness expiry is invalid") from exc
    if valid_until.tzinfo is None or valid_until.astimezone(UTC) <= datetime.now(UTC):
        raise RuntimeError("camera-satellite readiness receipt has expired")


def verify_runtime_health(config: BootstrapConfig) -> None:
    if config.profile == "camera-satellite":
        verify_camera_runtime(config)
        verify_ssh_access(config)
        return
    verify_agent_readiness(config)
    if config.lte_apn:
        run_required(
            ["nmcli", "connection", "show", "--active", "id", config.lte_connection_name],
            "verify active LTE connection",
        )
        verify_cellular_data_path(config)
    verify_ssh_access(config)
    verify_telegram_delivery(config)
    if config.profile == "gateway":
        verify_gateway_runtime(config)


def run_tailscale(config: BootstrapConfig, logger: logging.Logger) -> None:
    if not config.tailscale_required:
        logger.info("tailscale auth key not provided; skipping tailnet enrollment")
        return
    if shutil_which("tailscale") is None:
        raise RuntimeError("Tailscale was requested but the tailscale command is not installed")
    run_required(["systemctl", "enable", "--now", "tailscaled"], "enable tailscaled")
    if config.tailscale_auth_key:
        secret_path = write_tailscale_secret_file(config)
        try:
            auth_cmd = (
                f'tailscale up --auth-key="$(cat {shlex.quote(str(secret_path))})" '
                f"--hostname={shlex.quote(config.tailscale_hostname or config.device_id)}"
            )
            run_required(["bash", "-lc", auth_cmd], "join Tailscale tailnet")
        finally:
            _unlink_durable(secret_path)
    if config.tailscale_enable_ssh:
        run_required(["tailscale", "set", "--ssh"], "enable Tailscale SSH")

    raw_ip = run_capture_required(["tailscale", "ip", "-4"], "verify Tailscale enrollment")
    try:
        addresses = [ipaddress.ip_address(line.strip()) for line in raw_ip.splitlines() if line.strip()]
    except ValueError as exc:
        raise RuntimeError("Tailscale enrollment returned an invalid device address") from exc
    tailnet = ipaddress.ip_network("100.64.0.0/10")
    if not any(address.version == 4 and address in tailnet for address in addresses):
        raise RuntimeError("Tailscale enrollment did not assign a tailnet IPv4 address")


def write_firstboot_state(config: BootstrapConfig, logger: logging.Logger, *, warnings: list[str]) -> None:
    config.firstboot_report.parent.mkdir(parents=True, exist_ok=True)
    hardware_boundaries: list[str] = []
    if config.profile == "gateway":
        hardware_boundaries = [
            "The pinned SX1302/SX1303 ingress adapter is installed separately and must prove radio and ChirpStack readiness.",
            "Electrical LTE cutoff remains a carrier-qualified external load-switch integration.",
        ]
    elif config.profile == "camera-satellite":
        hardware_boundaries = [
            "MCU power-latch firmware and a board-qualified HALT_ACK signal remain external pilot work.",
            "Wio-E5 LoRaWAN radio firmware and OTAA programming remain external pilot work.",
        ]
    payload: dict[str, Any] = {
        "device_id": config.device_id,
        "profile": config.profile,
        "image_profile_path": str(config.image_profile_path),
        "telemetry_transport": config.telemetry_transport,
        "repo_dir": str(config.repo_dir),
        "agent_env_path": str(config.agent_env_path),
        "agent_service_path": (
            str(config.agent_service_path) if config.profile != "camera-satellite" else None
        ),
        "bundle_installed": bool(config.bundle_uri),
        "lte_profile": config.lte_connection_name if config.lte_apn else None,
        "tailscale_requested": config.tailscale_required,
        "ssh_user": (
            config.ssh_user
            if config.ssh_authorized_key_file or config.control_ssh_authorized_key_file
            else None
        ),
        "typed_controller_key_installed": bool(config.control_ssh_authorized_key_file),
        "ota_public_key_id": config.ota_public_key_id,
        "gateway_config_dir": (str(config.gateway_config_dir) if config.profile == "gateway" else None),
        "camera_runtime_env_path": (
            str(config.camera_config_dir / "camera-satellite.env")
            if config.profile == "camera-satellite"
            else None
        ),
        "hardware_boundaries": hardware_boundaries,
        "warnings": warnings,
    }
    write_text_if_changed(
        config.firstboot_report, json.dumps(payload, indent=2, sort_keys=True) + "\n", mode=0o600
    )
    write_text_if_changed(config.firstboot_marker, "complete\n", mode=0o600)
    logger.info("wrote first-boot state: %s", config.firstboot_report)


def _consume_boot_inputs(config: BootstrapConfig) -> None:
    sources: list[Path | None] = [
        config.bootstrap_telegram_bot_token_file,
        config.ssh_authorized_key_file,
        config.control_ssh_authorized_key_file,
        config.ota_public_key_file,
    ]
    if config.profile == "gateway":
        sources.extend(
            [
                config.lorawan_gateway_config_file,
                config.lorawan_registry_file,
                config.lorawan_radio_ingress_file,
                config.lorawan_vendor_config_file,
                config.gateway_power_env_file,
            ]
        )
    elif config.profile == "camera-satellite":
        sources.extend(
            [
                config.camera_runtime_env_file,
                config.camera_credentials_file,
                config.model_public_key_file,
                config.initial_model_bundle_file,
            ]
        )
    unique_sources = {source for source in sources if source is not None}
    for source in sorted(unique_sources, key=os.fspath):
        _unlink_durable(source)


def bootstrap(
    config: BootstrapConfig,
    logger: logging.Logger,
    *,
    boot_config_path: Path | None = None,
) -> list[str]:
    warnings: list[str] = []
    activation: BundleActivation | None = None
    verify_image_profile(config)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    if not config.repo_dir.exists():
        if not config.bundle_uri:
            raise FileNotFoundError(f"repo directory not found: {config.repo_dir}")

    try:
        activation = install_bundle(config, logger, retain_previous=True)
        write_telegram_token_file(config)
        write_ssh_authorized_key(config)
        install_ota_public_key(config)
        configure_hostname(config)
        ensure_current_release_symlink(config)
        if config.profile == "camera-satellite":
            install_camera_runtime(config, logger)
        else:
            install_agent_service(config, logger)
            if config.profile == "gateway":
                install_gateway_runtime(config, logger)

        if config.lte_apn:
            write_lte_profile(config, logger)

        if config.tailscale_required:
            run_tailscale(config, logger)

        verify_runtime_health(config)
        _consume_boot_inputs(config)
        if boot_config_path is not None:
            redact_consumed_secrets(boot_config_path)
    except Exception as original_error:
        if activation is not None:
            try:
                _rollback_bundle_activation(activation, logger)
                if config.profile != "camera-satellite":
                    _restart_restored_agent(activation)
            except Exception as rollback_error:
                raise RuntimeError(
                    f"bootstrap failed and the previous agent could not be restored: {rollback_error}"
                ) from original_error
        raise

    if activation is not None:
        _commit_bundle_activation(activation, logger)
    # The marker is deliberately last. A crash during credential consumption,
    # config redaction, or deployment health checks must remain retryable.
    write_firstboot_state(config, logger, warnings=warnings)
    return warnings


def redact_consumed_secrets(path: Path) -> None:
    lines: list[str] = []
    for raw_line in path.read_text().splitlines():
        stripped = raw_line.strip()
        candidate = stripped.removeprefix("export ").lstrip()
        key = candidate.split("=", 1)[0] if "=" in candidate else ""
        if key == "BOOTSTRAP_TAILSCALE_AUTH_KEY":
            lines.append("BOOTSTRAP_TAILSCALE_ENROLLED=true")
        elif key in CONSUMED_BOOTSTRAP_SECRET_KEYS:
            lines.append(f"# {key} consumed and removed by EdgeWatch bootstrap")
        else:
            lines.append(raw_line)
    write_text_if_changed(path, "\n".join(lines) + "\n", mode=0o600)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EdgeWatch Raspberry Pi first-boot bootstrap")
    parser.add_argument("--config", help="path to bootstrap env file")
    parser.add_argument("--dry-run", action="store_true", help="print the derived config and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger("edgewatch.rpi_bootstrap")

    if sys.platform != "linux":
        logger.warning("this bootstrap is intended for Linux / Raspberry Pi OS")

    config_path = resolve_boot_config_path(args.config)
    raw = parse_env_file(config_path)
    config = build_config(raw)
    verify_image_profile(config)

    if args.dry_run:
        print(f"profile={config.profile}")
        if config.profile == "camera-satellite":
            print("\n--- camera check systemd ---\n")
            print(render_camera_check_service(config))
            print("\n--- camera wake systemd ---\n")
            print(render_camera_wake_service(config))
            print("\n--- camera model recovery systemd ---\n")
            print(render_camera_model_recovery_service(config))
            print("\n--- camera poweroff path ---\n")
            print(render_camera_poweroff_path())
        else:
            print(render_agent_env(config, redact_secrets=True))
            print("\n--- agent systemd ---\n")
            print(render_agent_service(config))
            if config.profile == "gateway":
                print("\n--- LoRaWAN radio systemd ---\n")
                print(render_gateway_radio_service(config))
                print("\n--- LoRaWAN gateway systemd ---\n")
                print(render_gateway_service(config))
            if config.lte_apn:
                print("\n--- lte ---\n")
                print(render_lte_connection(config, redact_secrets=True))
        return 0

    if os.geteuid() != 0:
        raise SystemExit("edgewatch bootstrap must run as root")

    warnings = bootstrap(config, logger, boot_config_path=config_path)
    if warnings:
        logger.info("bootstrap completed with warnings")
    else:
        logger.info("bootstrap completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
