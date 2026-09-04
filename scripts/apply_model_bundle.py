#!/usr/bin/env python3
"""Validate and atomically activate a staged EdgeWatch camera model bundle."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator
from typing import Callable

from agent.inference.bundle import ModelActivationError, ModelBundleError, ModelBundleManager


def _manager() -> ModelBundleManager:
    return ModelBundleManager(
        releases_root=Path(os.getenv("EDGEWATCH_MODEL_RELEASES_ROOT", "/opt/edgewatch/models/releases")),
        current_symlink=Path(os.getenv("EDGEWATCH_MODEL_CURRENT_SYMLINK", "/opt/edgewatch/models/current")),
        keyring_dir=Path(os.getenv("EDGEWATCH_MODEL_KEYRING_DIR", "/opt/edgewatch/keys")),
        hardware_model=os.getenv("EDGEWATCH_HARDWARE_MODEL", "raspberry-pi-zero-2"),
        litert_version=os.getenv("EDGEWATCH_MODEL_LITERT_VERSION", "2.1.6"),
    )


_CHECK_UNIT = "edgewatch-camera-satellite@check.service"
_RESULT_PATH = Path("/var/lib/edgewatch-camera-satellite/result.json")
_MAX_RESULT_BYTES = 64 * 1024
_OUTER_MARKER = ".edgewatch-release.json"
_MAX_MODEL_VIEW_ENTRIES = 128
_MAX_MODEL_VIEW_BYTES = 512 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ACTIVATION_LOCK = Path("/run/edgewatch-camera-model-activation.lock")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _activation_lock(*, nonblocking: bool) -> Iterator[bool]:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(_ACTIVATION_LOCK, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise ModelBundleError("model activation lock is not a root-owned regular file")
        operation = fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0)
        try:
            fcntl.flock(descriptor, operation)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _validate_outer_marker(path: Path) -> None:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= 4096:
            raise ModelBundleError("outer OTA staging marker is invalid")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelBundleError("outer OTA staging marker is invalid") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"artifact_sha256"}
        or not isinstance(payload.get("artifact_sha256"), str)
        or _SHA256.fullmatch(payload["artifact_sha256"]) is None
    ):
        raise ModelBundleError("outer OTA staging marker is invalid")


def _copy_regular_nofollow(source: Path, destination: Path, *, expected_size: int) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
    except OSError as exc:
        raise ModelBundleError("staged model bundle file cannot be opened safely") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != expected_size:
            raise ModelBundleError("staged model bundle changed during activation")
        with os.fdopen(descriptor, "rb", closefd=False) as input_file, destination.open("xb") as output_file:
            shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
            output_file.flush()
            os.fsync(output_file.fileno())
    finally:
        os.close(descriptor)


@contextmanager
def _activation_source(staged: Path) -> Iterator[Path]:
    """Yield an exact model view, excluding only LocalOta's verified outer marker."""

    try:
        metadata = staged.lstat()
    except OSError as exc:
        raise ModelBundleError("staged model bundle is unavailable") from exc
    if staged.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise ModelBundleError("staged model bundle must be a real directory")
    marker = staged / _OUTER_MARKER
    if not marker.exists() and not marker.is_symlink():
        yield staged
        return
    _validate_outer_marker(marker)
    with tempfile.TemporaryDirectory(prefix=".edgewatch-model-activation-", dir=staged.parent) as name:
        clean = Path(name) / "bundle"
        clean.mkdir(mode=0o700)
        entry_count = 0
        total_bytes = 0
        directories = [clean]
        for source_root, directory_names, file_names in os.walk(staged, followlinks=False):
            source_directory = Path(source_root)
            relative_directory = source_directory.relative_to(staged)
            target_directory = clean / relative_directory
            for directory_name in directory_names:
                source = source_directory / directory_name
                source_metadata = source.lstat()
                if source.is_symlink() or not stat.S_ISDIR(source_metadata.st_mode):
                    raise ModelBundleError("staged model bundle contains a forbidden filesystem entry")
                entry_count += 1
                if entry_count > _MAX_MODEL_VIEW_ENTRIES:
                    raise ModelBundleError("staged model bundle inventory is too large")
                destination = target_directory / directory_name
                destination.mkdir(mode=0o700)
                directories.append(destination)
            for file_name in file_names:
                source = source_directory / file_name
                if relative_directory == Path(".") and file_name == _OUTER_MARKER:
                    continue
                source_metadata = source.lstat()
                if source.is_symlink() or not stat.S_ISREG(source_metadata.st_mode):
                    raise ModelBundleError("staged model bundle contains a forbidden filesystem entry")
                entry_count += 1
                total_bytes += source_metadata.st_size
                if entry_count > _MAX_MODEL_VIEW_ENTRIES or total_bytes > _MAX_MODEL_VIEW_BYTES:
                    raise ModelBundleError("staged model bundle inventory is too large")
                destination = target_directory / file_name
                _copy_regular_nofollow(
                    source,
                    destination,
                    expected_size=source_metadata.st_size,
                )
                destination.chmod(0o600)
        for directory in reversed(directories):
            _fsync_directory(directory)
        yield clean


def _readiness(
    bundle_identity: str,
    *,
    run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    result_path: Path = _RESULT_PATH,
) -> bool:
    """Run readiness as the supervised camera user and validate its fresh result."""

    try:
        result_path.unlink(missing_ok=True)
        completed = run_command(
            ["/usr/bin/systemctl", "start", _CHECK_UNIT],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if completed.returncode != 0:
        return False
    try:
        metadata = result_path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) & (stat.S_IRWXG | stat.S_IRWXO)
            or not 0 < metadata.st_size <= _MAX_RESULT_BYTES
        ):
            return False
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("status") == "ok"
        and payload.get("mode") == "check"
        and payload.get("manifest_identity") == bundle_identity
        and payload.get("poweroff_requested") is False
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recover-only",
        action="store_true",
        help="resolve an interrupted model activation without staging or applying a bundle",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.recover_only:
        try:
            with _activation_lock(nonblocking=True) as acquired:
                if not acquired:
                    print(json.dumps({"recovered": False, "status": "deferred"}, sort_keys=True))
                    return 0
                recovered = _manager().recover_interrupted_activation()
        except (ModelActivationError, ModelBundleError, OSError, ValueError) as exc:
            print(f"model activation recovery failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"recovered": recovered, "status": "ok"}, sort_keys=True))
        return 0
    staged = os.getenv("EDGEWATCH_OTA_ARTIFACT_PATH", "").strip()
    if not staged:
        print("model activation failed: EDGEWATCH_OTA_ARTIFACT_PATH is required", file=sys.stderr)
        return 2
    try:
        with _activation_lock(nonblocking=False):
            manager = _manager()
            with _activation_source(Path(staged)) as source:
                bundle = manager.stage(source)
            result = manager.activate(
                bundle.manifest.version,
                readiness_probe=lambda installed: _readiness(installed.manifest.identity),
            )
    except (ModelActivationError, ModelBundleError, OSError, ValueError) as exc:
        print(f"model activation failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "manifest_identity": result.manifest_identity,
                "previous_target": result.previous_target,
                "status": "applied",
                "version": result.version,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
