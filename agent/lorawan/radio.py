"""Fail-closed contract for a local SX1302/SX1303 radio ingress adapter.

The repository does not ship or bless a concentrator binary. A production
adapter must be installed separately, pinned by SHA-256, and implement the
fixed command/status contract below. Readiness requires both detected radio
hardware and a connected ChirpStack MQTT gateway bridge.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


_GATEWAY_ID = re.compile(r"[0-9a-fA-F]{16}\Z")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
_INSTANCE_ID = re.compile(r"[0-9a-f]{32}\Z")
_CONFIG_KEYS = frozenset(
    {
        "schema_version",
        "gateway_id",
        "region",
        "concentrator",
        "adapter_executable",
        "adapter_sha256",
        "adapter_config_file",
        "status_file",
        "instance_file",
        "status_max_age_s",
        "startup_timeout_s",
    }
)
_STATUS_KEYS = frozenset(
    {
        "schema_version",
        "gateway_id",
        "region",
        "concentrator",
        "instance_id",
        "concentrator_detected",
        "gateway_bridge_connected",
        "updated_at",
    }
)
_INSTANCE_KEYS = frozenset({"schema_version", "gateway_id", "instance_id", "started_at"})
_MAX_FILE_BYTES = 64 * 1024


class RadioIngressError(RuntimeError):
    """Raised when local LoRaWAN radio ingress cannot be proven ready."""


def _closed_mapping(value: object, *, where: str, allowed: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise RadioIngressError(f"{where} must be a mapping")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise RadioIngressError(f"unknown key(s) in {where}: {', '.join(unknown)}")
    return value


def _private_regular_file(path: Path, *, where: str) -> Path:
    try:
        file_stat = path.lstat()
    except OSError as exc:
        raise RadioIngressError(f"{where} cannot be read") from exc
    mode = stat.S_IMODE(file_stat.st_mode)
    if (
        stat.S_ISLNK(file_stat.st_mode)
        or not stat.S_ISREG(file_stat.st_mode)
        or mode & (stat.S_IRWXG | stat.S_IRWXO)
        or file_stat.st_size > _MAX_FILE_BYTES
    ):
        raise RadioIngressError(
            f"{where} must be a private regular file no larger than {_MAX_FILE_BYTES} bytes"
        )
    return path


def _read_json(path: Path, *, where: str) -> Mapping[str, Any]:
    _private_regular_file(path, where=where)

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite value is not allowed: {value}")

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    except (OSError, UnicodeError, ValueError) as exc:
        raise RadioIngressError(f"{where} must contain valid UTF-8 JSON") from exc
    return _closed_mapping(parsed, where=where, allowed=_STATUS_KEYS | _INSTANCE_KEYS)


def _absolute_path(value: object, *, where: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise RadioIngressError(f"{where} must be a non-empty absolute path")
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        raise RadioIngressError(f"{where} must be an absolute path")
    return path


def _bounded_int(value: object, *, where: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise RadioIngressError(f"{where} must be from {minimum} through {maximum}")
    return value


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_private_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class RadioIngressConfig:
    gateway_id: str
    adapter_executable: Path
    adapter_sha256: str
    adapter_config_file: Path
    status_file: Path
    instance_file: Path
    region: str = "US915"
    concentrator: str = "sx1302"
    status_max_age_s: int = 30
    startup_timeout_s: int = 90

    def __post_init__(self) -> None:
        if not isinstance(self.gateway_id, str) or _GATEWAY_ID.fullmatch(self.gateway_id) is None:
            raise RadioIngressError("radio gateway_id must contain exactly 16 hexadecimal characters")
        if self.region != "US915":
            raise RadioIngressError("radio region must be US915 for the v1 field profile")
        if self.concentrator not in {"sx1302", "sx1303"}:
            raise RadioIngressError("radio concentrator must be sx1302 or sx1303")
        if not isinstance(self.adapter_sha256, str) or _SHA256.fullmatch(self.adapter_sha256) is None:
            raise RadioIngressError("radio adapter_sha256 must be a complete SHA-256 digest")
        for name in ("adapter_executable", "adapter_config_file", "status_file", "instance_file"):
            path = getattr(self, name)
            if not isinstance(path, Path) or not path.is_absolute():
                raise RadioIngressError(f"radio {name} must be an absolute filesystem path")
        if len({self.adapter_config_file, self.status_file, self.instance_file}) != 3:
            raise RadioIngressError("radio config, status, and instance paths must be distinct")
        _bounded_int(
            self.status_max_age_s,
            where="radio status_max_age_s",
            minimum=5,
            maximum=300,
        )
        _bounded_int(
            self.startup_timeout_s,
            where="radio startup_timeout_s",
            minimum=10,
            maximum=600,
        )
        object.__setattr__(self, "gateway_id", self.gateway_id.lower())
        object.__setattr__(self, "adapter_sha256", self.adapter_sha256.lower())

    def validate_installation(self) -> None:
        """Verify the executable pin and the private hardware configuration."""

        try:
            executable_stat = self.adapter_executable.lstat()
        except OSError as exc:
            raise RadioIngressError("pinned radio adapter executable is not installed") from exc
        mode = stat.S_IMODE(executable_stat.st_mode)
        if (
            stat.S_ISLNK(executable_stat.st_mode)
            or not stat.S_ISREG(executable_stat.st_mode)
            or not mode & stat.S_IXUSR
            or mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise RadioIngressError("radio adapter must be a non-writable executable regular file")
        digest = hashlib.sha256()
        try:
            with self.adapter_executable.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise RadioIngressError("radio adapter executable cannot be hashed") from exc
        if not hmac.compare_digest(digest.hexdigest(), self.adapter_sha256):
            raise RadioIngressError("radio adapter executable does not match its SHA-256 pin")
        _private_regular_file(self.adapter_config_file, where="radio adapter_config_file")

    def command(self, instance_id: str) -> list[str]:
        if _INSTANCE_ID.fullmatch(instance_id) is None:
            raise RadioIngressError("radio adapter instance_id is invalid")
        return [
            str(self.adapter_executable),
            "--config",
            str(self.adapter_config_file),
            "--status-file",
            str(self.status_file),
            "--gateway-id",
            self.gateway_id,
            "--region",
            self.region,
            "--concentrator",
            self.concentrator,
            "--instance-id",
            instance_id,
        ]


def load_radio_ingress_config(path: str | Path) -> RadioIngressConfig:
    config_path = Path(path).expanduser().absolute()
    _private_regular_file(config_path, where="radio ingress config")
    try:
        parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RadioIngressError("radio ingress config must contain valid UTF-8 YAML") from exc
    root = _closed_mapping(parsed, where="radio ingress config", allowed=_CONFIG_KEYS)
    schema_version = root.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != 1:
        raise RadioIngressError("radio ingress config schema_version must be 1")
    gateway_id = root.get("gateway_id")
    adapter_sha256 = root.get("adapter_sha256")
    region = root.get("region", "US915")
    concentrator = root.get("concentrator", "sx1302")
    if not isinstance(gateway_id, str):
        raise RadioIngressError("radio gateway_id must be text")
    if not isinstance(adapter_sha256, str):
        raise RadioIngressError("radio adapter_sha256 must be text")
    if not isinstance(region, str) or not isinstance(concentrator, str):
        raise RadioIngressError("radio region and concentrator must be text")
    return RadioIngressConfig(
        gateway_id=gateway_id,
        region=region,
        concentrator=concentrator,
        adapter_executable=_absolute_path(root.get("adapter_executable"), where="radio adapter_executable"),
        adapter_sha256=adapter_sha256,
        adapter_config_file=_absolute_path(
            root.get("adapter_config_file"), where="radio adapter_config_file"
        ),
        status_file=_absolute_path(root.get("status_file"), where="radio status_file"),
        instance_file=_absolute_path(root.get("instance_file"), where="radio instance_file"),
        status_max_age_s=_bounded_int(
            root.get("status_max_age_s", 30),
            where="radio status_max_age_s",
            minimum=5,
            maximum=300,
        ),
        startup_timeout_s=_bounded_int(
            root.get("startup_timeout_s", 90),
            where="radio startup_timeout_s",
            minimum=10,
            maximum=600,
        ),
    )


class RadioIngressHealth:
    """Validate a fresh status bound to the currently supervised adapter instance."""

    def __init__(self, config: RadioIngressConfig, *, clock=time.time):
        self.config = config
        self.clock = clock

    def create_instance(self) -> str:
        instance_id = secrets.token_hex(16)
        _write_private_json(
            self.config.instance_file,
            {
                "gateway_id": self.config.gateway_id,
                "instance_id": instance_id,
                "schema_version": 1,
                "started_at": float(self.clock()),
            },
        )
        return instance_id

    def assert_ready(self, *, now: float | None = None) -> None:
        current = float(self.clock() if now is None else now)
        if not math.isfinite(current) or current < 0:
            raise RadioIngressError("radio health clock is invalid")
        instance = _closed_mapping(
            _read_json(self.config.instance_file, where="radio instance file"),
            where="radio instance file",
            allowed=_INSTANCE_KEYS,
        )
        status = _closed_mapping(
            _read_json(self.config.status_file, where="radio status file"),
            where="radio status file",
            allowed=_STATUS_KEYS,
        )
        instance_id = instance.get("instance_id")
        started_at = instance.get("started_at")
        if (
            type(instance.get("schema_version")) is not int
            or instance.get("schema_version") != 1
            or instance.get("gateway_id") != self.config.gateway_id
            or not isinstance(instance_id, str)
            or _INSTANCE_ID.fullmatch(instance_id) is None
            or isinstance(started_at, bool)
            or not isinstance(started_at, (int, float))
            or not math.isfinite(float(started_at))
            or not 0 <= float(started_at) <= current + 5
            or type(status.get("schema_version")) is not int
            or status.get("schema_version") != 1
            or status.get("gateway_id") != self.config.gateway_id
            or status.get("region") != self.config.region
            or status.get("concentrator") != self.config.concentrator
            or status.get("instance_id") != instance_id
            or status.get("concentrator_detected") is not True
            or status.get("gateway_bridge_connected") is not True
        ):
            raise RadioIngressError("radio ingress identity or readiness proof is invalid")
        updated_at = status.get("updated_at")
        if (
            isinstance(updated_at, bool)
            or not isinstance(updated_at, (int, float))
            or not math.isfinite(float(updated_at))
            or float(updated_at) > current + 5
            or current - float(updated_at) > self.config.status_max_age_s
        ):
            raise RadioIngressError("radio ingress readiness proof is stale")


def wait_until_ready(config: RadioIngressConfig, *, sleeper=time.sleep, clock=time.time) -> None:
    config.validate_installation()
    health = RadioIngressHealth(config, clock=clock)
    deadline = float(clock()) + config.startup_timeout_s
    while True:
        try:
            health.assert_ready()
            return
        except RadioIngressError:
            if float(clock()) >= deadline:
                raise RadioIngressError("radio ingress did not become ready before its deadline") from None
            sleeper(1.0)


def run_adapter(config: RadioIngressConfig) -> int:
    """Run and continuously supervise the separately installed pinned adapter."""

    config.validate_installation()
    health = RadioIngressHealth(config)
    instance_id = health.create_instance()
    process = subprocess.Popen(config.command(instance_id))
    ready = False
    deadline = time.monotonic() + config.startup_timeout_s
    interval_s = max(1.0, min(5.0, config.status_max_age_s / 2))
    try:
        while True:
            return_code = process.poll()
            if return_code is not None:
                return return_code if return_code != 0 else 1
            try:
                health.assert_ready()
                ready = True
            except RadioIngressError as exc:
                if ready or time.monotonic() >= deadline:
                    logging.error("LoRaWAN radio ingress lost readiness: %s", exc)
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    return 1
            time.sleep(interval_s)
    finally:
        if process.poll() is None:
            process.terminate()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Supervise the pinned LoRaWAN radio ingress adapter")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for operation in ("run", "check"):
        command = subparsers.add_parser(operation)
        command.add_argument("--config", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = load_radio_ingress_config(args.config)
        if args.operation == "check":
            wait_until_ready(config)
            return 0
        return run_adapter(config)
    except (OSError, RadioIngressError) as exc:
        logging.error("LoRaWAN radio ingress cannot start: %s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
