#!/usr/bin/env python3
"""Build a deterministic, doubly signed EdgeWatch model OTA release."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
import re
import stat
import subprocess
import tarfile
import tempfile
import urllib.parse
from collections.abc import Sequence
from pathlib import Path

from agent.inference.bundle import ModelBundleManager, canonical_model_manifest_bytes
from agent.local_ota import canonical_manifest_bytes


REPO_ROOT = Path(__file__).resolve().parents[1]
SIGNATURE_SCHEME = "openssl_rsa_sha256"
MODEL_FILES = {
    "vision_model": "vision.tflite",
    "audio_model": "audio.tflite",
    "labels": "labels.json",
    "preprocessing": "preprocessing.json",
    "thresholds": "thresholds.json",
    "known_answer": "known_answer.json",
}
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _safe_id(value: str, field: str) -> str:
    normalized = value.strip()
    if normalized in {"", ".", ".."} or _SAFE_ID.fullmatch(normalized) is None:
        raise ValueError(f"{field} must be a safe identifier")
    return normalized


def _private_key(path: Path) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ValueError("private key is not accessible") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("private key must be a regular non-symlink file")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ValueError("private key permissions must be exactly 0600")
    return path


def _run(command: Sequence[str], error: str) -> None:
    try:
        result = subprocess.run(
            list(command),
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(error) from exc
    if result.returncode != 0:
        raise RuntimeError(error)


def _sign(private_key: Path, payload: Path, destination: Path) -> bytes:
    _run(
        [
            "openssl",
            "dgst",
            "-sha256",
            "-sign",
            str(private_key),
            "-out",
            str(destination),
            str(payload),
        ],
        "OpenSSL RSA/SHA-256 signing failed",
    )
    return destination.read_bytes()


def _write_reproducible_archive(source: Path, destination: Path) -> None:
    names = ["manifest.json", *sorted(MODEL_FILES.values())]
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                for name in names:
                    path = source / name
                    metadata = tarfile.TarInfo(name)
                    metadata.size = path.stat().st_size
                    metadata.mode = 0o644
                    metadata.mtime = 0
                    metadata.uid = metadata.gid = 0
                    metadata.uname = metadata.gname = ""
                    with path.open("rb") as contents:
                        archive.addfile(metadata, contents)


def _validate_source(source: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("model source must be a real directory")
    found = {path.name for path in source.iterdir() if path.is_file() and not path.is_symlink()}
    expected = set(MODEL_FILES.values())
    if found != expected or any(path.is_symlink() or not path.is_file() for path in source.iterdir()):
        raise ValueError("model source must contain exactly the six required regular files")


def build_model_release(
    *,
    source_dir: Path,
    output_dir: Path,
    private_key: Path,
    key_id: str,
    artifact_uri: str,
    version: str,
    hardware_models: Sequence[str] = ("raspberry-pi-zero-2",),
    minimum_litert_version: str = "2.1.6",
    release_channel: str = "stable",
) -> tuple[Path, Path, Path]:
    """Return the model artifact, detached artifact signature, and OTA catalog."""

    source_dir = source_dir.resolve()
    _validate_source(source_dir)
    private_key = _private_key(private_key.resolve())
    version = _safe_id(version, "version")
    key_id = _safe_id(key_id, "key_id")
    release_channel = _safe_id(release_channel, "release_channel")
    models = [_safe_id(item, "hardware_model") for item in hardware_models]
    if not models or len(models) > 16 or len(set(models)) != len(models):
        raise ValueError("hardware_models must contain 1..16 unique values")
    if _SEMVER.fullmatch(minimum_litert_version) is None:
        raise ValueError("minimum_litert_version must be MAJOR.MINOR.PATCH")
    parsed_uri = urllib.parse.urlparse(artifact_uri)
    if parsed_uri.scheme != "https" or not parsed_uri.netloc:
        raise ValueError("artifact_uri must be an absolute HTTPS URI")
    _run(
        ["openssl", "rsa", "-in", str(private_key), "-check", "-noout"],
        "private key is not a valid RSA key",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = output_dir / f"edgewatch-model_{version}.tar.gz"
    artifact_signature = artifact.with_suffix(artifact.suffix + ".sig")
    catalog = output_dir / f"edgewatch-model_{version}.catalog.json"
    with tempfile.TemporaryDirectory(prefix=".edgewatch-model-", dir=output_dir) as temporary_name:
        temporary = Path(temporary_name)
        bundle = temporary / "bundle"
        bundle.mkdir()
        files: dict[str, dict[str, str | int]] = {}
        for role, name in MODEL_FILES.items():
            source = source_dir / name
            payload = source.read_bytes()
            destination = bundle / name
            destination.write_bytes(payload)
            files[role] = {"path": name, "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}

        inner_manifest: dict[str, object] = {
            "schema_version": 1,
            "version": version,
            "signature_key_id": key_id,
            "compatibility": {
                "schema_version": 1,
                "hardware_models": list(models),
                "minimum_litert_version": minimum_litert_version,
            },
            "files": files,
        }
        unsigned_inner = temporary / "model-manifest.unsigned.json"
        unsigned_inner.write_bytes(canonical_model_manifest_bytes(inner_manifest))
        inner_signature = _sign(private_key, unsigned_inner, temporary / "model-manifest.sig")
        inner_manifest["signature"] = base64.b64encode(inner_signature).decode("ascii")
        (bundle / "manifest.json").write_text(
            json.dumps(inner_manifest, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="ascii",
        )

        keyring = temporary / "keyring"
        keyring.mkdir()
        public_key = keyring / f"{key_id}.pem"
        _run(
            ["openssl", "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)],
            "could not derive the model verification key",
        )
        public_key.chmod(0o600)
        ModelBundleManager(
            releases_root=temporary / "validation-releases",
            current_symlink=temporary / "validation-current",
            keyring_dir=keyring,
            hardware_model=models[0],
            litert_version=minimum_litert_version,
        ).validate(bundle)

        staged_artifact = temporary / artifact.name
        staged_artifact_signature = temporary / artifact_signature.name
        staged_catalog = temporary / catalog.name
        _write_reproducible_archive(bundle, staged_artifact)
        signature_bytes = _sign(private_key, staged_artifact, staged_artifact_signature)
        artifact_sha256 = _digest(staged_artifact)
        manifest: dict[str, object] = {
            "version": version,
            "git_tag": f"model-{version}",
            "commit_sha": hashlib.sha256(canonical_model_manifest_bytes(inner_manifest)).hexdigest(),
            "update_type": "asset_bundle",
            "artifact_uri": artifact_uri,
            "artifact_size": staged_artifact.stat().st_size,
            "artifact_sha256": artifact_sha256,
            "artifact_signature": base64.b64encode(signature_bytes).decode("ascii"),
            "artifact_signature_scheme": SIGNATURE_SCHEME,
            "signature_key_id": key_id,
            "runtime_dependency_sha256": _digest(REPO_ROOT / "agent" / "requirements.txt"),
            "compatibility": {
                "schema_version": 1,
                "hardware_models": list(models),
                "release_channel": release_channel,
                "minimum_python_version": "3.11.0",
                "minimum_runtime_schema": 1,
                "minimum_ota_schema": 1,
                "requires_stable_power": True,
                "requires_apply_enabled": True,
                "minimum_free_bytes": 128 * 1024 * 1024,
            },
        }
        unsigned_outer = temporary / "ota-manifest.unsigned.json"
        unsigned_outer.write_bytes(canonical_manifest_bytes(manifest))
        outer_signature = _sign(private_key, unsigned_outer, temporary / "ota-manifest.sig")
        manifest["manifest_signature"] = base64.b64encode(outer_signature).decode("ascii")
        staged_catalog.write_text(
            json.dumps(
                {"schema_version": 1, "releases": {f"model-{version}": manifest}, "aliases": {}},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="ascii",
        )
        os.replace(staged_artifact, artifact)
        os.replace(staged_artifact_signature, artifact_signature)
        os.replace(staged_catalog, catalog)
    return artifact, artifact_signature, catalog


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--artifact-uri", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--hardware-model", action="append", dest="hardware_models")
    parser.add_argument("--minimum-litert-version", default="2.1.6")
    parser.add_argument("--release-channel", default="stable")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        artifact, signature, catalog = build_model_release(
            source_dir=args.source_dir,
            output_dir=args.output_dir,
            private_key=args.private_key,
            key_id=args.key_id,
            artifact_uri=args.artifact_uri,
            version=args.version,
            hardware_models=args.hardware_models or ("raspberry-pi-zero-2",),
            minimum_litert_version=args.minimum_litert_version,
            release_channel=args.release_channel,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from exc
    print(json.dumps({"artifact": str(artifact), "catalog": str(catalog), "signature": str(signature)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
