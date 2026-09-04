"""Build a reproducible, signed application-bundle OTA release catalog."""

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
from pathlib import Path, PurePosixPath
from typing import Sequence

try:
    from scripts.package_dist import _should_exclude
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from package_dist import _should_exclude


REPO_ROOT = Path(__file__).resolve().parents[1]
SIGNATURE_SCHEME = "openssl_rsa_sha256"
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_HEX_COMMIT = re.compile(r"[0-9a-fA-F]{7,64}\Z")
_RUNTIME_DEPENDENCY_INPUT = Path("agent/requirements.txt")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_manifest_bytes(payload: dict[str, object]) -> bytes:
    unsigned = dict(payload)
    unsigned.pop("manifest_signature", None)
    return json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def _validate_identifier(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    value = value.strip()
    if not _SAFE_IDENTIFIER.fullmatch(value) or value in {".", ".."}:
        raise ValueError(f"{field} must contain only safe identifier characters")
    return value


def _validate_private_key(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ValueError("private key file is not accessible") from exc
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise ValueError("private key must be a regular, non-symlink file")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ValueError("private key permissions must be exactly 0600")


def _git_tracked_files(source_root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=source_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("unable to enumerate tracked release files") from exc
    return [Path(os.fsdecode(value)) for value in result.stdout.split(b"\0") if value]


def _validate_git_source_identity(source_root: Path, git_tag: str, commit_sha: str) -> None:
    """Bind manifest identity to the exact tracked worktree bytes being signed."""

    try:
        root_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=source_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        raise ValueError("source_root must be a Git worktree root") from None
    if Path(root_result.stdout.strip()).resolve() != source_root.resolve():
        raise ValueError("source_root must be the Git worktree root")

    def resolve_commit(revision: str, *, error: str) -> str:
        try:
            return (
                subprocess.run(
                    ["git", "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"],
                    cwd=source_root,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                .stdout.strip()
                .lower()
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ValueError(error) from exc

    head = resolve_commit("HEAD", error="unable to resolve source worktree HEAD")
    supplied_commit = resolve_commit(commit_sha, error="commit_sha does not resolve to a commit")
    tag_commit = resolve_commit(
        f"refs/tags/{git_tag}", error=f"exact Git tag refs/tags/{git_tag} does not exist"
    )
    if supplied_commit != head:
        raise ValueError("commit_sha does not match the source worktree HEAD")
    if tag_commit != head:
        raise ValueError("git_tag does not resolve to the source worktree HEAD")
    if tag_commit != supplied_commit:
        raise ValueError("git_tag does not resolve to commit_sha")
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=source_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    ).stdout
    if status:
        raise ValueError("source worktree has tracked changes")


def _validate_relative_path(path: Path) -> None:
    archive_path = PurePosixPath(path.as_posix())
    if archive_path.is_absolute() or not archive_path.parts or ".." in archive_path.parts:
        raise ValueError(f"unsafe archive path: {path}")


def _discover_files(source_root: Path) -> list[Path]:
    tracked = _git_tracked_files(source_root)
    files: list[Path] = []
    for relative in tracked:
        _validate_relative_path(relative)
        absolute = source_root / relative
        if _should_exclude(relative) or not absolute.exists() or absolute.is_dir():
            continue
        if absolute.is_symlink() or not absolute.is_file():
            raise ValueError(f"bundle input must be a regular file: {relative}")
        files.append(relative)
    return sorted(files, key=lambda path: path.as_posix().encode("utf-8"))


def _write_reproducible_bundle(source_root: Path, destination: Path) -> None:
    files = _discover_files(source_root)
    if not files:
        raise ValueError("no files discovered for the application bundle")
    with destination.open("wb") as raw_output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_output, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                for relative in files:
                    source = source_root / relative
                    metadata = source.stat()
                    member = tarfile.TarInfo(relative.as_posix())
                    member.size = metadata.st_size
                    member.mode = 0o755 if metadata.st_mode & 0o111 else 0o644
                    member.mtime = 0
                    member.uid = 0
                    member.gid = 0
                    member.uname = ""
                    member.gname = ""
                    with source.open("rb") as contents:
                        archive.addfile(member, contents)


def _run_openssl(command: Sequence[str], *, error: str) -> None:
    try:
        result = subprocess.run(
            list(command),
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise RuntimeError(error) from exc
    if result.returncode != 0:
        raise RuntimeError(error)


def build_release(
    *,
    source_root: Path,
    output_dir: Path,
    private_key: Path,
    key_id: str,
    artifact_uri: str,
    version: str,
    git_tag: str,
    commit_sha: str,
    hardware_models: Sequence[str] = ("raspberry-pi-4", "raspberry-pi-5"),
    release_channel: str = "stable",
    minimum_python_version: str = "3.11.0",
    minimum_runtime_schema: int = 1,
    minimum_ota_schema: int = 1,
    requires_stable_power: bool = True,
    requires_apply_enabled: bool = True,
    minimum_free_bytes: int = 256 * 1024 * 1024,
) -> tuple[Path, Path, Path]:
    """Build artifact, detached signature, and compatible catalog atomically."""

    version = _validate_identifier(version, "version")
    git_tag = _validate_identifier(git_tag, "git_tag")
    key_id = _validate_identifier(key_id, "key_id")
    release_channel = _validate_identifier(release_channel, "release_channel")
    normalized_models = [_validate_identifier(value, "hardware_model") for value in hardware_models]
    if (
        not normalized_models
        or len(normalized_models) > 32
        or len(set(normalized_models)) != len(normalized_models)
    ):
        raise ValueError("hardware_models must be a unique list of 1 through 32 models")
    if (
        not isinstance(minimum_python_version, str)
        or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", minimum_python_version) is None
    ):
        raise ValueError("minimum_python_version must be MAJOR.MINOR.PATCH")
    if not isinstance(requires_stable_power, bool) or not isinstance(requires_apply_enabled, bool):
        raise ValueError("power and apply compatibility constraints must be boolean")
    for field, value, minimum in (
        ("minimum_runtime_schema", minimum_runtime_schema, 1),
        ("minimum_ota_schema", minimum_ota_schema, 1),
        ("minimum_free_bytes", minimum_free_bytes, 0),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"{field} must be an integer >= {minimum}")
    commit_sha = commit_sha.strip().lower()
    if not _HEX_COMMIT.fullmatch(commit_sha):
        raise ValueError("commit_sha must be 7-64 hexadecimal characters")
    source_root = source_root.resolve()
    _validate_git_source_identity(source_root, git_tag, commit_sha)
    runtime_dependency_input = source_root / _RUNTIME_DEPENDENCY_INPUT
    if not runtime_dependency_input.is_file() or runtime_dependency_input.is_symlink():
        raise ValueError(f"runtime dependency input is missing: {_RUNTIME_DEPENDENCY_INPUT}")
    runtime_dependency_sha256 = _sha256(runtime_dependency_input)
    parsed_uri = urllib.parse.urlparse(artifact_uri)
    if parsed_uri.scheme != "https" or not parsed_uri.netloc:
        raise ValueError("artifact_uri must be an absolute HTTPS URI")
    _validate_private_key(private_key)
    _run_openssl(
        ["openssl", "rsa", "-in", str(private_key), "-check", "-noout"],
        error="private key is not a valid OpenSSL RSA private key",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = output_dir / f"edgewatch-ota_v{version}.tar.gz"
    signature = artifact.with_suffix(artifact.suffix + ".sig")
    catalog = output_dir / f"edgewatch-ota_v{version}.catalog.json"
    with tempfile.TemporaryDirectory(prefix=".edgewatch-ota-", dir=output_dir) as temporary_name:
        temporary = Path(temporary_name)
        temporary_artifact = temporary / artifact.name
        temporary_signature = temporary / signature.name
        temporary_catalog = temporary / catalog.name
        temporary_manifest = temporary / "manifest.json"
        temporary_manifest_signature = temporary / "manifest.sig"
        _write_reproducible_bundle(source_root, temporary_artifact)
        _run_openssl(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-sign",
                str(private_key),
                "-out",
                str(temporary_signature),
                str(temporary_artifact),
            ],
            error="OpenSSL RSA/SHA-256 artifact signing failed",
        )
        manifest = {
            "version": version,
            "git_tag": git_tag,
            "commit_sha": commit_sha,
            "update_type": "application_bundle",
            "artifact_uri": artifact_uri,
            "artifact_size": temporary_artifact.stat().st_size,
            "artifact_sha256": _sha256(temporary_artifact),
            "artifact_signature": base64.b64encode(temporary_signature.read_bytes()).decode("ascii"),
            "artifact_signature_scheme": SIGNATURE_SCHEME,
            "signature_key_id": key_id,
            "runtime_dependency_sha256": runtime_dependency_sha256,
            "compatibility": {
                "schema_version": 1,
                "hardware_models": normalized_models,
                "release_channel": release_channel,
                "minimum_python_version": minimum_python_version,
                "minimum_runtime_schema": minimum_runtime_schema,
                "minimum_ota_schema": minimum_ota_schema,
                "requires_stable_power": requires_stable_power,
                "requires_apply_enabled": requires_apply_enabled,
                "minimum_free_bytes": minimum_free_bytes,
            },
        }
        temporary_manifest.write_bytes(_canonical_manifest_bytes(manifest))
        _run_openssl(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-sign",
                str(private_key),
                "-out",
                str(temporary_manifest_signature),
                str(temporary_manifest),
            ],
            error="OpenSSL RSA/SHA-256 manifest signing failed",
        )
        manifest["manifest_signature"] = base64.b64encode(temporary_manifest_signature.read_bytes()).decode(
            "ascii"
        )
        payload = {"schema_version": 1, "releases": {git_tag: manifest}, "aliases": {}}
        temporary_catalog.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary_artifact, artifact)
        os.replace(temporary_signature, signature)
        os.replace(temporary_catalog, catalog)
    return artifact, signature, catalog


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--artifact-uri", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument(
        "--hardware-model",
        action="append",
        dest="hardware_models",
        default=None,
        help="Compatible hardware identifier; repeat for multiple models (default: Pi 4 and Pi 5).",
    )
    parser.add_argument("--release-channel", default="stable")
    parser.add_argument("--minimum-python-version", default="3.11.0")
    parser.add_argument("--minimum-runtime-schema", type=int, default=1)
    parser.add_argument("--minimum-ota-schema", type=int, default=1)
    parser.add_argument("--minimum-free-bytes", type=int, default=256 * 1024 * 1024)
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "dist")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        artifact, signature, catalog = build_release(
            source_root=REPO_ROOT,
            output_dir=args.output_dir,
            private_key=args.private_key,
            key_id=args.key_id,
            artifact_uri=args.artifact_uri,
            version=args.version,
            git_tag=args.tag,
            commit_sha=args.commit,
            hardware_models=args.hardware_models or ("raspberry-pi-4", "raspberry-pi-5"),
            release_channel=args.release_channel,
            minimum_python_version=args.minimum_python_version,
            minimum_runtime_schema=args.minimum_runtime_schema,
            minimum_ota_schema=args.minimum_ota_schema,
            minimum_free_bytes=args.minimum_free_bytes,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from exc
    print(json.dumps({"artifact": str(artifact), "catalog": str(catalog), "signature": str(signature)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
