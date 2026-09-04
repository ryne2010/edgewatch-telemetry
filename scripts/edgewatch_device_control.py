#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import MutableMapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.local_control import (  # noqa: E402
    MAX_ENVELOPE_BYTES,
    AppliedCommandLedger,
    LocalControlError,
    LocalControlExecutor,
    LocalControlState,
    error_response,
    parse_envelope,
)


_RUNTIME_ENV_FILES = {
    "standalone": (Path("/etc/edgewatch/agent.env"),),
    "gateway": (Path("/etc/edgewatch/agent.env"),),
    "camera-satellite": (
        Path("/etc/edgewatch/agent.env"),
        Path("/etc/edgewatch/camera-satellite.env"),
    ),
}
_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_CONTROL_ENV_ALLOWLIST = frozenset(
    {
        "BUFFER_DB_PATH",
        "EDGEWATCH_AGENT_RUNTIME_SCHEMA",
        "EDGEWATCH_AGENT_SYSTEMD_SERVICE",
        "EDGEWATCH_AGENT_VERSION",
        "EDGEWATCH_ALLOW_LOCAL_CONTROL_SHUTDOWN",
        "EDGEWATCH_ASSETS_ROOT",
        "EDGEWATCH_ASSET_BUNDLE_APPLY_CMD",
        "EDGEWATCH_CURRENT_SYMLINK",
        "EDGEWATCH_ENABLE_OTA_APPLY",
        "EDGEWATCH_HARDWARE_MODEL",
        "EDGEWATCH_LOCAL_CONTROL_LEDGER_PATH",
        "EDGEWATCH_LOCAL_CONTROL_STATE_PATH",
        "EDGEWATCH_LOCAL_OTA_STATE_PATH",
        "EDGEWATCH_MODEL_CURRENT_SYMLINK",
        "EDGEWATCH_MODEL_KEYRING_DIR",
        "EDGEWATCH_MODEL_LITERT_VERSION",
        "EDGEWATCH_MODEL_RELEASES_ROOT",
        "EDGEWATCH_OTA_CACHE_DIR",
        "EDGEWATCH_OTA_GATEWAY_CACHE_URL",
        "EDGEWATCH_OTA_KEYRING_DIR",
        "EDGEWATCH_OTA_MAX_ARTIFACT_BYTES",
        "EDGEWATCH_OTA_POWER_EVIDENCE_MAX_AGE_S",
        "EDGEWATCH_OTA_READY_POLL_S",
        "EDGEWATCH_OTA_READY_STABILITY_S",
        "EDGEWATCH_OTA_READY_TIMEOUT_S",
        "EDGEWATCH_OTA_RELEASE_CATALOG",
        "EDGEWATCH_OTA_RUNTIME_PROFILE",
        "EDGEWATCH_POWER_INPUT_OUT_OF_RANGE",
        "EDGEWATCH_POWER_STATE_PATH",
        "EDGEWATCH_POWER_UNSUSTAINABLE",
        "EDGEWATCH_READY_PATH",
        "EDGEWATCH_RELEASES_ROOT",
        "EDGEWATCH_RELEASE_CHANNEL",
        "EDGEWATCH_RUNTIME_DEPENDENCY_PATH",
        "EDGEWATCH_SYSTEM_IMAGE_APPLY_CMD",
        "EDGEWATCH_SYSTEM_IMAGE_HARDWARE_QUALIFIED",
        "EDGEWATCH_SYSTEM_IMAGE_STAGE_CMD",
        "EDGEWATCH_TELEMETRY_TRANSPORT",
        "RUNTIME_POWER_MODE",
    }
)
_OTA_POWER_COMMANDS = frozenset({"ota_stage", "ota_canary", "ota_promote"})
_CAMERA_ASSET_APPLY_CMD = (
    "/opt/edgewatch/app/.venv/bin/python /opt/edgewatch/current/scripts/apply_model_bundle.py"
)
_CAMERA_OTA_POWER_STATE_PATH = "/var/lib/edgewatch-camera-satellite/ota-power-state.json"
_CAMERA_CURRENT_SYMLINK = "/opt/edgewatch/current"
_CAMERA_RELEASES_ROOT = "/opt/edgewatch/releases"


