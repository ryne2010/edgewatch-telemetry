from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

import pytest

from agent.local_ota import ReleaseCatalog, canonical_manifest_bytes
from scripts.build_telegram_ota_release import _git_tracked_files, build_release


OPENSSL = shutil.which("openssl")


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    (source / "agent").mkdir(parents=True)
    (source / "scripts").mkdir()
    (source / "agent" / "edgewatch_agent.py").write_text("print('edgewatch')\n", encoding="utf-8")
    (source / "agent" / "requirements.txt").write_text("requests==2.32.4\n", encoding="utf-8")
    (source / "scripts" / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (source / "scripts" / "run.sh").chmod(0o755)
    (source / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (source / "build").mkdir()
    (source / "build" / "junk.txt").write_text("junk\n", encoding="utf-8")
    return source


def _private_key(tmp_path: Path) -> Path:
    if OPENSSL is None:
        pytest.skip("openssl is not available")
    private_key = tmp_path / "release-private.pem"
    subprocess.run(
        [OPENSSL, "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", private_key],
        check=True,
        capture_output=True,
    )
    private_key.chmod(0o600)
    return private_key


def _build(tmp_path: Path, private_key: Path) -> tuple[Path, Path, Path]:
    source = _source(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.invalid"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=source, check=True)
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=source, check=True)
    subprocess.run(["git", "tag", "v1.2.3"], cwd=source, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, check=True, capture_output=True, text=True
    ).stdout.strip()
    return build_release(
        source_root=source,
        output_dir=tmp_path / "dist",
        private_key=private_key,
        key_id="release-2026",
        artifact_uri="https://example.invalid/releases/edgewatch-ota_v1.2.3.tar.gz",
        version="1.2.3",
        git_tag="v1.2.3",
        commit_sha=commit,
    )


def test_bundle_has_repository_root_shape_and_no_unsafe_members(tmp_path: Path) -> None:
    artifact, _, _ = _build(tmp_path, _private_key(tmp_path))
    with tarfile.open(artifact, "r:gz") as archive:
        members = archive.getmembers()
    names = {member.name for member in members}
    assert "agent/edgewatch_agent.py" in names
    assert "scripts/run.sh" in names
    assert ".env" not in names
    assert "build/junk.txt" not in names
    assert all(not PurePosixPath(member.name).is_absolute() for member in members)
    assert all(".." not in PurePosixPath(member.name).parts for member in members)
    assert all(member.isfile() for member in members)


def test_private_key_requires_exact_0600_mode(tmp_path: Path) -> None:
    private_key = tmp_path / "release-private.pem"
    private_key.write_text("not read because the mode is unsafe", encoding="utf-8")
    private_key.chmod(0o640)
    with pytest.raises(ValueError, match="exactly 0600"):
        _build(tmp_path, private_key)
    assert not (tmp_path / "dist").exists()


@pytest.mark.skipif(OPENSSL is None, reason="openssl is not available")
def test_private_key_rejects_non_rsa_key(tmp_path: Path) -> None:
    assert OPENSSL is not None
    private_key = tmp_path / "ec-private.pem"
    subprocess.run(
        [OPENSSL, "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", private_key],
        check=True,
        capture_output=True,
    )
    private_key.chmod(0o600)
    with pytest.raises(RuntimeError, match="RSA private key"):
        _build(tmp_path, private_key)
    assert not (tmp_path / "dist").exists()


@pytest.mark.skipif(OPENSSL is None, reason="openssl is not available")
def test_openssl_signature_and_catalog_are_compatible(tmp_path: Path) -> None:
    assert OPENSSL is not None
    private_key = _private_key(tmp_path)
    public_key = tmp_path / "release-public.pem"
    subprocess.run(
        [OPENSSL, "pkey", "-in", private_key, "-pubout", "-out", public_key],
        check=True,
        capture_output=True,
    )
    artifact, signature, catalog_path = _build(tmp_path, private_key)
    verified = subprocess.run(
        [OPENSSL, "dgst", "-sha256", "-verify", public_key, "-signature", signature, artifact],
        check=False,
        capture_output=True,
        text=True,
    )
    assert verified.returncode == 0

    catalog = ReleaseCatalog.load(catalog_path)
    manifest = catalog.resolve("v1.2.3")
    assert manifest.artifact_size == artifact.stat().st_size
    assert manifest.artifact_sha256 == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert manifest.artifact_signature_scheme == "openssl_rsa_sha256"
    assert manifest.signature_key_id == "release-2026"
    assert manifest.runtime_dependency_sha256 == hashlib.sha256(b"requests==2.32.4\n").hexdigest()
    assert manifest.compatibility == {
        "schema_version": 1,
        "hardware_models": ["raspberry-pi-4", "raspberry-pi-5"],
        "release_channel": "stable",
        "minimum_python_version": "3.11.0",
        "minimum_runtime_schema": 1,
        "minimum_ota_schema": 1,
        "requires_stable_power": True,
        "requires_apply_enabled": True,
        "minimum_free_bytes": 256 * 1024 * 1024,
    }
    manifest_bytes = tmp_path / "manifest.json"
    manifest_signature = tmp_path / "manifest.sig"
    manifest_bytes.write_bytes(canonical_manifest_bytes(manifest.to_command_payload()))
    manifest_signature.write_bytes(base64.b64decode(manifest.manifest_signature, validate=True))
    manifest_verified = subprocess.run(
        [
            OPENSSL,
            "dgst",
            "-sha256",
            "-verify",
            public_key,
            "-signature",
            manifest_signature,
            manifest_bytes,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert manifest_verified.returncode == 0
    assert json.loads(catalog_path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_bundle_is_reproducible(tmp_path: Path) -> None:
    private_key = _private_key(tmp_path)
    first, _, _ = _build(tmp_path / "first", private_key)
    second, _, _ = _build(tmp_path / "second", private_key)
    assert first.read_bytes() == second.read_bytes()


def test_release_workflow_binds_artifacts_to_the_named_git_tag() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "publish-release-bundle.yml"
    ).read_text(encoding="utf-8")

    assert "refs/tags/${TAG_EFFECTIVE}^{commit}" in workflow
    assert 'if [ "${tag_commit}" != "${head_commit}" ]' in workflow
    assert '--commit "${RELEASE_COMMIT}"' in workflow


def test_git_source_rejects_dirty_tracked_bytes_and_false_commit_identity(tmp_path: Path) -> None:
    source = _source(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.invalid"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=source, check=True)
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=source, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, check=True, capture_output=True, text=True
    ).stdout.strip()
    private_key = _private_key(tmp_path)

    with pytest.raises(ValueError, match="exact Git tag"):
        build_release(
            source_root=source,
            output_dir=tmp_path / "missing-tag",
            private_key=private_key,
            key_id="release-2026",
            artifact_uri="https://example.invalid/releases/edgewatch.tar.gz",
            version="1.2.3",
            git_tag="v1.2.3",
            commit_sha=commit,
        )

    subprocess.run(["git", "tag", "v1.2.3"], cwd=source, check=True)

    with pytest.raises(ValueError, match="does not resolve"):
        build_release(
            source_root=source,
            output_dir=tmp_path / "mismatch",
            private_key=private_key,
            key_id="release-2026",
            artifact_uri="https://example.invalid/releases/edgewatch.tar.gz",
            version="1.2.3",
            git_tag="v1.2.3",
            commit_sha="a" * 40,
        )

    (source / "agent" / "edgewatch_agent.py").write_text("print('dirty')\n", encoding="utf-8")
    with pytest.raises(ValueError, match="tracked changes"):
        build_release(
            source_root=source,
            output_dir=tmp_path / "dirty",
            private_key=private_key,
            key_id="release-2026",
            artifact_uri="https://example.invalid/releases/edgewatch.tar.gz",
            version="1.2.3",
            git_tag="v1.2.3",
            commit_sha=commit,
        )


def test_builder_rejects_non_git_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Git worktree root"):
        build_release(
            source_root=_source(tmp_path),
            output_dir=tmp_path / "dist",
            private_key=_private_key(tmp_path),
            key_id="release-2026",
            artifact_uri="https://example.invalid/releases/edgewatch.tar.gz",
            version="1.2.3",
            git_tag="v1.2.3",
            commit_sha="a" * 40,
        )


def test_tracked_file_enumeration_failure_never_falls_back_to_directory_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args, **kwargs):
        del args, kwargs
        raise subprocess.CalledProcessError(1, ["git", "ls-files"])

    monkeypatch.setattr(subprocess, "run", fail)

    with pytest.raises(ValueError, match="enumerate tracked release files"):
        _git_tracked_files(tmp_path)


@pytest.mark.parametrize("annotated", [False, True])
def test_git_source_accepts_lightweight_and_annotated_tags(tmp_path: Path, annotated: bool) -> None:
    source = _source(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.invalid"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=source, check=True)
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=source, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, check=True, capture_output=True, text=True
    ).stdout.strip()
    tag_command = ["git", "tag"]
    if annotated:
        tag_command.extend(["-a", "-m", "release"])
    subprocess.run([*tag_command, "v1.2.3"], cwd=source, check=True)

    artifact, _, _ = build_release(
        source_root=source,
        output_dir=tmp_path / "dist",
        private_key=_private_key(tmp_path),
        key_id="release-2026",
        artifact_uri="https://example.invalid/releases/edgewatch.tar.gz",
        version="1.2.3",
        git_tag="v1.2.3",
        commit_sha=commit,
    )
    assert artifact.is_file()


def test_git_source_rejects_tag_that_does_not_point_to_head(tmp_path: Path) -> None:
    source = _source(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.invalid"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=source, check=True)
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(["git", "commit", "-qm", "tagged"], cwd=source, check=True)
    subprocess.run(["git", "tag", "v1.2.3"], cwd=source, check=True)
    tagged_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, check=True, capture_output=True, text=True
    ).stdout.strip()
    (source / "agent" / "edgewatch_agent.py").write_text("print('new head')\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(["git", "commit", "-qm", "head"], cwd=source, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, check=True, capture_output=True, text=True
    ).stdout.strip()

    with pytest.raises(ValueError, match="git_tag does not resolve"):
        build_release(
            source_root=source,
            output_dir=tmp_path / "dist",
            private_key=_private_key(tmp_path),
            key_id="release-2026",
            artifact_uri="https://example.invalid/releases/edgewatch.tar.gz",
            version="1.2.3",
            git_tag="v1.2.3",
            commit_sha=head,
        )

    subprocess.run(["git", "tag", "-f", "v1.2.3", head], cwd=source, check=True, capture_output=True)
    with pytest.raises(ValueError, match="commit_sha does not match"):
        build_release(
            source_root=source,
            output_dir=tmp_path / "commit-mismatch",
            private_key=_private_key(tmp_path),
            key_id="release-2026",
            artifact_uri="https://example.invalid/releases/edgewatch.tar.gz",
            version="1.2.3",
            git_tag="v1.2.3",
            commit_sha=tagged_commit,
        )
