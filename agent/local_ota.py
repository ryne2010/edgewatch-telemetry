from __future__ import annotations

import base64
import binascii
import datetime as dt
import hashlib
import ipaddress
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping


_UPDATE_TYPES = {"application_bundle", "asset_bundle", "system_image"}
_SIGNATURE_SCHEME = "openssl_rsa_sha256"
_OTA_SCHEMA_VERSION = 1
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_PYTHON_VERSION = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)\Z")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
_RUNTIME_DEPENDENCY_RELATIVE_PATH = Path("agent/requirements.txt")
_APPLY_JOURNAL_SCHEMA_VERSION = 1
_APPLY_JOURNAL_PHASES = {"prepared", "switched", "verified"}
_CAMERA_RUNTIME_PROFILE = "camera-satellite"
_CAMERA_CHECK_UNIT = "edgewatch-camera-satellite@check.service"
_CAMERA_READY_PATH = Path("/var/lib/edgewatch-camera-satellite/ready.json")
_CAMERA_USER = "edgewatch-camera"
_COMPATIBILITY_FIELDS = {
    "schema_version",
    "hardware_models",
    "release_channel",
    "minimum_python_version",
    "minimum_runtime_schema",
    "minimum_ota_schema",
    "requires_stable_power",
    "requires_apply_enabled",
    "minimum_free_bytes",
}


class OtaError(RuntimeError):
    """A fail-closed local OTA error safe to return through the typed helper."""

    retryable = False
    max_attempts = 1


class RetryableOtaError(OtaError):
    """A transient OTA failure that must not be committed to command ledgers."""

    retryable = True
    max_attempts = 3


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _gateway_cache_base_url(raw: str | None) -> str | None:
    value = (raw or "").strip().rstrip("/")
    if not value:
        return None
    parsed = urllib.parse.urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise OtaError("EDGEWATCH_OTA_GATEWAY_CACHE_URL must be a bare maintenance URL")
    try:
        address = ipaddress.ip_address(parsed.hostname)
        port = parsed.port
    except ValueError as exc:
        raise OtaError("EDGEWATCH_OTA_GATEWAY_CACHE_URL must use a private IP address") from exc
    if (
        address.version != 4
        or port is None
        or address.is_unspecified
        or address.is_multicast
        or address.is_loopback
        or address.is_link_local
        or not address.is_private
    ):
        raise OtaError("EDGEWATCH_OTA_GATEWAY_CACHE_URL must use a private IP address")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _url_origin(url: str) -> tuple[str, str, int | None]:
    parsed = urllib.parse.urlsplit(url)
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else None
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), port


class _OtaRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        source = _url_origin(req.full_url)
        target = _url_origin(newurl)
        if source[0] == "https" and target[0] != "https":
            raise urllib.error.URLError("HTTPS redirect downgrade is forbidden")
        if source != target:
            raise urllib.error.URLError("cross-origin redirect is forbidden")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OtaError(f"{field} must be a non-empty string")
    return value.strip()


def _safe_identifier(value: object, field: str) -> str:
    normalized = _nonempty_string(value, field)
    if normalized in {".", ".."} or _SAFE_IDENTIFIER.fullmatch(normalized) is None:
        raise OtaError(f"{field} must be a safe identifier")
    return normalized


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def canonical_manifest_bytes(payload: Mapping[str, Any]) -> bytes:
    """Return the exact security metadata bytes covered by the manifest signature."""

    unsigned = dict(payload)
    unsigned.pop("manifest_signature", None)
    return _canonical_json(unsigned)