def _parse_environment_file(path: Path, *, expected_owner_uid: int = 0) -> dict[str, str]:
    """Read a fixed root-owned systemd-style environment file without expansion."""

    try:
        metadata = path.lstat()
        payload = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise LocalControlError("local_configuration", "runtime environment is unavailable") from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != expected_owner_uid
        or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or metadata.st_size > 256 * 1024
    ):
        raise LocalControlError("local_configuration", "runtime environment is not trusted")
    values: dict[str, str] = {}
    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise LocalControlError("local_configuration", "runtime environment is malformed")
        name, raw_value = line.split("=", 1)
        if _ENV_NAME.fullmatch(name) is None or name in values:
            raise LocalControlError("local_configuration", "runtime environment is malformed")
        try:
            parsed = shlex.split(raw_value, comments=False, posix=True)
        except ValueError as exc:
            raise LocalControlError("local_configuration", "runtime environment is malformed") from exc
        if len(parsed) > 1:
            raise LocalControlError("local_configuration", "runtime environment is malformed")
        values[name] = parsed[0] if parsed else ""
    return values


def _load_runtime_environment(
    profile: str,
    *,
    files_by_profile: dict[str, tuple[Path, ...]] | None = None,
    expected_owner_uid: int = 0,
    environment: MutableMapping[str, str] | None = None,
) -> None:
    paths = (files_by_profile or _RUNTIME_ENV_FILES)[profile]
    selected: dict[str, str] = {}
    for path in paths:
        parsed = _parse_environment_file(path, expected_owner_uid=expected_owner_uid)
        selected.update({key: value for key, value in parsed.items() if key in _CONTROL_ENV_ALLOWLIST})
    if profile == "camera-satellite":
        if selected.get("EDGEWATCH_OTA_RUNTIME_PROFILE") != profile:
            raise LocalControlError("local_configuration", "camera OTA runtime profile is not installed")
        if (
            selected.get("EDGEWATCH_CURRENT_SYMLINK") != _CAMERA_CURRENT_SYMLINK
            or selected.get("EDGEWATCH_RELEASES_ROOT") != _CAMERA_RELEASES_ROOT
        ):
            raise LocalControlError(
                "local_configuration", "camera application release paths are not installed"
            )
        if selected.get("EDGEWATCH_ASSET_BUNDLE_APPLY_CMD") != _CAMERA_ASSET_APPLY_CMD:
            raise LocalControlError("local_configuration", "camera model activation hook is not installed")
        if selected.get("EDGEWATCH_POWER_STATE_PATH") != _CAMERA_OTA_POWER_STATE_PATH:
            raise LocalControlError("local_configuration", "camera OTA power evidence path is not installed")
        selected["EDGEWATCH_ASSET_BUNDLE_APPLY_CMD"] = _CAMERA_ASSET_APPLY_CMD
    target_environment = os.environ if environment is None else environment
    target_environment.clear()
    target_environment.update(
        {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        }
    )
    target_environment.update(selected)


