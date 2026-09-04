from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from .litert import LiteRtClassifier

_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_VERSION = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)\Z")
_REQUIRED_FILE_ROLES = frozenset(
    {
        "vision_model",
        "audio_model",
        "labels",
        "preprocessing",
        "thresholds",
        "known_answer",
    }
)
_MODEL_ROLES = frozenset({"vision_model", "audio_model"})
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "version",
        "signature_key_id",
        "compatibility",
        "files",
        "signature",
    }
)


class ModelBundleError(RuntimeError):
    """A signed model bundle failed closed validation."""


class ModelActivationError(ModelBundleError):
    """A staged model bundle failed known-answer/readiness activation."""


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise ModelBundleError("model manifest is not canonical JSON") from exc


def canonical_model_manifest_bytes(payload: Mapping[str, Any]) -> bytes:
    unsigned = dict(payload)
    unsigned.pop("signature", None)
    return _canonical_json(unsigned)


def _safe_identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise ModelBundleError(f"{field} must be a safe identifier")
    return value


def _safe_relative_path(value: object, *, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or len(value) > 255:
        raise ModelBundleError(f"{field} must be a safe relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ModelBundleError(f"{field} must be a safe relative POSIX path")
    return path


def _semantic_version(value: object, *, field: str) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise ModelBundleError(f"{field} must be MAJOR.MINOR.PATCH")
    match = _VERSION.fullmatch(value)
    if match is None:
        raise ModelBundleError(f"{field} must be MAJOR.MINOR.PATCH")
    return tuple(int(item) for item in match.groups())  # type: ignore[return-value]


def _pairs_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ModelBundleError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ModelBundleError(f"invalid JSON numeric constant: {value}")


def _load_json_bytes(payload: bytes, *, label: str) -> object:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_pairs_without_duplicates,
            parse_constant=_reject_json_constant,
        )
    except ModelBundleError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelBundleError(f"{label} is not valid JSON") from exc


def _read_regular_file(path: Path, *, maximum_bytes: int, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ModelBundleError(f"{label} cannot be opened safely") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ModelBundleError(f"{label} must be a regular file")
        if metadata.st_size <= 0 or metadata.st_size > maximum_bytes:
            raise ModelBundleError(f"{label} size is outside the allowed range")
        payload = bytearray()
        while len(payload) <= maximum_bytes:
            chunk = os.read(descriptor, min(1024 * 1024, maximum_bytes + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
    finally:
        os.close(descriptor)
    if len(payload) > maximum_bytes:
        raise ModelBundleError(f"{label} exceeds the size limit")
    return bytes(payload)


def _write_fsync(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_json(payload))
            handle.write(b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _read_private_json(path: Path, *, label: str) -> dict[str, Any] | None:
    if not path.exists() and not path.is_symlink():
        return None
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ModelActivationError(f"{label} must be a regular file")
        if stat.S_IMODE(metadata.st_mode) & (stat.S_IRWXG | stat.S_IRWXO):
            raise ModelActivationError(f"{label} must have mode 0600 or stricter")
        if not 0 < metadata.st_size <= 64 * 1024:
            raise ModelActivationError(f"{label} size is outside the allowed range")
        value = _load_json_bytes(path.read_bytes(), label=label)
    except ModelBundleError:
        raise
    except OSError as exc:
        raise ModelActivationError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ModelActivationError(f"{label} root must be an object")
    return value


@dataclass(frozen=True)
class ModelBundleFile:
    path: PurePosixPath
    sha256: str
    size: int


@dataclass(frozen=True)
class ModelBundleManifest:
    version: str
    signature_key_id: str
    hardware_models: tuple[str, ...]
    minimum_litert_version: str
    files: dict[str, ModelBundleFile]
    signature: bytes
    raw_payload: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ModelBundleManifest:
        unknown = set(payload) - _MANIFEST_FIELDS
        missing = _MANIFEST_FIELDS - set(payload)
        if unknown:
            raise ModelBundleError(f"unknown model manifest fields: {', '.join(sorted(unknown))}")
        if missing:
            raise ModelBundleError(f"missing model manifest fields: {', '.join(sorted(missing))}")
        if payload.get("schema_version") != 1:
            raise ModelBundleError("model manifest schema_version must be 1")
        version = _safe_identifier(payload.get("version"), field="version")
        key_id = _safe_identifier(payload.get("signature_key_id"), field="signature_key_id")

        compatibility = payload.get("compatibility")
        if not isinstance(compatibility, Mapping) or set(compatibility) != {
            "schema_version",
            "hardware_models",
            "minimum_litert_version",
        }:
            raise ModelBundleError("compatibility must contain exactly the v1 fields")
        if compatibility.get("schema_version") != 1:
            raise ModelBundleError("compatibility.schema_version must be 1")
        hardware_models_raw = compatibility.get("hardware_models")
        if not isinstance(hardware_models_raw, list) or not hardware_models_raw:
            raise ModelBundleError("compatibility.hardware_models must be non-empty")
        hardware_models = tuple(
            _safe_identifier(item, field="compatibility.hardware_models") for item in hardware_models_raw
        )
        if len(hardware_models) > 16 or len(set(hardware_models)) != len(hardware_models):
            raise ModelBundleError("compatibility.hardware_models must be unique and bounded")
        minimum_litert = compatibility.get("minimum_litert_version")
        _semantic_version(minimum_litert, field="compatibility.minimum_litert_version")
        assert isinstance(minimum_litert, str)

        files_raw = payload.get("files")
        if not isinstance(files_raw, Mapping) or set(files_raw) != _REQUIRED_FILE_ROLES:
            raise ModelBundleError("files must contain exactly the six required model bundle roles")
        files: dict[str, ModelBundleFile] = {}
        used_paths: set[PurePosixPath] = set()
        for role, descriptor in files_raw.items():
            if not isinstance(role, str) or not isinstance(descriptor, Mapping):
                raise ModelBundleError("model file entries are invalid")
            if set(descriptor) != {"path", "sha256", "size"}:
                raise ModelBundleError(f"files.{role} must contain exactly path, sha256, and size")
            relative = _safe_relative_path(descriptor.get("path"), field=f"files.{role}.path")
            if relative in used_paths:
                raise ModelBundleError("model manifest file paths must be unique")
            used_paths.add(relative)
            digest = descriptor.get("sha256")
            if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
                raise ModelBundleError(f"files.{role}.sha256 must be lowercase SHA-256")
            size = descriptor.get("size")
            if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
                raise ModelBundleError(f"files.{role}.size must be a positive integer")
            if role in _MODEL_ROLES and relative.suffix != ".tflite":
                raise ModelBundleError(f"files.{role}.path must end in .tflite")
            if role not in _MODEL_ROLES and relative.suffix != ".json":
                raise ModelBundleError(f"files.{role}.path must end in .json")
            files[role] = ModelBundleFile(path=relative, sha256=digest, size=size)

        signature_raw = payload.get("signature")
        if not isinstance(signature_raw, str):
            raise ModelBundleError("signature must be base64 text")
        try:
            signature = base64.b64decode(signature_raw, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ModelBundleError("signature must be valid base64") from exc
        if not signature or len(signature) > 16 * 1024:
            raise ModelBundleError("signature size is outside the allowed range")
        return cls(
            version=version,
            signature_key_id=key_id,
            hardware_models=hardware_models,
            minimum_litert_version=minimum_litert,
            files=files,
            signature=signature,
            raw_payload=dict(payload),
        )

    @property
    def identity(self) -> str:
        return hashlib.sha256(_canonical_json(self.raw_payload)).hexdigest()


@dataclass(frozen=True)
class InstalledModelBundle:
    root: Path
    manifest: ModelBundleManifest
    labels: dict[str, tuple[str, ...]]
    preprocessing: dict[str, dict[str, Any]]
    thresholds: dict[str, float | int]
    known_answer_cases: tuple[dict[str, Any], ...]

    def role_path(self, role: str) -> Path:
        try:
            descriptor = self.manifest.files[role]
        except KeyError as exc:
            raise ModelBundleError(f"unknown model bundle role: {role}") from exc
        return self.root.joinpath(*descriptor.path.parts)


@dataclass(frozen=True)
class ModelActivationResult:
    version: str
    manifest_identity: str
    previous_target: str | None
    current_target: str
    rolled_back: bool = False


SignatureVerifier = Callable[[Path, bytes, bytes], bool]
KnownAnswerRunner = Callable[[InstalledModelBundle], bool]
ReadinessProbe = Callable[[InstalledModelBundle], bool]


def validate_known_answer_cases(
    bundle: InstalledModelBundle,
    classifiers: Mapping[str, Any],
) -> bool:
    if set(classifiers) != {"vision", "audio"}:
        raise ModelBundleError("known-answer classifiers must contain vision and audio")
    for case in bundle.known_answer_cases:
        model_name = str(case["model"])
        scores = classifiers[model_name].predict_quantized(case["input"])
        expected = str(case["expected_label"])
        predicted = max(scores, key=scores.__getitem__)
        if predicted != expected or scores[expected] < float(case["minimum_score"]):
            return False
    return True


def _openssl_signature_verifier(public_key: Path, payload: bytes, signature: bytes) -> bool:
    openssl = shutil.which("openssl")
    if openssl is None:
        raise ModelBundleError("openssl is required for model signature verification")
    with tempfile.NamedTemporaryFile(prefix="edgewatch-model-manifest-") as payload_file:
        with tempfile.NamedTemporaryFile(prefix="edgewatch-model-signature-") as signature_file:
            payload_file.write(payload)
            payload_file.flush()
            signature_file.write(signature)
            signature_file.flush()
            try:
                completed = subprocess.run(
                    [
                        openssl,
                        "dgst",
                        "-sha256",
                        "-verify",
                        str(public_key),
                        "-signature",
                        signature_file.name,
                        payload_file.name,
                    ],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10.0,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ModelBundleError("model signature verification could not run") from exc
    return completed.returncode == 0


class ModelBundleManager:
    """Stages and atomically activates immutable, signed model directories."""

    def __init__(
        self,
        *,
        releases_root: str | Path,
        current_symlink: str | Path,
        keyring_dir: str | Path,
        hardware_model: str,
        litert_version: str = "2.1.6",
        max_bundle_bytes: int = 128 * 1024 * 1024,
        signature_verifier: SignatureVerifier = _openssl_signature_verifier,
        activation_journal_path: str | Path | None = None,
        activation_state_path: str | Path | None = None,
    ) -> None:
        if max_bundle_bytes < 1024:
            raise ValueError("max_bundle_bytes must be at least 1024")
        self.releases_root = Path(releases_root)
        self.current_symlink = Path(current_symlink)
        self.keyring_dir = Path(keyring_dir)
        self.hardware_model = _safe_identifier(hardware_model, field="hardware_model")
        _semantic_version(litert_version, field="litert_version")
        self.litert_version = litert_version
        self.max_bundle_bytes = int(max_bundle_bytes)
        self.signature_verifier = signature_verifier
        self.activation_journal_path = Path(
            activation_journal_path
            if activation_journal_path is not None
            else self.current_symlink.parent / ".model-activation-journal.json"
        )
        self.activation_state_path = Path(
            activation_state_path
            if activation_state_path is not None
            else self.current_symlink.parent / ".model-activation-state.json"
        )
        if (
            len(
                {
                    self.current_symlink.absolute(),
                    self.activation_journal_path.absolute(),
                    self.activation_state_path.absolute(),
                }
            )
            != 3
        ):
            raise ValueError("model activation paths must be distinct")

    def stage(self, source_dir: str | Path) -> InstalledModelBundle:
        source = Path(source_dir)
        if source.is_symlink() or not source.is_dir():
            raise ModelBundleError("model bundle source must be a real directory")
        manifest_payload = _read_regular_file(
            source / "manifest.json",
            maximum_bytes=1024 * 1024,
            label="model manifest",
        )
        raw_manifest = _load_json_bytes(manifest_payload, label="model manifest")
        if not isinstance(raw_manifest, Mapping):
            raise ModelBundleError("model manifest root must be an object")
        manifest = ModelBundleManifest.from_payload(raw_manifest)
        self._validate_source_inventory(source, manifest)

        self.releases_root.mkdir(parents=True, exist_ok=True)
        stage_root = Path(tempfile.mkdtemp(prefix=".model-stage-", dir=self.releases_root))
        try:
            _write_fsync(stage_root / "manifest.json", manifest_payload)
            total = len(manifest_payload)
            for role in sorted(manifest.files):
                descriptor = manifest.files[role]
                if descriptor.size > self.max_bundle_bytes - total:
                    raise ModelBundleError("model bundle exceeds the configured size limit")
                source_path = source.joinpath(*descriptor.path.parts)
                payload = _read_regular_file(
                    source_path,
                    maximum_bytes=descriptor.size,
                    label=f"model bundle file {role}",
                )
                if len(payload) != descriptor.size:
                    raise ModelBundleError(f"model bundle file {role} size does not match manifest")
                if hashlib.sha256(payload).hexdigest() != descriptor.sha256:
                    raise ModelBundleError(f"model bundle file {role} digest does not match manifest")
                _write_fsync(stage_root.joinpath(*descriptor.path.parts), payload)
                total += len(payload)
            staged = self.validate(stage_root)
            target = self._release_path(manifest.version)
            if target.exists():
                existing = self.validate(target)
                if existing.manifest.identity != staged.manifest.identity:
                    raise ModelBundleError("model version already exists with different content")
                self._seal_tree(target)
                self._fsync_tree(target)
                return self.validate(target)
            self._seal_tree(stage_root)
            self._fsync_tree(stage_root)
            os.replace(stage_root, target)
            _fsync_directory(self.releases_root)
            return self.validate(target)
        finally:
            if stage_root.exists():
                self._make_tree_owner_writable(stage_root)
                shutil.rmtree(stage_root)

    def validate(self, root: str | Path) -> InstalledModelBundle:
        bundle_root = Path(root)
        if bundle_root.is_symlink() or not bundle_root.is_dir():
            raise ModelBundleError("installed model bundle must be a real directory")
        manifest_bytes = _read_regular_file(
            bundle_root / "manifest.json",
            maximum_bytes=1024 * 1024,
            label="model manifest",
        )
        raw_manifest = _load_json_bytes(manifest_bytes, label="model manifest")
        if not isinstance(raw_manifest, Mapping):
            raise ModelBundleError("model manifest root must be an object")
        manifest = ModelBundleManifest.from_payload(raw_manifest)
        self._validate_compatibility(manifest)
        self._validate_source_inventory(bundle_root, manifest)
        self._verify_signature(manifest)

        total = len(manifest_bytes)
        for role, descriptor in manifest.files.items():
            if descriptor.size > self.max_bundle_bytes - total:
                raise ModelBundleError("model bundle exceeds the configured size limit")
            payload = _read_regular_file(
                bundle_root.joinpath(*descriptor.path.parts),
                maximum_bytes=descriptor.size,
                label=f"model bundle file {role}",
            )
            if len(payload) != descriptor.size:
                raise ModelBundleError(f"model bundle file {role} size does not match manifest")
            if hashlib.sha256(payload).hexdigest() != descriptor.sha256:
                raise ModelBundleError(f"model bundle file {role} digest does not match manifest")
            total += len(payload)

        labels = self._validate_labels(bundle_root, manifest)
        preprocessing = self._validate_preprocessing(bundle_root, manifest)
        thresholds = self._validate_thresholds(bundle_root, manifest)
        cases = self._validate_known_answers(bundle_root, manifest, labels)
        return InstalledModelBundle(
            root=bundle_root.resolve(),
            manifest=manifest,
            labels=labels,
            preprocessing=preprocessing,
            thresholds=thresholds,
            known_answer_cases=cases,
        )

    def activate(
        self,
        version: str,
        *,
        known_answer_runner: KnownAnswerRunner | None = None,
        readiness_probe: ReadinessProbe | None = None,
    ) -> ModelActivationResult:
        self.recover_interrupted_activation()
        target = self._release_path(_safe_identifier(version, field="version"))
        bundle = self.validate(target)
        runner = known_answer_runner or self.run_known_answers
        try:
            known_answers_ok = runner(bundle)
        except Exception as exc:
            raise ModelActivationError("model known-answer validation failed") from exc
        if not known_answers_ok:
            raise ModelActivationError("model known-answer validation failed")

        previous = self._current_target()
        journal = self._activation_journal(
            phase="prepared",
            bundle=bundle,
            previous=previous,
        )
        self._write_activation_journal(journal)
        self._atomic_symlink(bundle.root)
        journal["phase"] = "switched"
        self._write_activation_journal(journal)
        try:
            if readiness_probe is not None and not readiness_probe(bundle):
                raise ModelActivationError("model readiness probe failed")
        except Exception as exc:
            self._rollback_activation(journal)
            if isinstance(exc, ModelActivationError):
                raise
            raise ModelActivationError("model readiness probe failed") from exc
        journal["phase"] = "verified"
        self._write_activation_journal(journal)
        self._write_activation_state(bundle)
        self._clear_activation_journal()
        return ModelActivationResult(
            version=bundle.manifest.version,
            manifest_identity=bundle.manifest.identity,
            previous_target=str(previous) if previous is not None else None,
            current_target=str(bundle.root),
        )

    def run_known_answers(self, bundle: InstalledModelBundle) -> bool:
        classifiers = {
            "vision": LiteRtClassifier.load(
                bundle.role_path("vision_model"),
                labels=bundle.labels["vision"],
            ),
            "audio": LiteRtClassifier.load(
                bundle.role_path("audio_model"),
                labels=bundle.labels["audio"],
            ),
        }
        return validate_known_answer_cases(bundle, classifiers)

    def load_active(self) -> InstalledModelBundle:
        self.recover_interrupted_activation()
        target = self._current_target()
        if target is None:
            raise ModelBundleError("no active model bundle is installed")
        return self.validate(target)

    def recover_interrupted_activation(self) -> bool:
        """Resolve a durable activation intent before any model can be used."""

        journal = _read_private_json(
            self.activation_journal_path,
            label="model activation journal",
        )
        if journal is None:
            return False
        normalized = self._validate_activation_journal(journal)
        target = Path(normalized["target"])
        current = self._current_target()
        if normalized["phase"] == "verified" and current == target:
            state = self._read_activation_state()
            if (
                state is not None
                and state["target"] == str(target)
                and state["manifest_identity"] == normalized["manifest_identity"]
                and state["version"] == normalized["version"]
            ):
                self._clear_activation_journal()
                return True
        self._rollback_activation(normalized)
        return True

    def _activation_journal(
        self,
        *,
        phase: str,
        bundle: InstalledModelBundle,
        previous: Path | None,
    ) -> dict[str, Any]:
        return {
            "manifest_identity": bundle.manifest.identity,
            "phase": phase,
            "previous_target": str(previous) if previous is not None else None,
            "schema_version": 1,
            "target": str(bundle.root),
            "version": bundle.manifest.version,
        }

    def _validate_activation_journal(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if set(payload) != {
            "manifest_identity",
            "phase",
            "previous_target",
            "schema_version",
            "target",
            "version",
        }:
            raise ModelActivationError("model activation journal schema is invalid")
        if payload.get("schema_version") != 1 or payload.get("phase") not in {
            "prepared",
            "switched",
            "verified",
        }:
            raise ModelActivationError("model activation journal state is invalid")
        version = _safe_identifier(payload.get("version"), field="version")
        identity = payload.get("manifest_identity")
        if not isinstance(identity, str) or _SHA256.fullmatch(identity) is None:
            raise ModelActivationError("model activation journal identity is invalid")
        target = self._journal_release_path(payload.get("target"), field="target")
        if target.name != version:
            raise ModelActivationError("model activation journal target does not match its version")
        previous_raw = payload.get("previous_target")
        previous = (
            None
            if previous_raw is None
            else self._journal_release_path(previous_raw, field="previous_target")
        )
        return {
            "manifest_identity": identity,
            "phase": str(payload["phase"]),
            "previous_target": str(previous) if previous is not None else None,
            "schema_version": 1,
            "target": str(target),
            "version": version,
        }

    def _journal_release_path(self, value: object, *, field: str) -> Path:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ModelActivationError(f"model activation journal {field} is invalid")
        candidate = Path(value)
        root = self.releases_root.resolve()
        if not candidate.is_absolute() or candidate.resolve(strict=False).parent != root:
            raise ModelActivationError(f"model activation journal {field} is outside releases root")
        if candidate.is_symlink():
            raise ModelActivationError(f"model activation journal {field} must not be a symlink")
        return candidate.resolve(strict=False)

    def _write_activation_journal(self, payload: Mapping[str, Any]) -> None:
        _write_atomic_json(self.activation_journal_path, payload)

    def _clear_activation_journal(self) -> None:
        try:
            self.activation_journal_path.unlink()
        except FileNotFoundError:
            return
        _fsync_directory(self.activation_journal_path.parent)

    def _write_activation_state(self, bundle: InstalledModelBundle) -> None:
        _write_atomic_json(
            self.activation_state_path,
            {
                "manifest_identity": bundle.manifest.identity,
                "schema_version": 1,
                "target": str(bundle.root),
                "version": bundle.manifest.version,
            },
        )

    def _read_activation_state(self) -> dict[str, Any] | None:
        state = _read_private_json(
            self.activation_state_path,
            label="model activation state",
        )
        if state is None:
            return None
        if set(state) != {"manifest_identity", "schema_version", "target", "version"}:
            raise ModelActivationError("model activation state schema is invalid")
        if state.get("schema_version") != 1:
            raise ModelActivationError("model activation state version is invalid")
        version = _safe_identifier(state.get("version"), field="version")
        identity = state.get("manifest_identity")
        if not isinstance(identity, str) or _SHA256.fullmatch(identity) is None:
            raise ModelActivationError("model activation state identity is invalid")
        target = self._journal_release_path(state.get("target"), field="state.target")
        if target.name != version:
            raise ModelActivationError("model activation state target does not match its version")
        return {
            "manifest_identity": identity,
            "schema_version": 1,
            "target": str(target),
            "version": version,
        }

    def _rollback_activation(self, journal: Mapping[str, Any]) -> None:
        normalized = self._validate_activation_journal(journal)
        previous_raw = normalized["previous_target"]
        previous = Path(previous_raw) if isinstance(previous_raw, str) else None
        self._restore_symlink(previous)
        if previous is None:
            try:
                self.activation_state_path.unlink()
            except FileNotFoundError:
                pass
            else:
                _fsync_directory(self.activation_state_path.parent)
        else:
            self._write_activation_state(self.validate(previous))
        self._clear_activation_journal()

    def _validate_compatibility(self, manifest: ModelBundleManifest) -> None:
        if self.hardware_model not in manifest.hardware_models:
            raise ModelBundleError("model bundle is incompatible with this hardware")
        if _semantic_version(self.litert_version, field="litert_version") < _semantic_version(
            manifest.minimum_litert_version,
            field="compatibility.minimum_litert_version",
        ):
            raise ModelBundleError("installed LiteRT version is below the model minimum")

    def _verify_signature(self, manifest: ModelBundleManifest) -> None:
        public_key = self.keyring_dir / f"{manifest.signature_key_id}.pem"
        try:
            metadata = public_key.stat()
        except OSError as exc:
            raise ModelBundleError("model signature key is not installed") from exc
        if public_key.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise ModelBundleError("model signature key is not a regular file")
        if stat.S_IMODE(metadata.st_mode) & 0o022:
            raise ModelBundleError("model signature key must not be group/world writable")
        try:
            valid = self.signature_verifier(
                public_key,
                canonical_model_manifest_bytes(manifest.raw_payload),
                manifest.signature,
            )
        except ModelBundleError:
            raise
        except Exception as exc:
            raise ModelBundleError("model signature verification could not run") from exc
        if not valid:
            raise ModelBundleError("model manifest signature verification failed")

    def _validate_source_inventory(self, root: Path, manifest: ModelBundleManifest) -> None:
        expected = {PurePosixPath("manifest.json"), *(item.path for item in manifest.files.values())}
        expected_directories: set[PurePosixPath] = set()
        for file_path in expected:
            parent = file_path.parent
            while parent != PurePosixPath("."):
                expected_directories.add(parent)
                parent = parent.parent
        found: set[PurePosixPath] = set()
        found_directories: set[PurePosixPath] = set()
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ModelBundleError("model bundle must not contain symbolic links")
            if path.is_file():
                found.add(PurePosixPath(path.relative_to(root).as_posix()))
            elif path.is_dir():
                found_directories.add(PurePosixPath(path.relative_to(root).as_posix()))
            else:
                raise ModelBundleError("model bundle contains an unsupported filesystem entry")
        if found != expected or found_directories != expected_directories:
            raise ModelBundleError("model bundle file inventory does not match its manifest")

    def _validate_labels(
        self,
        root: Path,
        manifest: ModelBundleManifest,
    ) -> dict[str, tuple[str, ...]]:
        raw = self._load_role_json(root, manifest, "labels")
        if not isinstance(raw, Mapping) or set(raw) != {"schema_version", "vision", "audio"}:
            raise ModelBundleError("labels must contain exactly schema_version, vision, and audio")
        if raw.get("schema_version") != 1:
            raise ModelBundleError("labels.schema_version must be 1")
        labels: dict[str, tuple[str, ...]] = {}
        expected = {
            "vision": {"running", "stopped", "fault", "unknown"},
            "audio": {"normal", "anomaly"},
        }
        for model_name, required in expected.items():
            values = raw.get(model_name)
            if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
                raise ModelBundleError(f"labels.{model_name} must be a string list")
            normalized = tuple(str(item) for item in values)
            if len(set(normalized)) != len(normalized) or set(normalized) != required:
                raise ModelBundleError(f"labels.{model_name} does not match the v1 label contract")
            labels[model_name] = normalized
        return labels

    def _validate_preprocessing(
        self,
        root: Path,
        manifest: ModelBundleManifest,
    ) -> dict[str, dict[str, Any]]:
        raw = self._load_role_json(root, manifest, "preprocessing")
        if not isinstance(raw, Mapping) or set(raw) != {"schema_version", "vision", "audio"}:
            raise ModelBundleError("preprocessing must contain exactly schema_version, vision, and audio")
        if raw.get("schema_version") != 1:
            raise ModelBundleError("preprocessing.schema_version must be 1")
        vision = raw.get("vision")
        audio = raw.get("audio")
        if not isinstance(vision, Mapping) or not isinstance(audio, Mapping):
            raise ModelBundleError("preprocessing vision/audio entries must be objects")
        vision_fields = {
            "schema_version",
            "layout",
            "width",
            "height",
            "channels",
            "resize_filter",
            "value_scale",
            "value_offset",
        }
        if set(vision) != vision_fields or vision.get("schema_version") != 1:
            raise ModelBundleError("preprocessing.vision does not match the closed v1 schema")
        if vision.get("layout") != "nhwc":
            raise ModelBundleError("preprocessing.vision.layout must be nhwc")
        width = self._bounded_int(vision.get("width"), field="vision.width", minimum=16, maximum=2048)
        height = self._bounded_int(vision.get("height"), field="vision.height", minimum=16, maximum=2048)
        channels = self._bounded_int(vision.get("channels"), field="vision.channels", minimum=1, maximum=3)
        if channels not in {1, 3}:
            raise ModelBundleError("preprocessing.vision.channels must be 1 or 3")
        if width * height * channels > 1_000_000:
            raise ModelBundleError("preprocessing.vision tensor exceeds the Pi Zero resource limit")
        resize_filter = vision.get("resize_filter")
        if resize_filter not in {"bilinear", "area"}:
            raise ModelBundleError("preprocessing.vision.resize_filter must be bilinear or area")
        value_scale = self._bounded_float(
            vision.get("value_scale"), field="vision.value_scale", minimum=0.0000001, maximum=10.0
        )
        value_offset = self._bounded_float(
            vision.get("value_offset"), field="vision.value_offset", minimum=-10.0, maximum=10.0
        )

        audio_fields = {
            "schema_version",
            "layout",
            "feature",
            "sample_rate_hz",
            "sample_count",
            "window_samples",
            "hop_samples",
            "fft_size",
            "mel_bins",
            "lower_hz",
            "upper_hz",
            "log_floor",
            "window",
            "log_base",
        }
        if set(audio) != audio_fields or audio.get("schema_version") != 1:
            raise ModelBundleError("preprocessing.audio does not match the closed v1 schema")
        if audio.get("feature") != "log_mel":
            raise ModelBundleError("preprocessing.audio.feature must be log_mel")
        if audio.get("layout") != "nhwc":
            raise ModelBundleError("preprocessing.audio.layout must be nhwc")
        if audio.get("window") != "hann" or audio.get("log_base") != "e":
            raise ModelBundleError("preprocessing.audio requires hann window and natural log")
        sample_rate = self._bounded_int(
            audio.get("sample_rate_hz"), field="audio.sample_rate_hz", minimum=8000, maximum=48000
        )
        sample_count = self._bounded_int(
            audio.get("sample_count"),
            field="audio.sample_count",
            minimum=800,
            maximum=sample_rate * 5,
        )
        window_samples = self._bounded_int(
            audio.get("window_samples"),
            field="audio.window_samples",
            minimum=64,
            maximum=sample_count,
        )
        hop_samples = self._bounded_int(
            audio.get("hop_samples"),
            field="audio.hop_samples",
            minimum=1,
            maximum=window_samples,
        )
        fft_size = self._bounded_int(
            audio.get("fft_size"), field="audio.fft_size", minimum=window_samples, maximum=2048
        )
        if fft_size & (fft_size - 1):
            raise ModelBundleError("preprocessing.audio.fft_size must be a power of two")
        mel_bins = self._bounded_int(audio.get("mel_bins"), field="audio.mel_bins", minimum=8, maximum=256)
        lower_hz = self._bounded_float(
            audio.get("lower_hz"), field="audio.lower_hz", minimum=0.0, maximum=sample_rate / 2
        )
        upper_hz = self._bounded_float(
            audio.get("upper_hz"), field="audio.upper_hz", minimum=0.0, maximum=sample_rate / 2
        )
        if upper_hz <= lower_hz:
            raise ModelBundleError("preprocessing.audio.upper_hz must exceed lower_hz")
        log_floor = self._bounded_float(
            audio.get("log_floor"), field="audio.log_floor", minimum=1e-12, maximum=1.0
        )
        frame_count = 1 + (sample_count - window_samples) // hop_samples
        if frame_count * mel_bins > 1_000_000:
            raise ModelBundleError("preprocessing.audio tensor exceeds the Pi Zero resource limit")
        if frame_count * fft_size * int(math.log2(fft_size)) > 5_000_000:
            raise ModelBundleError("preprocessing.audio FFT workload exceeds the Pi Zero resource limit")
        return {
            "vision": {
                "layout": "nhwc",
                "width": width,
                "height": height,
                "channels": channels,
                "resize_filter": str(resize_filter),
                "value_scale": value_scale,
                "value_offset": value_offset,
            },
            "audio": {
                "layout": "nhwc",
                "feature": "log_mel",
                "sample_rate_hz": sample_rate,
                "sample_count": sample_count,
                "window_samples": window_samples,
                "hop_samples": hop_samples,
                "fft_size": fft_size,
                "mel_bins": mel_bins,
                "lower_hz": lower_hz,
                "upper_hz": upper_hz,
                "log_floor": log_floor,
                "window": "hann",
                "log_base": "e",
            },
        }

    @staticmethod
    def _bounded_int(value: object, *, field: str, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ModelBundleError(f"preprocessing.{field} must be within {minimum}..{maximum}")
        return value

    @staticmethod
    def _bounded_float(
        value: object,
        *,
        field: str,
        minimum: float,
        maximum: float,
    ) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ModelBundleError(f"preprocessing.{field} must be numeric")
        normalized = float(value)
        if not math.isfinite(normalized) or not minimum <= normalized <= maximum:
            raise ModelBundleError(f"preprocessing.{field} must be within {minimum}..{maximum}")
        return normalized

    def _validate_thresholds(
        self,
        root: Path,
        manifest: ModelBundleManifest,
    ) -> dict[str, float | int]:
        raw = self._load_role_json(root, manifest, "thresholds")
        fields = {
            "schema_version",
            "minimum_state_confidence",
            "minimum_state_margin",
            "fault_audio_threshold",
            "fault_visual_threshold",
            "minimum_alert_confidence",
            "consecutive_required",
        }
        if not isinstance(raw, Mapping) or set(raw) != fields or raw.get("schema_version") != 1:
            raise ModelBundleError("thresholds does not match the closed v1 schema")
        result: dict[str, float | int] = {}
        for field in fields - {"schema_version", "consecutive_required"}:
            value = raw.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ModelBundleError(f"thresholds.{field} must be numeric")
            normalized = float(value)
            if not 0.0 <= normalized <= 1.0:
                raise ModelBundleError(f"thresholds.{field} must be within 0..1")
            result[field] = normalized
        repeated = raw.get("consecutive_required")
        if isinstance(repeated, bool) or not isinstance(repeated, int) or not 2 <= repeated <= 20:
            raise ModelBundleError("thresholds.consecutive_required must be within 2..20")
        result["consecutive_required"] = repeated
        return result

    def _validate_known_answers(
        self,
        root: Path,
        manifest: ModelBundleManifest,
        labels: Mapping[str, tuple[str, ...]],
    ) -> tuple[dict[str, Any], ...]:
        raw = self._load_role_json(root, manifest, "known_answer")
        if not isinstance(raw, Mapping) or set(raw) != {"schema_version", "cases"}:
            raise ModelBundleError("known_answer must contain exactly schema_version and cases")
        if raw.get("schema_version") != 1:
            raise ModelBundleError("known_answer.schema_version must be 1")
        cases_raw = raw.get("cases")
        if not isinstance(cases_raw, list) or not 2 <= len(cases_raw) <= 16:
            raise ModelBundleError("known_answer.cases must contain 2..16 cases")
        cases: list[dict[str, Any]] = []
        seen_models: set[str] = set()
        for case in cases_raw:
            if not isinstance(case, Mapping) or set(case) != {
                "model",
                "input",
                "expected_label",
                "minimum_score",
            }:
                raise ModelBundleError("known-answer case does not match the closed v1 schema")
            model = case.get("model")
            if model not in {"vision", "audio"}:
                raise ModelBundleError("known-answer model must be vision or audio")
            assert isinstance(model, str)
            input_values = case.get("input")
            if (
                not isinstance(input_values, list)
                or not input_values
                or len(input_values) > 1_000_000
                or any(
                    isinstance(item, bool) or not isinstance(item, int) or not -128 <= item <= 127
                    for item in input_values
                )
            ):
                raise ModelBundleError("known-answer input must be a bounded signed int8 vector")
            expected_label = case.get("expected_label")
            if expected_label not in labels[model]:
                raise ModelBundleError("known-answer expected_label is not in the model labels")
            minimum_score = case.get("minimum_score")
            if (
                isinstance(minimum_score, bool)
                or not isinstance(minimum_score, (int, float))
                or not 0.0 <= float(minimum_score) <= 1.0
            ):
                raise ModelBundleError("known-answer minimum_score must be within 0..1")
            cases.append(
                {
                    "model": model,
                    "input": tuple(input_values),
                    "expected_label": str(expected_label),
                    "minimum_score": float(minimum_score),
                }
            )
            seen_models.add(model)
        if seen_models != {"vision", "audio"}:
            raise ModelBundleError("known-answer cases must cover both vision and audio models")
        return tuple(cases)

    def _load_role_json(
        self,
        root: Path,
        manifest: ModelBundleManifest,
        role: str,
    ) -> object:
        descriptor = manifest.files[role]
        payload = _read_regular_file(
            root.joinpath(*descriptor.path.parts),
            maximum_bytes=descriptor.size,
            label=f"model bundle file {role}",
        )
        return _load_json_bytes(payload, label=role)

    def _release_path(self, version: str) -> Path:
        root = self.releases_root.resolve()
        candidate = root / version
        if candidate.is_symlink() or candidate.resolve(strict=False).parent != root:
            raise ModelBundleError("model version resolves outside the releases root")
        return candidate

    def _current_target(self) -> Path | None:
        if not self.current_symlink.exists() and not self.current_symlink.is_symlink():
            return None
        if not self.current_symlink.is_symlink():
            raise ModelBundleError("active model path must be a symbolic link")
        target = self.current_symlink.resolve(strict=False)
        releases_root = self.releases_root.resolve()
        if target.parent != releases_root:
            raise ModelBundleError("active model target is outside the releases root")
        return target

    def _atomic_symlink(self, target: Path) -> None:
        self.current_symlink.parent.mkdir(parents=True, exist_ok=True)
        if self.current_symlink.exists() and not self.current_symlink.is_symlink():
            raise ModelBundleError("active model path must be a symbolic link")
        temporary = self.current_symlink.with_name(f".{self.current_symlink.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.symlink_to(target, target_is_directory=True)
            os.replace(temporary, self.current_symlink)
            _fsync_directory(self.current_symlink.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def _restore_symlink(self, previous: Path | None) -> None:
        if previous is not None:
            self._atomic_symlink(previous)
            return
        self.current_symlink.unlink(missing_ok=True)
        _fsync_directory(self.current_symlink.parent)

    @staticmethod
    def _seal_tree(root: Path) -> None:
        for path in root.rglob("*"):
            if path.is_file():
                path.chmod(0o444)
        directories = sorted(
            (path for path in root.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in directories:
            directory.chmod(0o555)
        root.chmod(0o555)

    @staticmethod
    def _make_tree_owner_writable(root: Path) -> None:
        root.chmod(0o700)
        for path in root.rglob("*"):
            if path.is_dir():
                path.chmod(0o700)
            elif path.is_file():
                path.chmod(0o600)

    @staticmethod
    def _fsync_tree(root: Path) -> None:
        directories = sorted(
            (path for path in root.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in directories:
            _fsync_directory(directory)
        _fsync_directory(root)