def _validate_compatibility(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise OtaError("compatibility must be a mapping")
    unknown = set(value) - _COMPATIBILITY_FIELDS
    missing = _COMPATIBILITY_FIELDS - set(value)
    if unknown:
        raise OtaError(f"unknown compatibility fields: {', '.join(sorted(unknown))}")
    if missing:
        raise OtaError(f"missing compatibility fields: {', '.join(sorted(missing))}")
    if value.get("schema_version") != 1:
        raise OtaError("compatibility.schema_version must be 1")
    models = value.get("hardware_models")
    if (
        not isinstance(models, list)
        or not models
        or len(models) > 32
        or any(not isinstance(item, str) or _SAFE_IDENTIFIER.fullmatch(item) is None for item in models)
        or len(set(models)) != len(models)
    ):
        raise OtaError("compatibility.hardware_models must be a unique non-empty safe identifier list")
    channel = _safe_identifier(value.get("release_channel"), "compatibility.release_channel")
    minimum_python = _nonempty_string(
        value.get("minimum_python_version"), "compatibility.minimum_python_version"
    )
    if _PYTHON_VERSION.fullmatch(minimum_python) is None:
        raise OtaError("compatibility.minimum_python_version must be MAJOR.MINOR.PATCH")
    for field in ("minimum_runtime_schema", "minimum_ota_schema", "minimum_free_bytes"):
        raw = value.get(field)
        minimum = 0 if field == "minimum_free_bytes" else 1
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < minimum:
            raise OtaError(f"compatibility.{field} must be an integer >= {minimum}")
    for field in ("requires_stable_power", "requires_apply_enabled"):
        if not isinstance(value.get(field), bool):
            raise OtaError(f"compatibility.{field} must be boolean")
    return {
        "schema_version": 1,
        "hardware_models": list(models),
        "release_channel": channel,
        "minimum_python_version": minimum_python,
        "minimum_runtime_schema": value["minimum_runtime_schema"],
        "minimum_ota_schema": value["minimum_ota_schema"],
        "requires_stable_power": value["requires_stable_power"],
        "requires_apply_enabled": value["requires_apply_enabled"],
        "minimum_free_bytes": value["minimum_free_bytes"],
    }


def _detect_hardware_model() -> str:
    configured = (platform.machine() or "").strip().lower()
    try:
        model = Path("/proc/device-tree/model").read_text(encoding="ascii").rstrip("\0\n")
    except OSError:
        return configured
    normalized = model.lower()
    if "raspberry pi 5" in normalized:
        return "raspberry-pi-5"
    if "raspberry pi 4" in normalized:
        return "raspberry-pi-4"
    if "raspberry pi zero 2" in normalized:
        return "raspberry-pi-zero-2"
    return configured


def _contained_child(root: Path, name: str, *, field: str) -> Path:
    safe_name = _safe_identifier(name, field)
    resolved_root = root.resolve()
    candidate = resolved_root / safe_name
    if candidate.is_symlink():
        raise OtaError(f"{field} must not be a symbolic link")
    resolved_candidate = candidate.resolve(strict=False)
    if resolved_candidate.parent != resolved_root:
        raise OtaError(f"{field} resolves outside its configured root")
    return candidate


@dataclass(frozen=True)
class ReleaseManifest:
    version: str
    git_tag: str
    commit_sha: str
    update_type: str
    artifact_uri: str
    artifact_size: int
    artifact_sha256: str
    artifact_signature: str
    artifact_signature_scheme: str
    signature_key_id: str
    runtime_dependency_sha256: str
    compatibility: dict[str, Any]
    manifest_signature: str

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any], *, allow_local_file_artifacts: bool = False
    ) -> ReleaseManifest:
        allowed = {
            "version",
            "git_tag",
            "tag",
            "commit_sha",
            "commit",
            "update_type",
            "type",
            "artifact_uri",
            "uri",
            "artifact_size",
            "size",
            "artifact_sha256",
            "sha256",
            "artifact_signature",
            "signature",
            "artifact_signature_scheme",
            "signature_scheme",
            "signature_key_id",
            "key_id",
            "runtime_dependency_sha256",
            "compatibility",
            "manifest_signature",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise OtaError(f"unknown release manifest fields: {', '.join(sorted(unknown))}")

        def alias(primary: str, secondary: str) -> object:
            first = payload.get(primary)
            second = payload.get(secondary)
            if first is not None and second is not None and first != second:
                raise OtaError(f"conflicting {primary}/{secondary} values")
            return first if first is not None else second

        version = _safe_identifier(payload.get("version"), "version")
        git_tag = _safe_identifier(alias("git_tag", "tag"), "git_tag")
        commit_sha = _nonempty_string(alias("commit_sha", "commit"), "commit_sha").lower()
        if not (7 <= len(commit_sha) <= 64) or any(c not in "0123456789abcdef" for c in commit_sha):
            raise OtaError("commit_sha must be 7-64 hexadecimal characters")
        update_type = _nonempty_string(alias("update_type", "type"), "update_type").lower()
        if update_type not in _UPDATE_TYPES:
            raise OtaError(f"update_type must be one of: {', '.join(sorted(_UPDATE_TYPES))}")
        artifact_uri = _nonempty_string(alias("artifact_uri", "uri"), "artifact_uri")
        parsed_uri = urllib.parse.urlparse(artifact_uri)
        allowed_schemes = {"https", "file"} if allow_local_file_artifacts else {"https"}
        if parsed_uri.scheme not in allowed_schemes:
            raise OtaError("artifact_uri must use https://")
        if parsed_uri.scheme == "https" and not parsed_uri.netloc:
            raise OtaError("artifact_uri must contain an HTTPS host")
        if parsed_uri.scheme == "file" and (
            parsed_uri.netloc not in {"", "localhost"}
            or not parsed_uri.path
            or not Path(urllib.request.url2pathname(parsed_uri.path)).is_absolute()
        ):
            raise OtaError("file artifact_uri must be an absolute local URI")
        size_raw = alias("artifact_size", "size")
        if isinstance(size_raw, bool) or not isinstance(size_raw, int) or size_raw <= 0:
            raise OtaError("artifact_size must be a positive integer")
        artifact_sha256 = _nonempty_string(alias("artifact_sha256", "sha256"), "artifact_sha256").lower()
        if len(artifact_sha256) != 64 or any(c not in "0123456789abcdef" for c in artifact_sha256):
            raise OtaError("artifact_sha256 must be exactly 64 hexadecimal characters")
        signature = _nonempty_string(alias("artifact_signature", "signature"), "artifact_signature")
        try:
            decoded_signature = base64.b64decode(signature, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise OtaError("artifact_signature must be valid base64") from exc
        if not decoded_signature:
            raise OtaError("artifact_signature must decode to non-empty bytes")
        scheme = _nonempty_string(
            alias("artifact_signature_scheme", "signature_scheme"), "artifact_signature_scheme"
        ).lower()
        if scheme != _SIGNATURE_SCHEME:
            raise OtaError(f"artifact_signature_scheme must be {_SIGNATURE_SCHEME}")
        key_id = _safe_identifier(alias("signature_key_id", "key_id"), "signature_key_id")
        runtime_dependency_sha256 = _nonempty_string(
            payload.get("runtime_dependency_sha256"), "runtime_dependency_sha256"
        ).lower()
        if _SHA256_HEX.fullmatch(runtime_dependency_sha256) is None:
            raise OtaError("runtime_dependency_sha256 must be exactly 64 hexadecimal characters")
        compatibility = _validate_compatibility(payload.get("compatibility"))
        manifest_signature = _nonempty_string(payload.get("manifest_signature"), "manifest_signature")
        try:
            decoded_manifest_signature = base64.b64decode(manifest_signature, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise OtaError("manifest_signature must be valid base64") from exc
        if not decoded_manifest_signature:
            raise OtaError("manifest_signature must decode to non-empty bytes")
        return cls(
            version=version,
            git_tag=git_tag,
            commit_sha=commit_sha,
            update_type=update_type,
            artifact_uri=artifact_uri,
            artifact_size=size_raw,
            artifact_sha256=artifact_sha256,
            artifact_signature=signature,
            artifact_signature_scheme=scheme,
            signature_key_id=key_id,
            runtime_dependency_sha256=runtime_dependency_sha256,
            compatibility=compatibility,
            manifest_signature=manifest_signature,
        )

    def to_command_payload(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def identity(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_command_payload())).hexdigest()


class _UniqueKeyLoaderMixin:
    pass


class ReleaseCatalog:
    def __init__(self, releases: Mapping[str, ReleaseManifest], aliases: Mapping[str, str] | None = None):
        self.releases = dict(releases)
        self.aliases = dict(aliases or {})
        if not self.releases:
            raise OtaError("release catalog must contain at least one release")
        unknown_targets = set(self.aliases.values()) - set(self.releases)
        if unknown_targets:
            raise OtaError(f"aliases reference unknown releases: {', '.join(sorted(unknown_targets))}")
        if set(self.aliases) & set(self.releases):
            raise OtaError("alias names must not shadow release names")

    @classmethod
    def load(
        cls, path: str | os.PathLike[str], *, allow_local_file_artifacts: bool = False
    ) -> ReleaseCatalog:
        import yaml

        class UniqueKeyLoader(yaml.SafeLoader):
            pass

        def construct_mapping(
            loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False
        ) -> dict[Any, Any]:
            result: dict[Any, Any] = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node, deep=deep)
                if key in result:
                    raise OtaError(f"duplicate YAML key: {key}")
                result[key] = loader.construct_object(value_node, deep=deep)
            return result

        UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)
        catalog_path = Path(path)
        try:
            raw = yaml.load(catalog_path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
        except OtaError:
            raise
        except Exception as exc:
            raise OtaError(f"invalid release catalog YAML: {exc}") from exc
        if not isinstance(raw, Mapping):
            raise OtaError("release catalog root must be a mapping")
        allowed_root = {"schema_version", "releases", "aliases"}
        unknown = set(raw) - allowed_root
        if unknown:
            raise OtaError(f"unknown release catalog fields: {', '.join(sorted(map(str, unknown)))}")
        if raw.get("schema_version") != 1:
            raise OtaError("release catalog schema_version must be 1")
        releases_raw = raw.get("releases")
        if not isinstance(releases_raw, Mapping) or not releases_raw:
            raise OtaError("releases must be a non-empty mapping")
        releases: dict[str, ReleaseManifest] = {}
        for name, manifest_raw in releases_raw.items():
            release_name = _safe_identifier(name, "release name")
            if not isinstance(manifest_raw, Mapping):
                raise OtaError(f"release {release_name!r} must be a mapping")
            releases[release_name] = ReleaseManifest.from_payload(
                manifest_raw, allow_local_file_artifacts=allow_local_file_artifacts
            )
        aliases_raw = raw.get("aliases", {})
        if not isinstance(aliases_raw, Mapping):
            raise OtaError("aliases must be a mapping")
        aliases = {
            _safe_identifier(name, "alias name"): _safe_identifier(target, "alias target")
            for name, target in aliases_raw.items()
        }
        return cls(releases, aliases)

    def resolve(self, alias_or_release: str) -> ReleaseManifest:
        name = _safe_identifier(alias_or_release, "release alias")
        target = self.aliases.get(name, name)
        try:
            return self.releases[target]
        except KeyError as exc:
            raise OtaError(f"unknown release alias: {name}") from exc

    def __getitem__(self, alias_or_release: str) -> ReleaseManifest:
        return self.resolve(alias_or_release)


@dataclass
class LocalOtaManager:
    state_path: Path
    cache_dir: Path
    keyring_dir: Path
    releases_root: Path
    current_symlink: Path
    assets_root: Path
    gateway_cache_base_url: str | None = None
    max_artifact_bytes: int = 512 * 1024 * 1024
    device_id: str | None = None
    apply_enabled: bool = False
    allow_local_file_artifacts: bool = False
    hardware_model: str = ""
    release_channel: str = "stable"
    runtime_schema: int = 1
    runtime_dependency_path: Path | None = None
    power_state_path: Path | None = None
    run_command: Callable[..., Any] = subprocess.run
    readiness_probe: Callable[[], tuple[object, ...]] | None = None
    runtime_profile: str = "standalone"
    camera_readiness_owner_uid: int | None = None
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    wall_time: Callable[[], float] = time.time

    @classmethod
    def from_env(cls, device_id: str | None = None) -> LocalOtaManager:
        default_state = (
            f"./edgewatch_local_ota_{device_id}.json" if device_id else "/var/lib/edgewatch/local-ota.json"
        )
        state_path = Path(os.getenv("EDGEWATCH_LOCAL_OTA_STATE_PATH", default_state))
        current_symlink = Path(os.getenv("EDGEWATCH_CURRENT_SYMLINK", "/opt/edgewatch/current"))
        default_power_state = (
            f"./edgewatch_power_state_{device_id}.json"
            if device_id
            else "/var/lib/edgewatch/power-state.json"
        )
        return cls(
            state_path=state_path,
            cache_dir=Path(os.getenv("EDGEWATCH_OTA_CACHE_DIR", "/opt/edgewatch/update-cache")),
            keyring_dir=Path(os.getenv("EDGEWATCH_OTA_KEYRING_DIR", "/opt/edgewatch/keys")),
            releases_root=Path(os.getenv("EDGEWATCH_RELEASES_ROOT", "/opt/edgewatch/releases")),
            current_symlink=current_symlink,
            assets_root=Path(os.getenv("EDGEWATCH_ASSETS_ROOT", "/opt/edgewatch/assets")),
            gateway_cache_base_url=_gateway_cache_base_url(os.getenv("EDGEWATCH_OTA_GATEWAY_CACHE_URL")),
            max_artifact_bytes=int(os.getenv("EDGEWATCH_OTA_MAX_ARTIFACT_BYTES", str(512 * 1024 * 1024))),
            device_id=device_id,
            apply_enabled=_bool_env("EDGEWATCH_ENABLE_OTA_APPLY", default=False),
            hardware_model=(os.getenv("EDGEWATCH_HARDWARE_MODEL") or _detect_hardware_model()).strip(),
            release_channel=(os.getenv("EDGEWATCH_RELEASE_CHANNEL") or "stable").strip(),
            runtime_schema=int(os.getenv("EDGEWATCH_AGENT_RUNTIME_SCHEMA", "1")),
            runtime_dependency_path=Path(
                os.getenv(
                    "EDGEWATCH_RUNTIME_DEPENDENCY_PATH",
                    str(current_symlink / _RUNTIME_DEPENDENCY_RELATIVE_PATH),
                )
            ),
            power_state_path=Path(os.getenv("EDGEWATCH_POWER_STATE_PATH", default_power_state)),
            runtime_profile=(os.getenv("EDGEWATCH_OTA_RUNTIME_PROFILE") or "standalone").strip(),
        )

    def handle_command(
        self, *, command_type: str, args: Mapping[str, Any], command_id: str
    ) -> dict[str, Any]:
        """Adapter for ``agent.local_control.LocalControlExecutor``.

        Telegram supplies only a catalog alias.  Promotion reuses the exact
        manifest durably recorded by the preceding local stage/canary command.
        """
        if command_type == "ota_status":
            return {
                "ok": True,
                "action": "status",
                "status": "ok",
                "ota": self._public_state(self._load_state()),
            }
        if command_type not in {"ota_stage", "ota_canary", "ota_promote", "ota_abort"}:
            raise OtaError("unsupported typed OTA command")
        if command_type in {"ota_stage", "ota_canary"}:
            alias = _nonempty_string(args.get("release_alias"), "release_alias")
            if "://" in alias:
                raise OtaError("release_alias must not be a URL")
            supplied_raw = args.get("manifest")
            if "manifest" in args and not isinstance(supplied_raw, Mapping):
                raise OtaError("manifest must be a mapping")
            supplied = (
                ReleaseManifest.from_payload(
                    supplied_raw, allow_local_file_artifacts=self.allow_local_file_artifacts
                )
                if isinstance(supplied_raw, Mapping)
                else None
            )
            catalog_path = (os.getenv("EDGEWATCH_OTA_RELEASE_CATALOG") or "").strip()
            catalog_manifest = (
                ReleaseCatalog.load(
                    catalog_path, allow_local_file_artifacts=self.allow_local_file_artifacts
                ).resolve(alias)
                if catalog_path
                else None
            )
            if supplied is None and catalog_manifest is None:
                raise OtaError("trusted manifest payload or local release catalog is required")
            if (
                supplied is not None
                and catalog_manifest is not None
                and supplied.identity != catalog_manifest.identity
            ):
                raise OtaError("supplied manifest does not exactly match the local catalog alias")
            manifest = supplied or catalog_manifest
            if manifest is None:  # pragma: no cover - narrowed by the guard above
                raise OtaError("release manifest is unavailable")
            manifest_payload = manifest.to_command_payload()
            if command_type == "ota_stage":
                return self.execute("stage", manifest_payload, command_id)
            staged = self.execute("stage", manifest_payload, f"{command_id}:stage")
            if not staged.get("ok"):
                return staged
            return self.execute("apply", manifest_payload, command_id)
        if command_type == "ota_promote":
            state = self._load_state()
            staged = state.get("staged")
            if not isinstance(staged, Mapping) or not isinstance(staged.get("manifest"), Mapping):
                raise OtaError("no staged release is available for promotion")
            return self.execute("apply", staged["manifest"], command_id)
        return self.execute("abort", None, command_id)

    def execute(
        self, action: str, manifest_payload: Mapping[str, Any] | None, command_id: str
    ) -> dict[str, Any]:
        normalized_action = action.strip().lower().removeprefix("ota.").replace("-", "_")
        if normalized_action not in {"stage", "apply", "status", "rollback", "abort"}:
            raise OtaError("unsupported OTA action")
        command_id = _nonempty_string(command_id, "command_id")
        state = self._load_state()
        fingerprint = self._command_fingerprint(normalized_action, manifest_payload)
        prior = state.setdefault("commands", {}).get(command_id)
        if isinstance(prior, Mapping):
            if prior.get("fingerprint") != fingerprint:
                raise OtaError("command_id replayed with different input")
            result = prior.get("result")
            if isinstance(result, dict):
                return dict(result)
        try:
            result = self._execute_once(
                normalized_action,
                manifest_payload,
                state,
                command_id=command_id,
                fingerprint=fingerprint,
            )
        except RetryableOtaError:
            # The caller's command ledger must roll back so the same command_id
            # can be retried after network, storage, or readiness recovery.
            raise
        except OtaError as exc:
            result = {"ok": False, "action": normalized_action, "status": "failed", "reason": str(exc)}
        state.setdefault("commands", {})[command_id] = {"fingerprint": fingerprint, "result": result}
        journal = self._read_apply_journal(required=False)
        if (
            normalized_action == "apply"
            and isinstance(journal, dict)
            and journal["command_id"] == command_id
            and journal["fingerprint"] == fingerprint
        ):
            journal["phase"] = "verified"
            journal["committed_state"] = state
            self._write_apply_journal(journal)
        self._save_state(state)
        if normalized_action == "apply" and isinstance(journal, dict):
            self._clear_apply_journal()
        return result

    @staticmethod
    def _command_fingerprint(action: str, payload: Mapping[str, Any] | None) -> str:
        encoded = json.dumps({"action": action, "manifest": payload}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _execute_once(
        self,
        action: str,
        manifest_payload: Mapping[str, Any] | None,
        state: dict[str, Any],
        *,
        command_id: str,
        fingerprint: str,
    ) -> dict[str, Any]:
        if action == "status":
            return {"ok": True, "action": action, "status": "ok", "ota": self._public_state(state)}
        if action == "rollback":
            return self._rollback(state)
        if action == "abort":
            state["aborted"] = True
            return {"ok": True, "action": "abort", "status": "aborted"}
        if not isinstance(manifest_payload, Mapping):
            raise OtaError("manifest payload is required")
        manifest = ReleaseManifest.from_payload(
            manifest_payload, allow_local_file_artifacts=self.allow_local_file_artifacts
        )
        self._verify_manifest_signature(manifest)
        self._check_compatibility(manifest, action=action)
        if action == "stage":
            return self._stage(manifest, state)
        return self._apply(
            manifest,
            state,
            command_id=command_id,
            fingerprint=fingerprint,
        )

    def _check_compatibility(self, manifest: ReleaseManifest, *, action: str) -> None:
        compatibility = manifest.compatibility
        if not self.hardware_model or self.hardware_model not in compatibility["hardware_models"]:
            raise OtaError("hardware_incompatible")
        if compatibility["release_channel"] != self.release_channel:
            raise OtaError("channel_incompatible")
        required_python = tuple(int(part) for part in compatibility["minimum_python_version"].split("."))
        if tuple(sys.version_info[:3]) < required_python:
            raise OtaError("python_runtime_incompatible")
        if compatibility["minimum_runtime_schema"] > self.runtime_schema:
            raise OtaError("agent_runtime_schema_incompatible")
        if compatibility["minimum_ota_schema"] > _OTA_SCHEMA_VERSION:
            raise OtaError("ota_schema_incompatible")
        if manifest.update_type == "application_bundle":
            self._check_runtime_dependencies(manifest)
        if compatibility["requires_stable_power"]:
            self._check_stable_power()
        if action == "apply" and compatibility["requires_apply_enabled"] and not self.apply_enabled:
            raise OtaError("OTA apply is disabled by EDGEWATCH_ENABLE_OTA_APPLY")
        required_free = compatibility["minimum_free_bytes"]
        if action == "stage":
            required_free += manifest.artifact_size
        try:
            free_bytes = shutil.disk_usage(self.cache_dir.parent).free
        except OSError as exc:
            raise RetryableOtaError("unable to inspect OTA storage capacity") from exc
        if free_bytes < required_free:
            raise RetryableOtaError("insufficient OTA storage capacity")

    def _check_runtime_dependencies(self, manifest: ReleaseManifest) -> None:
        dependency_path = self.runtime_dependency_path
        if dependency_path is None:
            dependency_path = self.current_symlink / _RUNTIME_DEPENDENCY_RELATIVE_PATH
        try:
            metadata = dependency_path.lstat()
        except OSError as exc:
            raise OtaError(
                "runtime_dependency_incompatible: installed dependency baseline is missing"
            ) from exc
        if dependency_path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise OtaError("runtime_dependency_incompatible: installed dependency baseline is invalid")
        try:
            installed_sha256 = _sha256(dependency_path)
        except OSError as exc:
            raise OtaError(
                "runtime_dependency_incompatible: installed dependency baseline is unreadable"
            ) from exc
        if installed_sha256 != manifest.runtime_dependency_sha256:
            raise OtaError("runtime_dependency_incompatible")

    def _check_stable_power(self) -> None:
        if _bool_env("EDGEWATCH_POWER_INPUT_OUT_OF_RANGE") or _bool_env("EDGEWATCH_POWER_UNSUSTAINABLE"):
            raise OtaError("power_incompatible")
        if self.hardware_model not in {"raspberry-pi-4", "raspberry-pi-5", "raspberry-pi-zero-2"}:
            return
        if self.power_state_path is None:
            raise OtaError("power_incompatible: live power evidence is unavailable")
        try:
            metadata = self.power_state_path.lstat()
            payload = json.loads(self.power_state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OtaError("power_incompatible: live power evidence is unavailable") from exc
        if self.power_state_path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise OtaError("power_incompatible: live power evidence is invalid")
        evaluation = payload.get("last_evaluation") if isinstance(payload, Mapping) else None
        if not isinstance(evaluation, Mapping):
            raise OtaError("power_incompatible: live power evidence is unavailable")
        evaluated_at = evaluation.get("ts")
        flags = (
            evaluation.get("power_input_out_of_range"),
            evaluation.get("power_unsustainable"),
            evaluation.get("power_saver_active"),
        )
        evidence = evaluation.get("evidence")
        if (
            isinstance(evaluated_at, bool)
            or not isinstance(evaluated_at, (int, float))
            or any(not isinstance(flag, bool) for flag in flags)
            or not isinstance(evidence, str)
        ):
            raise OtaError("power_incompatible: live power evidence is invalid")
        max_age_s = max(1.0, float(os.getenv("EDGEWATCH_OTA_POWER_EVIDENCE_MAX_AGE_S", "300")))
        age_s = self.wall_time() - float(evaluated_at)
        if age_s < 0 or age_s > max_age_s:
            raise OtaError("power_incompatible: live power evidence is stale")
        if any(flags):
            raise OtaError("power_incompatible")
        if evidence not in {"input_voltage", "input_power", "battery"}:
            self._check_pi_throttling()

    def _check_pi_throttling(self) -> None:
        try:
            completed = self.run_command(
                ["vcgencmd", "get_throttled"],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise OtaError("power_incompatible: live Pi power evidence is unavailable") from exc
        output = str(getattr(completed, "stdout", "")).strip()
        match = re.fullmatch(r"throttled=0x([0-9a-fA-F]+)", output)
        if getattr(completed, "returncode", 1) != 0 or match is None:
            raise OtaError("power_incompatible: live Pi power evidence is invalid")
        if int(match.group(1), 16) != 0:
            raise OtaError("power_incompatible")

    def _artifact_path(self, manifest: ReleaseManifest) -> Path:
        suffix = Path(urllib.parse.urlparse(manifest.artifact_uri).path).suffix or ".bin"
        if not re.fullmatch(r"\.[A-Za-z0-9]{1,10}", suffix):
            suffix = ".bin"
        return _contained_child(
            self.cache_dir,
            f"{manifest.artifact_sha256}{suffix}",
            field="artifact cache name",
        )

    def _stage(self, manifest: ReleaseManifest, state: dict[str, Any]) -> dict[str, Any]:
        if manifest.artifact_size > self.max_artifact_bytes:
            raise OtaError("artifact exceeds configured size limit")
        artifact_path = self._artifact_path(manifest)
        try:
            self._download(manifest, artifact_path)
            downloaded_size = artifact_path.stat().st_size
        except OtaError:
            raise
        except OSError as exc:
            raise RetryableOtaError("unable to store OTA artifact") from exc
        if downloaded_size != manifest.artifact_size:
            raise OtaError("artifact size mismatch")
        if _sha256(artifact_path) != manifest.artifact_sha256:
            raise OtaError("artifact sha256 mismatch")
        self._verify_signature(manifest, artifact_path)
        stage_path: Path
        if manifest.update_type == "application_bundle":
            stage_path = _contained_child(
                self.releases_root,
                f"{manifest.git_tag}-{manifest.artifact_sha256[:12]}",
                field="application release path",
            )
            self._safe_extract(artifact_path, stage_path)
        elif manifest.update_type == "asset_bundle":
            stage_path = _contained_child(
                self.assets_root,
                f"{manifest.git_tag}-{manifest.artifact_sha256[:12]}",
                field="asset release path",
            )
            self._safe_extract(artifact_path, stage_path)
        else:
            stage_path = artifact_path
            self._stage_system_image(manifest, artifact_path)
        state["staged"] = {
            "manifest": manifest.to_command_payload(),
            "identity": manifest.identity,
            "artifact_path": str(artifact_path),
            "stage_path": str(stage_path),
        }
        state["aborted"] = False
        return {
            "ok": True,
            "action": "stage",
            "status": "staged",
            "version": manifest.version,
            "git_tag": manifest.git_tag,
            "update_type": manifest.update_type,
            "identity": manifest.identity,
        }

    def _apply(
        self,
        manifest: ReleaseManifest,
        state: dict[str, Any],
        *,
        command_id: str,
        fingerprint: str,
    ) -> dict[str, Any]:
        if not self.apply_enabled:
            raise OtaError("OTA apply is disabled by EDGEWATCH_ENABLE_OTA_APPLY")
        if state.get("aborted") is True:
            raise OtaError("local OTA deployment was aborted")
        staged = state.get("staged")
        if not isinstance(staged, Mapping) or staged.get("identity") != manifest.identity:
            raise OtaError("release must be staged before apply")
        if manifest.update_type == "system_image":
            self._apply_system_image(manifest, Path(str(staged["artifact_path"])))
        elif manifest.update_type == "application_bundle":
            target = Path(str(staged["stage_path"]))
            if not target.is_dir():
                raise OtaError("staged application bundle is missing")
            previous = self._current_target()
            if self.runtime_profile == _CAMERA_RUNTIME_PROFILE:
                self._restart_and_verify(None)
            previous_receipt = self._readiness_snapshot()
            journal: dict[str, Any] = {
                "schema_version": _APPLY_JOURNAL_SCHEMA_VERSION,
                "phase": "prepared",
                "original_target": previous,
                "current_target": str(target.resolve()),
                "command_id": command_id,
                "fingerprint": fingerprint,
                "manifest": manifest.to_command_payload(),
            }
            self._write_apply_journal(journal)
            self._atomic_symlink(target)
            journal["phase"] = "switched"
            self._write_apply_journal(journal)
            try:
                self._restart_and_verify(previous_receipt)
            except OtaError as apply_error:
                self._restore_symlink(previous)
                try:
                    self._restart_and_verify(None)
                except OtaError as rollback_error:
                    raise RetryableOtaError(
                        f"application readiness failed and rollback restart failed: {rollback_error}"
                    ) from apply_error
                self._clear_apply_journal()
                raise RetryableOtaError(
                    "application readiness failed; previous release restored"
                ) from apply_error
            state["previous_target"] = previous
            state["current_target"] = str(target.resolve())
        else:
            hook = (os.getenv("EDGEWATCH_ASSET_BUNDLE_APPLY_CMD") or "").strip()
            if hook:
                self._run_hook(hook, manifest, Path(str(staged["stage_path"])))
        state["active"] = {"manifest": manifest.to_command_payload(), "identity": manifest.identity}
        state["aborted"] = False
        return {
            "ok": True,
            "action": "apply",
            "status": "applied",
            "version": manifest.version,
            "git_tag": manifest.git_tag,
            "update_type": manifest.update_type,
        }

    def _rollback(self, state: dict[str, Any]) -> dict[str, Any]:
        previous = state.get("previous_target")
        if not isinstance(previous, str) or not previous:
            raise OtaError("no previous application target is available")
        target = Path(previous)
        if not target.is_dir():
            raise OtaError("previous application target is missing")
        current = self._current_target()
        if self.runtime_profile == _CAMERA_RUNTIME_PROFILE:
            self._restart_and_verify(None)
        current_receipt = self._readiness_snapshot()
        self._atomic_symlink(target)
        try:
            self._restart_and_verify(current_receipt)
        except OtaError as rollback_error:
            self._restore_symlink(current)
            try:
                self._restart_and_verify(None)
            except OtaError as restore_error:
                raise RetryableOtaError(
                    f"rollback readiness failed and active release restart failed: {restore_error}"
                ) from rollback_error
            raise RetryableOtaError("rollback readiness failed; active release restored") from rollback_error
        state["current_target"] = previous
        state["previous_target"] = current
        state["active"] = {"status": "rolled_back", "target": previous}
        return {"ok": True, "action": "rollback", "status": "rolled_back", "target": previous}

    def _download(self, manifest: ReleaseManifest, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if (
                destination.stat().st_size == manifest.artifact_size
                and _sha256(destination) == manifest.artifact_sha256
            ):
                return
            destination.unlink()
        partial = destination.with_name(destination.name + ".part")
        existing = partial.stat().st_size if partial.exists() else 0
        if existing == manifest.artifact_size:
            if _sha256(partial) == manifest.artifact_sha256:
                os.replace(partial, destination)
                return
            partial.unlink()
            existing = 0
        if existing > manifest.artifact_size:
            partial.unlink()
            existing = 0
        download_uri = manifest.artifact_uri
        if self.gateway_cache_base_url is not None:
            download_uri = f"{self.gateway_cache_base_url}/artifacts/{manifest.artifact_sha256}"
        parsed = urllib.parse.urlparse(download_uri)
        if parsed.scheme == "file":
            source = Path(urllib.request.url2pathname(parsed.path))
            if not source.is_file():
                raise OtaError("local artifact does not exist")
            if source.stat().st_size != manifest.artifact_size:
                raise OtaError("artifact size mismatch")
            with source.open("rb") as source_fh, partial.open("ab" if existing else "wb") as output:
                source_fh.seek(existing)
                self._copy_bounded(source_fh, output, manifest.artifact_size - existing)
        else:
            headers = {"Range": f"bytes={existing}-"} if existing else {}
            request = urllib.request.Request(download_uri, headers=headers)
            try:
                if parsed.scheme == "https":
                    response = urllib.request.build_opener(_OtaRedirectHandler()).open(request, timeout=30)
                else:
                    response = urllib.request.urlopen(request, timeout=30)  # noqa: S310 - private gateway-cache HTTP is constrained above
            except (OSError, urllib.error.URLError) as exc:
                raise RetryableOtaError("artifact download failed") from exc
            with response:
                final_url = response.geturl() if hasattr(response, "geturl") else request.full_url
                source_origin = _url_origin(request.full_url)
                final_origin = _url_origin(final_url)
                if source_origin[0] == "https" and final_origin[0] != "https":
                    raise OtaError("artifact redirect downgraded HTTPS")
                if source_origin != final_origin:
                    raise OtaError("artifact redirect changed host")
                if existing and getattr(response, "status", None) != 206:
                    existing = 0
                    partial.unlink(missing_ok=True)
                with partial.open("ab" if existing else "wb") as output:
                    self._copy_bounded(response, output, manifest.artifact_size - existing)
        if partial.stat().st_size != manifest.artifact_size:
            raise RetryableOtaError("artifact download was incomplete")
        os.replace(partial, destination)

    @staticmethod
    def _copy_bounded(source: Any, output: Any, remaining: int) -> None:
        copied = 0
        while copied < remaining:
            chunk = source.read(min(1024 * 1024, remaining - copied + 1))
            if not chunk:
                break
            copied += len(chunk)
            if copied > remaining:
                raise OtaError("artifact exceeds declared size")
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())

    def _verify_signature(self, manifest: ReleaseManifest, artifact_path: Path) -> None:
        public_key = _contained_child(
            self.keyring_dir, f"{manifest.signature_key_id}.pem", field="signature key path"
        )
        try:
            metadata = public_key.lstat()
        except OSError as exc:
            raise OtaError("signature key is not installed") from exc
        if public_key.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise OtaError("signature key is not installed")
        try:
            signature = base64.b64decode(manifest.artifact_signature, validate=True)
        except binascii.Error as exc:
            raise OtaError("artifact signature is invalid base64") from exc
        with tempfile.NamedTemporaryFile(prefix="edgewatch-ota-signature-") as signature_file:
            signature_file.write(signature)
            signature_file.flush()
            process = subprocess.run(
                [
                    "openssl",
                    "dgst",
                    "-sha256",
                    "-verify",
                    str(public_key),
                    "-signature",
                    signature_file.name,
                    str(artifact_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        if process.returncode != 0:
            raise OtaError("artifact signature verification failed")

    def _verify_manifest_signature(self, manifest: ReleaseManifest) -> None:
        public_key = _contained_child(
            self.keyring_dir, f"{manifest.signature_key_id}.pem", field="signature key path"
        )
        try:
            metadata = public_key.lstat()
        except OSError as exc:
            raise OtaError("signature key is not installed") from exc
        if public_key.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise OtaError("signature key is not installed")
        try:
            signature = base64.b64decode(manifest.manifest_signature, validate=True)
        except binascii.Error as exc:
            raise OtaError("manifest signature is invalid base64") from exc
        with tempfile.NamedTemporaryFile(prefix="edgewatch-ota-manifest-") as manifest_file:
            manifest_file.write(canonical_manifest_bytes(manifest.to_command_payload()))
            manifest_file.flush()
            with tempfile.NamedTemporaryFile(prefix="edgewatch-ota-manifest-signature-") as signature_file:
                signature_file.write(signature)
                signature_file.flush()
                process = subprocess.run(
                    [
                        "openssl",
                        "dgst",
                        "-sha256",
                        "-verify",
                        str(public_key),
                        "-signature",
                        signature_file.name,
                        manifest_file.name,
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
        if process.returncode != 0:
            raise OtaError("manifest signature verification failed")

    @staticmethod
    def _validate_member(member: tarfile.TarInfo) -> None:
        member_path = PurePosixPath(member.name)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise OtaError("archive contains path traversal")
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise OtaError("archive contains a forbidden link or special file")
        if not (member.isfile() or member.isdir()):
            raise OtaError("archive contains an unsupported entry type")

    def _safe_extract(self, artifact_path: Path, destination: Path) -> None:
        if destination.exists():
            marker = destination / ".edgewatch-release.json"
            if marker.is_file():
                return
            raise OtaError("staging destination already exists")
        temporary = destination.with_name(destination.name + ".tmp")
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir(parents=True, mode=0o700)
        try:
            with tarfile.open(artifact_path, mode="r:*") as archive:
                members = archive.getmembers()
                for member in members:
                    self._validate_member(member)
                archive.extractall(temporary, members=members, filter="data")
            marker = temporary / ".edgewatch-release.json"
            marker.write_text(json.dumps({"artifact_sha256": _sha256(artifact_path)}), encoding="utf-8")
            self._fsync_tree(temporary)
            self._fsync_directory(destination.parent)
            os.replace(temporary, destination)
            self._fsync_directory(destination.parent)
        except (OtaError, tarfile.TarError, OSError) as exc:
            shutil.rmtree(temporary, ignore_errors=True)
            if isinstance(exc, OtaError):
                raise
            if isinstance(exc, OSError):
                raise RetryableOtaError("unable to write extracted OTA bundle") from exc
            raise OtaError(f"unable to safely extract bundle: {exc}") from exc

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        directory_fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @classmethod
    def _fsync_tree(cls, root: Path) -> None:
        directories: list[Path] = []
        for current_root, _, filenames in os.walk(root):
            directory = Path(current_root)
            directories.append(directory)
            for filename in filenames:
                file_fd = os.open(directory / filename, os.O_RDONLY)
                try:
                    os.fsync(file_fd)
                finally:
                    os.close(file_fd)
        for directory in reversed(directories):
            cls._fsync_directory(directory)

    def _stage_system_image(self, manifest: ReleaseManifest, artifact_path: Path) -> None:
        command = (os.getenv("EDGEWATCH_SYSTEM_IMAGE_STAGE_CMD") or "").strip()
        if not command:
            wrapper = Path(__file__).resolve().parents[1] / "scripts" / "ota" / "system_image_updater.py"
            command = f"{shlex.quote(sys.executable)} {shlex.quote(str(wrapper))}"
        self._run_hook(
            command,
            manifest,
            artifact_path,
            extra_env={"EDGEWATCH_SYSTEM_IMAGE_STAGE_DIR": str(self.cache_dir / "system-image-staging")},
        )

    def _apply_system_image(self, manifest: ReleaseManifest, artifact_path: Path) -> None:
        hook = (os.getenv("EDGEWATCH_SYSTEM_IMAGE_APPLY_CMD") or "").strip()
        if not (
            _bool_env("EDGEWATCH_ENABLE_SYSTEM_IMAGE_APPLY")
            and _bool_env("EDGEWATCH_SYSTEM_IMAGE_HARDWARE_QUALIFIED")
            and hook
        ):
            raise OtaError("system_image apply is disabled pending hardware qualification and an apply hook")
        self._run_hook(hook, manifest, artifact_path)

    @staticmethod
    def _run_hook(
        command: str,
        manifest: ReleaseManifest,
        artifact_path: Path,
        *,
        extra_env: Mapping[str, str] | None = None,
    ) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "EDGEWATCH_OTA_ARTIFACT_PATH": str(artifact_path),
                "EDGEWATCH_OTA_MANIFEST_ID": manifest.identity,
                "EDGEWATCH_OTA_ARTIFACT_SHA256": manifest.artifact_sha256,
            }
        )
        if extra_env:
            environment.update(extra_env)
        try:
            process = subprocess.run(
                shlex.split(command), check=False, capture_output=True, text=True, env=environment
            )
        except OSError as exc:
            raise RetryableOtaError("unable to execute OTA hook") from exc
        if process.returncode:
            raise RetryableOtaError(f"OTA hook failed with exit code {process.returncode}")

    def _current_target(self) -> str | None:
        if not self.current_symlink.is_symlink():
            return None
        target = os.readlink(self.current_symlink)
        return str((self.current_symlink.parent / target).resolve()) if not os.path.isabs(target) else target

    def _restore_symlink(self, previous: str | None) -> None:
        if previous is None:
            self.current_symlink.unlink(missing_ok=True)
            return
        self._atomic_symlink(Path(previous))

    def _restart_and_verify(self, previous_receipt: tuple[object, ...] | None) -> None:
        if self.runtime_profile == _CAMERA_RUNTIME_PROFILE:
            self._restart_camera_and_verify(previous_receipt)
            return
        service = (os.getenv("EDGEWATCH_AGENT_SYSTEMD_SERVICE") or "edgewatch-agent.service").strip()
        if not service or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._@:-"
            for character in service
        ):
            raise OtaError("invalid edgewatch-agent service name")
        try:
            completed = self.run_command(
                ["systemctl", "restart", service],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RetryableOtaError("edgewatch-agent restart failed") from exc
        if getattr(completed, "returncode", 1) != 0:
            raise RetryableOtaError("edgewatch-agent restart failed")
        timeout_s = max(0.0, float(os.getenv("EDGEWATCH_OTA_READY_TIMEOUT_S", "60")))
        stability_s = max(0.0, float(os.getenv("EDGEWATCH_OTA_READY_STABILITY_S", "10")))
        poll_s = max(0.01, float(os.getenv("EDGEWATCH_OTA_READY_POLL_S", "0.5")))
        deadline = self.monotonic() + timeout_s
        last_error: OtaError | None = None
        while True:
            try:
                current = self._readiness_snapshot()
                if previous_receipt is not None and current == previous_receipt:
                    raise OtaError("edgewatch-agent readiness receipt is stale")
                break
            except OtaError as exc:
                last_error = exc
                if self.monotonic() >= deadline:
                    raise RetryableOtaError(
                        "edgewatch-agent did not publish a fresh readiness receipt"
                    ) from last_error
                self.sleep(poll_s)
        if stability_s:
            self.sleep(stability_s)
        if self._readiness_snapshot() != current:
            raise RetryableOtaError("edgewatch-agent restarted during the readiness stability window")

    def _readiness_snapshot(self) -> tuple[object, ...]:
        if self.readiness_probe is not None:
            return self.readiness_probe()
        if self.runtime_profile == _CAMERA_RUNTIME_PROFILE:
            return self._camera_readiness_snapshot()
        ready_raw = (os.getenv("EDGEWATCH_READY_PATH") or "").strip()
        if not ready_raw:
            raise OtaError("EDGEWATCH_READY_PATH is required for application activation")
        service = (os.getenv("EDGEWATCH_AGENT_SYSTEMD_SERVICE") or "edgewatch-agent.service").strip()
        try:
            ready_path = Path(ready_raw)
            ready_stat = ready_path.lstat()
            if not stat.S_ISREG(ready_stat.st_mode) or ready_stat.st_mode & 0o077:
                raise OtaError("edgewatch-agent readiness receipt is not a private regular file")
            active = self.run_command(
                ["systemctl", "is-active", "--quiet", service],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            main_pid_result = self.run_command(
                ["systemctl", "show", "--property=MainPID", "--value", service],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            payload = json.loads(ready_path.read_text(encoding="utf-8"))
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise OtaError("edgewatch-agent readiness receipt is unavailable") from exc
        if getattr(active, "returncode", 1) != 0 or getattr(main_pid_result, "returncode", 1) != 0:
            raise OtaError("edgewatch-agent service is not active")
        if not isinstance(payload, Mapping):
            raise OtaError("edgewatch-agent readiness receipt must be an object")
        raw_pid = payload.get("pid")
        if isinstance(raw_pid, bool) or not isinstance(raw_pid, (int, str)):
            raise OtaError("edgewatch-agent readiness receipt has an invalid PID")
        try:
            receipt_pid = int(raw_pid)
            main_pid = int(str(getattr(main_pid_result, "stdout", "")).strip())
        except (TypeError, ValueError) as exc:
            raise OtaError("edgewatch-agent readiness receipt has an invalid PID") from exc
        session_id = str(payload.get("process_session_id") or "").strip()
        expected_transport = (os.getenv("EDGEWATCH_TELEMETRY_TRANSPORT") or "").strip()
        if (
            receipt_pid <= 0
            or receipt_pid != main_pid
            or not session_id
            or (self.device_id is not None and payload.get("device_id") != self.device_id)
            or (expected_transport and payload.get("transport") != expected_transport)
        ):
            raise OtaError("edgewatch-agent readiness receipt belongs to a stale or different process")
        return receipt_pid, session_id

    def _restart_camera_and_verify(self, previous_receipt: tuple[object, ...] | None) -> None:
        try:
            _CAMERA_READY_PATH.unlink(missing_ok=True)
            completed = self.run_command(
                ["/usr/bin/systemctl", "start", _CAMERA_CHECK_UNIT],
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RetryableOtaError("camera readiness unit failed") from exc
        if getattr(completed, "returncode", 1) != 0:
            raise RetryableOtaError("camera readiness unit failed")
        timeout_s = max(0.0, float(os.getenv("EDGEWATCH_OTA_READY_TIMEOUT_S", "60")))
        stability_s = max(0.0, float(os.getenv("EDGEWATCH_OTA_READY_STABILITY_S", "10")))
        poll_s = max(0.01, float(os.getenv("EDGEWATCH_OTA_READY_POLL_S", "0.5")))
        deadline = self.monotonic() + timeout_s
        last_error: OtaError | None = None
        while True:
            try:
                current = self._camera_readiness_snapshot()
                if previous_receipt is not None and current == previous_receipt:
                    raise OtaError("camera readiness receipt is stale")
                break
            except OtaError as exc:
                last_error = exc
                if self.monotonic() >= deadline:
                    raise RetryableOtaError(
                        "camera did not publish a fresh readiness receipt"
                    ) from last_error
                self.sleep(poll_s)
        if stability_s:
            self.sleep(stability_s)
        if self._camera_readiness_snapshot() != current:
            raise RetryableOtaError("camera readiness changed during the stability window")

    def _camera_readiness_snapshot(self) -> tuple[object, ...]:
        try:
            metadata = _CAMERA_READY_PATH.lstat()
            if (
                _CAMERA_READY_PATH.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or not 0 < metadata.st_size <= 64 * 1024
            ):
                raise OtaError("camera readiness receipt is not a private regular file")
            expected_uid = self.camera_readiness_owner_uid
            if expected_uid is None:
                import pwd

                expected_uid = pwd.getpwnam(_CAMERA_USER).pw_uid
            if metadata.st_uid != expected_uid:
                raise OtaError("camera readiness receipt has the wrong owner")
            payload = json.loads(_CAMERA_READY_PATH.read_text(encoding="utf-8"))
        except OtaError:
            raise
        except (KeyError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise OtaError("camera readiness receipt is unavailable") from exc
        if not isinstance(payload, Mapping):
            raise OtaError("camera readiness receipt must be an object")
        target = self._current_target()
        issued_at = self._read_receipt_time(payload.get("issued_at"), "issued_at")
        valid_until = self._read_receipt_time(payload.get("valid_until"), "valid_until")
        now = dt.datetime.fromtimestamp(self.wall_time(), tz=dt.timezone.utc)
        if (
            payload.get("schema_version") != 1
            or payload.get("status") != "ready"
            or payload.get("application_target") != target
            or (self.device_id is not None and payload.get("device_id") != self.device_id)
            or payload.get("known_answers_valid") is not True
            or payload.get("preprocessing_valid") is not True
            or payload.get("local_media_only") is not True
            or valid_until <= issued_at
            or not issued_at <= now < valid_until
        ):
            raise OtaError("camera readiness receipt does not match the current application")
        return (
            str(payload.get("boot_id") or ""),
            int(payload.get("pid") or 0),
            issued_at.isoformat(),
            target,
        )

    @staticmethod
    def _read_receipt_time(value: object, field: str) -> dt.datetime:
        if not isinstance(value, str):
            raise OtaError(f"camera readiness receipt has invalid {field}")
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise OtaError(f"camera readiness receipt has invalid {field}") from exc
        if parsed.tzinfo is None:
            raise OtaError(f"camera readiness receipt has invalid {field}")
        return parsed.astimezone(dt.timezone.utc)

    def _atomic_symlink(self, target: Path) -> None:
        self.current_symlink.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.current_symlink.with_name(f".{self.current_symlink.name}.ota-tmp")
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(target)
        os.replace(temporary, self.current_symlink)
        directory_fd = os.open(self.current_symlink.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _load_state(self) -> dict[str, Any]:
        self._recover_apply_transaction()
        return self._load_state_raw()

    def _load_state_raw(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"schema_version": 1, "commands": {}}
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise OtaError(f"invalid local OTA state: {exc}") from exc
        except OSError as exc:
            raise RetryableOtaError("local OTA state is temporarily unavailable") from exc
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            raise OtaError("invalid local OTA state schema")
        if not isinstance(raw.get("commands"), dict):
            raise OtaError("invalid local OTA command ledger")
        return raw

    @property
    def _apply_journal_path(self) -> Path:
        return self.state_path.with_name(f"{self.state_path.name}.apply-journal")

    def _read_apply_journal(self, *, required: bool) -> dict[str, Any] | None:
        path = self._apply_journal_path
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            if required:
                raise OtaError("local OTA apply journal is missing")
            return None
        except OSError as exc:
            raise RetryableOtaError("local OTA apply journal is temporarily unavailable") from exc
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise OtaError("invalid local OTA apply journal")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise OtaError(f"invalid local OTA apply journal: {exc}") from exc
        except OSError as exc:
            raise RetryableOtaError("local OTA apply journal is temporarily unavailable") from exc
        if not isinstance(raw, dict):
            raise OtaError("invalid local OTA apply journal")
        phase = raw.get("phase")
        expected = {
            "schema_version",
            "phase",
            "original_target",
            "current_target",
            "command_id",
            "fingerprint",
            "manifest",
        }
        if phase == "verified":
            expected.add("committed_state")
        if set(raw) != expected or raw.get("schema_version") != _APPLY_JOURNAL_SCHEMA_VERSION:
            raise OtaError("invalid local OTA apply journal schema")
        original = raw.get("original_target")
        target = raw.get("current_target")
        command_id = raw.get("command_id")
        fingerprint = raw.get("fingerprint")
        manifest_payload = raw.get("manifest")
        if (
            phase not in _APPLY_JOURNAL_PHASES
            or (original is not None and (not isinstance(original, str) or not original))
            or not isinstance(target, str)
            or not target
            or not isinstance(command_id, str)
            or not command_id
            or not isinstance(fingerprint, str)
            or _SHA256_HEX.fullmatch(fingerprint) is None
            or not isinstance(manifest_payload, Mapping)
        ):
            raise OtaError("invalid local OTA apply journal")
        manifest = ReleaseManifest.from_payload(
            manifest_payload, allow_local_file_artifacts=self.allow_local_file_artifacts
        )
        if manifest.update_type != "application_bundle":
            raise OtaError("invalid local OTA apply journal manifest")
        target_path = Path(target)
        if (
            not target_path.is_absolute()
            or str(target_path.resolve(strict=False)) != target
            or target_path.resolve(strict=False).parent != self.releases_root.resolve()
            or not target_path.is_dir()
        ):
            raise OtaError("invalid local OTA apply journal target")
        if original is not None:
            original_path = Path(original)
            if (
                not original_path.is_absolute()
                or str(original_path.resolve(strict=False)) != original
                or not original_path.is_dir()
                or original == target
            ):
                raise OtaError("invalid local OTA apply journal original target")
        if phase == "verified":
            committed = raw.get("committed_state")
            if (
                not isinstance(committed, dict)
                or committed.get("schema_version") != 1
                or not isinstance(committed.get("commands"), dict)
            ):
                raise OtaError("invalid local OTA apply journal committed state")
            command = committed["commands"].get(command_id)
            if (
                not isinstance(command, Mapping)
                or command.get("fingerprint") != fingerprint
                or not isinstance(command.get("result"), dict)
            ):
                raise OtaError("invalid local OTA apply journal command outcome")
            result = command["result"]
            if (
                result.get("ok") is not True
                or result.get("action") != "apply"
                or result.get("status") != "applied"
                or committed.get("current_target") != target
                or committed.get("previous_target") != original
                or not isinstance(committed.get("active"), Mapping)
            ):
                raise OtaError("invalid local OTA apply journal committed state")
        return raw

    def _write_apply_journal(self, journal: Mapping[str, Any]) -> None:
        path = self._apply_journal_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        except OSError as exc:
            raise RetryableOtaError("unable to persist local OTA apply journal") from exc
        temporary = Path(temporary_name)
        try:
            try:
                os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    json.dump(journal, output, sort_keys=True, separators=(",", ":"))
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, path)
                os.chmod(path, 0o600)
                self._fsync_directory(path.parent)
            except OSError as exc:
                raise RetryableOtaError("unable to persist local OTA apply journal") from exc
        finally:
            temporary.unlink(missing_ok=True)

    def _clear_apply_journal(self) -> None:
        try:
            self._apply_journal_path.unlink(missing_ok=True)
            self._fsync_directory(self._apply_journal_path.parent)
        except OSError as exc:
            raise RetryableOtaError("unable to clear local OTA apply journal") from exc

    def _recover_apply_transaction(self) -> None:
        journal = self._read_apply_journal(required=False)
        if journal is None:
            return
        if journal["phase"] == "verified":
            if self._current_target() != journal["current_target"]:
                raise OtaError("local OTA apply journal does not match the current release target")
            committed = journal["committed_state"]
            self._save_state(committed)
            self._clear_apply_journal()
            return

        original = journal["original_target"]
        current = self._current_target()
        if journal["phase"] == "prepared" and current == original:
            self._save_state(self._load_state_raw())
            self._clear_apply_journal()
            return
        if current not in {original, journal["current_target"]}:
            raise OtaError("local OTA apply journal does not match the current release target")
        if original is None and current == journal["current_target"]:
            self._finish_initial_apply_recovery(journal)
            return
        self._restore_symlink(original)
        self._restart_and_verify(None)
        state = self._load_state_raw()
        state["current_target"] = original
        self._save_state(state)
        self._clear_apply_journal()

    def _finish_initial_apply_recovery(self, journal: dict[str, Any]) -> None:
        manifest = ReleaseManifest.from_payload(
            journal["manifest"], allow_local_file_artifacts=self.allow_local_file_artifacts
        )
        state = self._load_state_raw()
        staged = state.get("staged")
        if (
            not isinstance(staged, Mapping)
            or staged.get("identity") != manifest.identity
            or str(Path(str(staged.get("stage_path"))).resolve(strict=False)) != journal["current_target"]
        ):
            raise OtaError("local OTA apply journal does not match the staged release")
        self._restart_and_verify(None)
        result = {
            "ok": True,
            "action": "apply",
            "status": "applied",
            "version": manifest.version,
            "git_tag": manifest.git_tag,
            "update_type": manifest.update_type,
        }
        state["previous_target"] = None
        state["current_target"] = journal["current_target"]
        state["active"] = {
            "manifest": manifest.to_command_payload(),
            "identity": manifest.identity,
        }
        state["aborted"] = False
        state.setdefault("commands", {})[journal["command_id"]] = {
            "fingerprint": journal["fingerprint"],
            "result": result,
        }
        journal["phase"] = "verified"
        journal["committed_state"] = state
        self._write_apply_journal(journal)
        self._save_state(state)
        self._clear_apply_journal()

    def _save_state(self, state: Mapping[str, Any]) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{self.state_path.name}.", dir=self.state_path.parent
            )
        except OSError as exc:
            raise RetryableOtaError("unable to persist local OTA state") from exc
        temporary = Path(temporary_name)
        try:
            try:
                os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    json.dump(state, output, sort_keys=True, separators=(",", ":"))
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.state_path)
                os.chmod(self.state_path, 0o600)
                directory_fd = os.open(self.state_path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError as exc:
                raise RetryableOtaError("unable to persist local OTA state") from exc
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _public_state(state: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in state.items() if key != "commands"}