def _refresh_camera_power_evidence(*, run_command: object = subprocess.run) -> None:
    """Publish fresh Pi evidence only after the firmware reports no throttling flags."""

    raw_path = (os.getenv("EDGEWATCH_POWER_STATE_PATH") or "").strip()
    if not raw_path:
        raise LocalControlError("power_unavailable", "camera OTA power evidence is unavailable")
    destination = Path(raw_path)
    if not destination.is_absolute() or ".." in destination.parts:
        raise LocalControlError("local_configuration", "camera OTA power path is invalid")
    try:
        completed = run_command(  # type: ignore[operator]
            ["vcgencmd", "get_throttled"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        destination.unlink(missing_ok=True)
        raise LocalControlError("power_unavailable", "camera OTA power evidence is unavailable") from exc
    output = str(getattr(completed, "stdout", "")).strip()
    if getattr(completed, "returncode", 1) != 0 or output != "throttled=0x0":
        destination.unlink(missing_ok=True)
        raise LocalControlError("power_unstable", "camera OTA requires stable Pi power")
    payload = {
        "schema_version": 1,
        "last_evaluation": {
            "ts": time.time(),
            "evidence": "none",
            "power_input_out_of_range": False,
            "power_unsustainable": False,
            "power_saver_active": False,
        },
    }
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output_file:
            json.dump(payload, output_file, sort_keys=True, separators=(",", ":"))
            output_file.flush()
            os.fsync(output_file.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EdgeWatch typed device-control forced-command helper")
    parser.add_argument("--device-id", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ssh-stdin", action="store_true")
    mode.add_argument("--render-authorized-key", metavar="PUBLIC_KEY")
    parser.add_argument("--runtime-profile", choices=tuple(_RUNTIME_ENV_FILES))
    parser.add_argument(
        "--helper-path",
        default="/usr/local/lib/edgewatch/scripts/edgewatch_device_control.py",
        help=argparse.SUPPRESS,
    )
    return parser


def render_authorized_key(
    *, public_key: str, helper_path: str, device_id: str, runtime_profile: str | None = None
) -> str:
    if runtime_profile is not None and runtime_profile not in _RUNTIME_ENV_FILES:
        raise LocalControlError("invalid_runtime_profile", "runtime profile is not supported")
    if "\n" in public_key or "\r" in public_key:
        raise LocalControlError("invalid_public_key", "OpenSSH public key must be one line")
    key = public_key.strip()
    key_parts = key.split()
    if len(key_parts) < 2 or key_parts[0] not in {"ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256"}:
        raise LocalControlError("invalid_public_key", "a supported OpenSSH public key is required")
    if not key_parts[1] or any(
        char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
        for char in key_parts[1]
    ):
        raise LocalControlError("invalid_public_key", "invalid OpenSSH public key encoding")
    path = Path(helper_path)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or any(
            char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./-"
            for char in helper_path
        )
    ):
        raise LocalControlError("invalid_helper_path", "helper path must be an absolute safe path")
    # Device ID is validated by the same envelope parser grammar before rendering.
    if (
        not device_id.isascii()
        or not device_id
        or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for c in device_id
        )
    ):
        raise LocalControlError("invalid_device_id", "invalid device ID")
    profile_argument = f" --runtime-profile {runtime_profile}" if runtime_profile else ""
    forced = f"sudo -n {helper_path} --device-id {device_id}{profile_argument} --ssh-stdin"
    return f'restrict,command="{forced}" {key}'


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.render_authorized_key is not None:
        try:
            print(
                render_authorized_key(
                    public_key=args.render_authorized_key,
                    helper_path=args.helper_path,
                    device_id=args.device_id,
                    runtime_profile=args.runtime_profile,
                )
            )
            return 0
        except LocalControlError as exc:
            print(json.dumps(error_response(device_id=args.device_id, command_id=None, error=exc)))
            return 2

    original = (os.getenv("SSH_ORIGINAL_COMMAND") or "").strip()
    if original:
        exc = LocalControlError("original_command_rejected", "SSH_ORIGINAL_COMMAND is not accepted")
        print(json.dumps(error_response(device_id=args.device_id, command_id=None, error=exc)))
        return 2

    raw = sys.stdin.buffer.read(MAX_ENVELOPE_BYTES + 1)
    command_id = None
    try:
        envelope = parse_envelope(raw, expected_device_id=args.device_id)
        command_id = envelope.command_id
        if args.runtime_profile is not None:
            if os.geteuid() != 0:
                raise LocalControlError("local_configuration", "runtime profile requires root")
            _load_runtime_environment(args.runtime_profile)
            if args.runtime_profile == "camera-satellite" and envelope.command_type in _OTA_POWER_COMMANDS:
                _refresh_camera_power_evidence()
        executor = LocalControlExecutor(
            device_id=args.device_id,
            state=LocalControlState.from_env(args.device_id),
            ledger=AppliedCommandLedger.from_env(args.device_id),
        )
        response = executor.execute(envelope)
        print(json.dumps(response, sort_keys=True, separators=(",", ":")))
        return 0
    except LocalControlError as exc:
        print(
            json.dumps(
                error_response(device_id=args.device_id, command_id=command_id, error=exc),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2
    except Exception:
        exc = LocalControlError("internal_error", "local control command failed")
        print(json.dumps(error_response(device_id=args.device_id, command_id=command_id, error=exc)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
