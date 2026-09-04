from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import sys
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Literal, Mapping, Protocol, cast

from agent.inference.bundle import (
    InstalledModelBundle,
    ModelBundleError,
    ModelBundleManager,
    validate_known_answer_cases,
)
from agent.inference.litert import InferenceUnavailableError, QuantizedModelError
from agent.inference.policy import AlertGateSnapshot, PromotionEvidence
from agent.inference.preprocess import (
    FFmpegTensorPreprocessor,
    PreprocessedInputs,
    PreprocessingError,
    QuantizedInputSpec,
)
from agent.inference.runtime import EquipmentInferenceRuntime, InferenceEvaluation
from agent.media.capture import CameraCaptureError
from agent.media.evidence import (
    CapturedEventEvidence,
    CapturedInferenceSample,
    LocalEvidenceStore,
)
from agent.media.rtsp import (
    FFmpegRtspBackend,
    RtspCameraConfig,
    RtspCaptureLimits,
    RtspConfigurationError,
    RtspStreamInfo,
)
from agent.media.storage import MediaStorageError, to_iso_utc

RunMode = Literal["event", "daily", "check"]
InferenceMode = Literal["shadow", "live"]
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_BAKED_APPLICATION_TARGET = Path("/opt/edgewatch/app")
_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "mode",
        "invocation_id",
        "device_id",
        "camera_id",
        "observed_at",
        "model_version",
        "manifest_identity",
        "video_codec",
        "audio_codec",
        "equipment_state",
        "state_confidence",
        "audio_anomaly_score",
        "visual_change",
        "alert_eligible",
        "alert_reason",
        "repeated_observations",
        "evidence_capture_id",
        "evidence_sha256",
        "poweroff_requested",
    }
)


class SatelliteConfigError(ValueError):
    """The camera-satellite environment does not satisfy the closed contract."""


class SatelliteRunError(RuntimeError):
    """A bounded, machine-safe runner failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SAFE_IDENTIFIER.fullmatch(value.strip()) is None:
        raise SatelliteConfigError(f"{field} must be a safe identifier")
    return value.strip()


def _required_env(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name)
    if value is None or not value.strip():
        raise SatelliteConfigError(f"{name} is required")
    return value.strip()


def _absolute_path(value: str, *, field: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path == Path("/"):
        raise SatelliteConfigError(f"{field} must be an absolute non-root path")
    return path


def _bounded_int(
    environ: Mapping[str, str],
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SatelliteConfigError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise SatelliteConfigError(f"{name} must be within {minimum}..{maximum}")
    return value


def _bounded_float(
    environ: Mapping[str, str],
    name: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    raw = environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise SatelliteConfigError(f"{name} must be numeric") from exc
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise SatelliteConfigError(f"{name} must be within {minimum}..{maximum}")
    return value


@dataclass(frozen=True)
class SatelliteConfig:
    device_id: str
    camera_id: str
    rtsp_endpoint: str
    rtsp_credentials_path: Path
    model_releases_root: Path
    model_current_symlink: Path
    model_keyring_dir: Path
    application_releases_root: Path
    application_current_symlink: Path
    hardware_model: str
    litert_version: str
    evidence_dir: Path
    evidence_max_bytes: int
    result_path: Path
    ready_path: Path
    gate_state_path: Path
    lock_path: Path
    poweroff_request_path: Path
    inference_mode: InferenceMode
    promotion_file: Path | None
    event_reason: str
    capture_timeout_s: float
    event_duration_s: float
    preprocess_timeout_s: float
    readiness_ttl_s: int
    ffmpeg_binary: str
    ffprobe_binary: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> SatelliteConfig:
        values = dict(os.environ if environ is None else environ)
        device_id = _safe_identifier(
            _required_env(values, "EDGEWATCH_DEVICE_ID"), field="EDGEWATCH_DEVICE_ID"
        )
        camera_id = _safe_identifier(values.get("EDGEWATCH_CAMERA_ID", "cam1"), field="EDGEWATCH_CAMERA_ID")
        inference_mode_raw = values.get("EDGEWATCH_INFERENCE_MODE", "shadow").strip().lower()
        if inference_mode_raw not in {"shadow", "live"}:
            raise SatelliteConfigError("EDGEWATCH_INFERENCE_MODE must be shadow or live")
        inference_mode = cast(InferenceMode, inference_mode_raw)
        promotion_raw = values.get("EDGEWATCH_INFERENCE_PROMOTION_FILE", "").strip()
        promotion_file = (
            _absolute_path(promotion_raw, field="EDGEWATCH_INFERENCE_PROMOTION_FILE")
            if promotion_raw
            else None
        )
        if inference_mode == "live" and promotion_file is None:
            raise SatelliteConfigError(
                "EDGEWATCH_INFERENCE_PROMOTION_FILE is required when inference mode is live"
            )
        event_reason = values.get("EDGEWATCH_EVENT_REASON", "sentinel_event").strip().lower()
        if event_reason not in {"sentinel_event", "model_event"}:
            raise SatelliteConfigError("EDGEWATCH_EVENT_REASON must be sentinel_event or model_event")

        result_path = _absolute_path(
            _required_env(values, "EDGEWATCH_SATELLITE_RESULT_PATH"),
            field="EDGEWATCH_SATELLITE_RESULT_PATH",
        )
        ready_path = _absolute_path(
            _required_env(values, "EDGEWATCH_SATELLITE_READY_PATH"),
            field="EDGEWATCH_SATELLITE_READY_PATH",
        )
        gate_state_path = _absolute_path(
            _required_env(values, "EDGEWATCH_SATELLITE_GATE_STATE_PATH"),
            field="EDGEWATCH_SATELLITE_GATE_STATE_PATH",
        )
        lock_path = _absolute_path(
            _required_env(values, "EDGEWATCH_SATELLITE_LOCK_PATH"),
            field="EDGEWATCH_SATELLITE_LOCK_PATH",
        )
        poweroff_request_path = _absolute_path(
            values.get(
                "EDGEWATCH_SATELLITE_POWEROFF_REQUEST_PATH",
                "/run/edgewatch-camera-satellite/poweroff.request",
            ),
            field="EDGEWATCH_SATELLITE_POWEROFF_REQUEST_PATH",
        )
        if poweroff_request_path != Path("/run/edgewatch-camera-satellite/poweroff.request"):
            raise SatelliteConfigError(
                "EDGEWATCH_SATELLITE_POWEROFF_REQUEST_PATH must match the fixed systemd watcher path"
            )
        if len({result_path, ready_path, gate_state_path, lock_path, poweroff_request_path}) != 5:
            raise SatelliteConfigError(
                "result, readiness, gate-state, lock, and poweroff-request paths must be distinct"
            )

        return cls(
            device_id=device_id,
            camera_id=camera_id,
            rtsp_endpoint=_required_env(values, f"MEDIA_RTSP_{camera_id.upper()}_URL"),
            rtsp_credentials_path=_absolute_path(
                _required_env(values, f"MEDIA_RTSP_{camera_id.upper()}_CREDENTIALS_FILE"),
                field=f"MEDIA_RTSP_{camera_id.upper()}_CREDENTIALS_FILE",
            ),
            model_releases_root=_absolute_path(
                _required_env(values, "EDGEWATCH_MODEL_RELEASES_ROOT"),
                field="EDGEWATCH_MODEL_RELEASES_ROOT",
            ),
            model_current_symlink=_absolute_path(
                _required_env(values, "EDGEWATCH_MODEL_CURRENT_SYMLINK"),
                field="EDGEWATCH_MODEL_CURRENT_SYMLINK",
            ),
            model_keyring_dir=_absolute_path(
                _required_env(values, "EDGEWATCH_MODEL_KEYRING_DIR"),
                field="EDGEWATCH_MODEL_KEYRING_DIR",
            ),
            application_releases_root=_absolute_path(
                values.get("EDGEWATCH_RELEASES_ROOT", "/opt/edgewatch/releases"),
                field="EDGEWATCH_RELEASES_ROOT",
            ),
            application_current_symlink=_absolute_path(
                values.get("EDGEWATCH_CURRENT_SYMLINK", "/opt/edgewatch/current"),
                field="EDGEWATCH_CURRENT_SYMLINK",
            ),
            hardware_model=_safe_identifier(
                values.get("EDGEWATCH_HARDWARE_MODEL", "raspberry-pi-zero-2"),
                field="EDGEWATCH_HARDWARE_MODEL",
            ),
            litert_version=values.get("EDGEWATCH_MODEL_LITERT_VERSION", "2.1.6").strip(),
            evidence_dir=_absolute_path(
                _required_env(values, "EDGEWATCH_SATELLITE_EVIDENCE_DIR"),
                field="EDGEWATCH_SATELLITE_EVIDENCE_DIR",
            ),
            evidence_max_bytes=_bounded_int(
                values,
                "EDGEWATCH_SATELLITE_EVIDENCE_MAX_BYTES",
                default=8 * 1024 * 1024 * 1024,
                minimum=32 * 1024 * 1024,
                maximum=1024 * 1024 * 1024 * 1024,
            ),
            result_path=result_path,
            ready_path=ready_path,
            gate_state_path=gate_state_path,
            lock_path=lock_path,
            poweroff_request_path=poweroff_request_path,
            inference_mode=inference_mode,
            promotion_file=promotion_file,
            event_reason=event_reason,
            capture_timeout_s=_bounded_float(
                values,
                "EDGEWATCH_SATELLITE_CAPTURE_TIMEOUT_S",
                default=35.0,
                minimum=5.0,
                maximum=90.0,
            ),
            event_duration_s=_bounded_float(
                values,
                "EDGEWATCH_SATELLITE_EVENT_DURATION_S",
                default=10.0,
                minimum=0.5,
                maximum=30.0,
            ),
            preprocess_timeout_s=_bounded_float(
                values,
                "EDGEWATCH_SATELLITE_PREPROCESS_TIMEOUT_S",
                default=20.0,
                minimum=1.0,
                maximum=60.0,
            ),
            readiness_ttl_s=_bounded_int(
                values,
                "EDGEWATCH_SATELLITE_READINESS_TTL_S",
                default=300,
                minimum=30,
                maximum=3600,
            ),
            ffmpeg_binary=values.get("EDGEWATCH_FFMPEG_BINARY", "ffmpeg").strip() or "ffmpeg",
            ffprobe_binary=values.get("EDGEWATCH_FFPROBE_BINARY", "ffprobe").strip() or "ffprobe",
        )


class CameraRuntime(Protocol):
    def is_supported(self) -> bool:
        raise NotImplementedError

    def probe(self, *, camera_id: str, timeout_s: float | None = None) -> RtspStreamInfo:
        raise NotImplementedError

    def capture_event(self, *, camera_id: str, timeout_s: float | None = None) -> CapturedEventEvidence:
        raise NotImplementedError

    def capture_sample(self, *, camera_id: str, timeout_s: float | None = None) -> CapturedInferenceSample:
        raise NotImplementedError


class TensorPreprocessor(Protocol):
    def validate_specs(self, *, vision_spec: QuantizedInputSpec, audio_spec: QuantizedInputSpec) -> None:
        raise NotImplementedError

    def preprocess(
        self,
        *,
        still_jpeg: bytes,
        audio_wav: bytes,
        vision_spec: QuantizedInputSpec,
        audio_spec: QuantizedInputSpec,
        previous_still_jpeg: bytes | None = None,
    ) -> PreprocessedInputs:
        raise NotImplementedError


@dataclass(frozen=True)
class PreparedRuntime:
    bundle: InstalledModelBundle
    inference: EquipmentInferenceRuntime
    camera: CameraRuntime
    preprocessor: TensorPreprocessor
    store: LocalEvidenceStore
    stream: RtspStreamInfo


def _default_manager(config: SatelliteConfig) -> ModelBundleManager:
    return ModelBundleManager(
        releases_root=config.model_releases_root,
        current_symlink=config.model_current_symlink,
        keyring_dir=config.model_keyring_dir,
        hardware_model=config.hardware_model,
        litert_version=config.litert_version,
    )


def _default_inference(bundle: InstalledModelBundle) -> EquipmentInferenceRuntime:
    return EquipmentInferenceRuntime.load_bundle(bundle, shadow_mode=True)


def _default_camera(config: SatelliteConfig) -> FFmpegRtspBackend:
    return FFmpegRtspBackend(
        {
            config.camera_id: RtspCameraConfig(
                endpoint=config.rtsp_endpoint,
                credentials_path=config.rtsp_credentials_path,
                require_audio=True,
            )
        },
        limits=RtspCaptureLimits(
            connect_timeout_s=min(15.0, config.capture_timeout_s),
            event_duration_s=config.event_duration_s,
        ),
        ffmpeg_binary=config.ffmpeg_binary,
        ffprobe_binary=config.ffprobe_binary,
    )


def _default_preprocessor(bundle: InstalledModelBundle, config: SatelliteConfig) -> FFmpegTensorPreprocessor:
    return FFmpegTensorPreprocessor(
        bundle.preprocessing,
        ffmpeg_binary=config.ffmpeg_binary,
        timeout_s=config.preprocess_timeout_s,
    )


def _default_store(config: SatelliteConfig) -> LocalEvidenceStore:
    return LocalEvidenceStore(
        str(config.evidence_dir),
        max_bytes=config.evidence_max_bytes,
        retention_days=30.0,
    )


def _read_private_json(path: Path, *, maximum_bytes: int, error_code: str) -> Mapping[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SatelliteRunError(error_code) from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid not in {0, os.geteuid()}
            or metadata.st_size <= 0
            or metadata.st_size > maximum_bytes
        ):
            raise SatelliteRunError(error_code)
        payload = os.read(descriptor, maximum_bytes + 1)
    finally:
        os.close(descriptor)
    if len(payload) > maximum_bytes:
        raise SatelliteRunError(error_code)

    def unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        decoded_object: dict[str, Any] = {}
        for key, value in pairs:
            if key in decoded_object:
                raise SatelliteRunError(error_code)
            decoded_object[key] = value
        return decoded_object

    try:
        decoded = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=unique_json_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(SatelliteRunError(error_code)),
        )
    except SatelliteRunError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise SatelliteRunError(error_code) from exc
    if not isinstance(decoded, Mapping):
        raise SatelliteRunError(error_code)
    return decoded


def _promotion_evidence(path: Path) -> PromotionEvidence:
    payload = _read_private_json(path, maximum_bytes=4096, error_code="promotion_evidence_invalid")
    if (
        set(payload)
        != {
            "schema_version",
            "held_out_alert_precision",
            "false_alert_count",
            "device_days",
        }
        or payload.get("schema_version") != 1
    ):
        raise SatelliteRunError("promotion_evidence_invalid")
    precision = payload["held_out_alert_precision"]
    false_alert_count = payload["false_alert_count"]
    device_days = payload["device_days"]
    if (
        isinstance(precision, bool)
        or not isinstance(precision, (int, float))
        or not math.isfinite(float(precision))
        or isinstance(false_alert_count, bool)
        or not isinstance(false_alert_count, int)
        or false_alert_count < 0
        or isinstance(device_days, bool)
        or not isinstance(device_days, (int, float))
        or not math.isfinite(float(device_days))
        or float(device_days) <= 0
    ):
        raise SatelliteRunError("promotion_evidence_invalid")
    return PromotionEvidence(
        held_out_alert_precision=float(precision),
        false_alert_count=false_alert_count,
        device_days=float(device_days),
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    try:
        serialized = (
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise SatelliteRunError("state_write_failed") from exc
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        raise SatelliteRunError("state_write_failed") from exc
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise SatelliteRunError("runner_lock_failed") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid not in {0, os.geteuid()}:
            raise SatelliteRunError("runner_lock_failed")
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SatelliteRunError("runner_busy") from exc
        yield
    finally:
        os.close(descriptor)


def _default_boot_id() -> str:
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError as exc:
        raise SatelliteRunError("readiness_unavailable") from exc
    if _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise SatelliteRunError("readiness_unavailable")
    return value


class CameraSatelliteRunner:
    """One-shot local camera/inference contract for MCU or systemd orchestration."""

    def __init__(
        self,
        config: SatelliteConfig,
        *,
        manager_factory: Callable[[SatelliteConfig], ModelBundleManager] = _default_manager,
        inference_factory: Callable[[InstalledModelBundle], EquipmentInferenceRuntime] = _default_inference,
        camera_factory: Callable[[SatelliteConfig], CameraRuntime] = _default_camera,
        preprocessor_factory: Callable[
            [InstalledModelBundle, SatelliteConfig], TensorPreprocessor
        ] = _default_preprocessor,
        store_factory: Callable[[SatelliteConfig], LocalEvidenceStore] = _default_store,
        known_answer_validator: Callable[[InstalledModelBundle, Mapping[str, Any]], bool] | None = None,
        clock: Callable[[], datetime] = _utcnow,
        boot_id_source: Callable[[], str] = _default_boot_id,
    ) -> None:
        self.config = config
        self._manager_factory = manager_factory
        self._inference_factory = inference_factory
        self._camera_factory = camera_factory
        self._preprocessor_factory = preprocessor_factory
        self._store_factory = store_factory
        self._known_answer_validator = known_answer_validator or validate_known_answer_cases
        self._clock = clock
        self._boot_id_source = boot_id_source

    def run(
        self,
        *,
        mode: RunMode,
        invocation_id: str,
        poweroff_on_success: bool = False,
    ) -> dict[str, Any]:
        if mode not in {"event", "daily", "check"}:
            raise SatelliteRunError("mode_invalid")
        try:
            with _exclusive_lock(self.config.lock_path):
                try:
                    if poweroff_on_success and mode not in {"event", "daily"}:
                        raise SatelliteRunError("poweroff_not_allowed")
                    try:
                        safe_invocation = _safe_identifier(invocation_id, field="invocation_id")
                    except SatelliteConfigError as exc:
                        raise SatelliteRunError("invocation_id_invalid") from exc
                    if self.config.poweroff_request_path.exists():
                        raise SatelliteRunError("poweroff_pending")
                    self._remove_readiness()
                    prepared = self._prepare()
                    if mode == "check":
                        result = self._base_success(prepared, mode=mode, invocation_id=safe_invocation)
                    else:
                        result = self._capture_and_infer(
                            prepared,
                            mode=mode,
                            invocation_id=safe_invocation,
                        )
                    result["poweroff_requested"] = poweroff_on_success
                    try:
                        _write_private_json(self.config.result_path, result)
                    except SatelliteRunError as exc:
                        raise SatelliteRunError("result_write_failed") from exc
                    if poweroff_on_success:
                        assert mode in {"event", "daily"}
                        self._schedule_poweroff(
                            result=result,
                            mode=cast(Literal["event", "daily"], mode),
                            invocation_id=safe_invocation,
                        )
                    return result
                except SatelliteRunError as exc:
                    if exc.code != "poweroff_pending":
                        self._remove_readiness(best_effort=True)
                        failure = _failure_result(
                            mode=mode,
                            invocation_id=invocation_id,
                            error_code=exc.code,
                            config=self.config,
                        )
                        try:
                            _write_private_json(self.config.result_path, failure)
                        except SatelliteRunError:
                            pass
                    raise
                except Exception as exc:
                    self._remove_readiness(best_effort=True)
                    failure = _failure_result(
                        mode=mode,
                        invocation_id=invocation_id,
                        error_code="internal_error",
                        config=self.config,
                    )
                    try:
                        _write_private_json(self.config.result_path, failure)
                    except SatelliteRunError:
                        pass
                    raise SatelliteRunError("internal_error") from exc
        except SatelliteRunError:
            raise
        except Exception as exc:
            raise SatelliteRunError("internal_error") from exc

    def _prepare(self) -> PreparedRuntime:
        try:
            bundle = self._manager_factory(self.config).load_active()
            inference = self._inference_factory(bundle)
            classifiers = {
                "vision": inference.vision_classifier,
                "audio": inference.audio_classifier,
            }
            if not self._known_answer_validator(bundle, classifiers):
                raise SatelliteRunError("model_known_answer_failed")
            preprocessor = self._preprocessor_factory(bundle, self.config)
            preprocessor.validate_specs(
                vision_spec=cast(QuantizedInputSpec, inference.vision_classifier),
                audio_spec=cast(QuantizedInputSpec, inference.audio_classifier),
            )
        except SatelliteRunError:
            raise
        except (
            ModelBundleError,
            QuantizedModelError,
            InferenceUnavailableError,
            PreprocessingError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise SatelliteRunError("model_not_ready") from exc

        if self.config.inference_mode == "live":
            assert self.config.promotion_file is not None
            try:
                inference.enable_live_alerts(_promotion_evidence(self.config.promotion_file))
            except SatelliteRunError:
                raise
            except ValueError as exc:
                raise SatelliteRunError("promotion_evidence_invalid") from exc
        self._restore_gate_state(inference, bundle)

        try:
            camera = self._camera_factory(self.config)
            if not camera.is_supported():
                raise SatelliteRunError("camera_runtime_unavailable")
            stream = camera.probe(
                camera_id=self.config.camera_id,
                timeout_s=min(self.config.capture_timeout_s, 15.0),
            )
        except SatelliteRunError:
            raise
        except (CameraCaptureError, RtspConfigurationError, OSError) as exc:
            raise SatelliteRunError("camera_not_ready") from exc

        try:
            store = self._store_factory(self.config)
            store.prune(now=self._now())
        except (MediaStorageError, OSError, ValueError) as exc:
            raise SatelliteRunError("storage_not_ready") from exc

        prepared = PreparedRuntime(
            bundle=bundle,
            inference=inference,
            camera=camera,
            preprocessor=preprocessor,
            store=store,
            stream=stream,
        )
        self._publish_readiness(prepared)
        return prepared

    def _capture_and_infer(
        self,
        prepared: PreparedRuntime,
        *,
        mode: Literal["event", "daily"],
        invocation_id: str,
    ) -> dict[str, Any]:
        try:
            previous_still = prepared.store.latest_still_bytes(
                device_id=self.config.device_id,
                camera_id=self.config.camera_id,
            )
        except (MediaStorageError, OSError, ValueError) as exc:
            raise SatelliteRunError("storage_failed") from exc
        event: CapturedEventEvidence | None = None
        try:
            if mode == "event":
                event = prepared.camera.capture_event(
                    camera_id=self.config.camera_id,
                    timeout_s=self.config.capture_timeout_s,
                )
                still_jpeg = event.still_jpeg
                audio_wav = event.audio_wav
            else:
                sample = prepared.camera.capture_sample(
                    camera_id=self.config.camera_id,
                    timeout_s=self.config.capture_timeout_s,
                )
                still_jpeg = sample.still_jpeg
                audio_wav = sample.audio_wav
        except (CameraCaptureError, RtspConfigurationError, OSError) as exc:
            raise SatelliteRunError("capture_failed") from exc

        try:
            inputs = prepared.preprocessor.preprocess(
                still_jpeg=still_jpeg,
                audio_wav=audio_wav,
                vision_spec=cast(QuantizedInputSpec, prepared.inference.vision_classifier),
                audio_spec=cast(QuantizedInputSpec, prepared.inference.audio_classifier),
                previous_still_jpeg=previous_still,
            )
        except (PreprocessingError, OSError, ValueError) as exc:
            raise SatelliteRunError("preprocessing_failed") from exc
        try:
            evaluation = prepared.inference.infer(
                vision_input=inputs.vision,
                audio_input=inputs.audio,
                visual_change=inputs.visual_change,
            )
        except (QuantizedModelError, ValueError, RuntimeError) as exc:
            raise SatelliteRunError("inference_failed") from exc

        observed_at = self._now()
        scalars: dict[str, str | float | bool | int] = {
            **evaluation.telemetry_scalars(),
            "alert_reason": evaluation.alert.reason,
            "repeated_observations": evaluation.alert.repeated_observations,
        }
        try:
            if mode == "event":
                assert event is not None
                stored_event = prepared.store.store_event(
                    device_id=self.config.device_id,
                    camera_id=self.config.camera_id,
                    evidence=event,
                    inference=scalars,
                    captured_at=observed_at,
                    reason=self.config.event_reason,
                )
                capture_id: str | None = stored_event.capture_id
                evidence_digest = stored_event.still.metadata.sha256
            else:
                daily_still = prepared.store.store_daily_still(
                    device_id=self.config.device_id,
                    camera_id=self.config.camera_id,
                    still_jpeg=still_jpeg,
                    inference=scalars,
                    captured_at=observed_at,
                )
                capture_id = None
                evidence_digest = daily_still.metadata.sha256
            prepared.store.prune(now=observed_at)
            self._persist_gate_state(prepared.inference, prepared.bundle, observed_at=observed_at)
        except (MediaStorageError, OSError, ValueError) as exc:
            raise SatelliteRunError("storage_failed") from exc

        return self._inference_result(
            prepared,
            evaluation=evaluation,
            mode=mode,
            invocation_id=invocation_id,
            observed_at=observed_at,
            capture_id=capture_id,
            evidence_digest=evidence_digest,
        )

    def _base_success(
        self,
        prepared: PreparedRuntime,
        *,
        mode: RunMode,
        invocation_id: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": "ok",
            "mode": mode,
            "invocation_id": invocation_id,
            "device_id": self.config.device_id,
            "camera_id": self.config.camera_id,
            "observed_at": to_iso_utc(self._now()),
            "model_version": prepared.bundle.manifest.version,
            "manifest_identity": prepared.bundle.manifest.identity,
            "video_codec": prepared.stream.video_codec,
            "audio_codec": prepared.stream.audio_codec,
        }

    def _inference_result(
        self,
        prepared: PreparedRuntime,
        *,
        evaluation: InferenceEvaluation,
        mode: Literal["event", "daily"],
        invocation_id: str,
        observed_at: datetime,
        capture_id: str | None,
        evidence_digest: str,
    ) -> dict[str, Any]:
        result = {
            **self._base_success(prepared, mode=mode, invocation_id=invocation_id),
            "observed_at": to_iso_utc(observed_at),
            **evaluation.output.as_scalars(),
            "alert_eligible": evaluation.alert.eligible,
            "alert_reason": evaluation.alert.reason,
            "repeated_observations": evaluation.alert.repeated_observations,
            "evidence_capture_id": capture_id,
            "evidence_sha256": evidence_digest,
        }
        if set(result) - _RESULT_FIELDS:
            raise SatelliteRunError("result_schema_invalid")
        return result

    def _publish_readiness(self, prepared: PreparedRuntime) -> None:
        issued_at = self._now()
        application_target = self._application_target()
        receipt = {
            "schema_version": 1,
            "status": "ready",
            "device_id": self.config.device_id,
            "camera_id": self.config.camera_id,
            "pid": os.getpid(),
            "boot_id": self._boot_id_source(),
            "issued_at": to_iso_utc(issued_at),
            "valid_until": to_iso_utc(issued_at + timedelta(seconds=self.config.readiness_ttl_s)),
            "model_version": prepared.bundle.manifest.version,
            "manifest_identity": prepared.bundle.manifest.identity,
            "inference_mode": self.config.inference_mode,
            "known_answers_valid": True,
            "preprocessing_valid": True,
            "video_codec": prepared.stream.video_codec,
            "audio_codec": prepared.stream.audio_codec,
            "local_media_only": True,
            "application_target": str(application_target),
        }
        try:
            _write_private_json(self.config.ready_path, receipt)
        except SatelliteRunError as exc:
            raise SatelliteRunError("readiness_write_failed") from exc

    def _application_target(self) -> Path:
        current = self.config.application_current_symlink
        try:
            releases = self.config.application_releases_root.resolve()
            metadata = current.lstat()
            target = current.resolve(strict=True)
            baked_target = _BAKED_APPLICATION_TARGET.resolve(strict=False)
        except OSError as exc:
            raise SatelliteRunError("application_release_invalid") from exc
        if (
            not stat.S_ISLNK(metadata.st_mode)
            or not target.is_dir()
            or (target.parent != releases and target != baked_target)
        ):
            raise SatelliteRunError("application_release_invalid")
        return target

    def _restore_gate_state(
        self,
        inference: EquipmentInferenceRuntime,
        bundle: InstalledModelBundle,
    ) -> None:
        path = self.config.gate_state_path
        if not path.exists() and not path.is_symlink():
            return
        payload = _read_private_json(path, maximum_bytes=4096, error_code="gate_state_invalid")
        if (
            set(payload)
            != {
                "schema_version",
                "model_version",
                "inference_mode",
                "candidate",
                "observations",
                "updated_at",
            }
            or payload.get("schema_version") != 1
        ):
            raise SatelliteRunError("gate_state_invalid")
        if (
            payload.get("model_version") != bundle.manifest.version
            or payload.get("inference_mode") != self.config.inference_mode
        ):
            return
        candidate = payload.get("candidate")
        observations = payload.get("observations")
        try:
            inference.alert_gate.restore(
                AlertGateSnapshot(
                    candidate=cast(Any, candidate),
                    observations=cast(int, observations),
                )
            )
        except ValueError as exc:
            raise SatelliteRunError("gate_state_invalid") from exc

    def _persist_gate_state(
        self,
        inference: EquipmentInferenceRuntime,
        bundle: InstalledModelBundle,
        *,
        observed_at: datetime,
    ) -> None:
        snapshot = inference.alert_gate.snapshot()
        payload = {
            "schema_version": 1,
            "model_version": bundle.manifest.version,
            "inference_mode": self.config.inference_mode,
            "candidate": snapshot.candidate,
            "observations": snapshot.observations,
            "updated_at": to_iso_utc(observed_at),
        }
        try:
            _write_private_json(self.config.gate_state_path, payload)
        except SatelliteRunError as exc:
            raise SatelliteRunError("gate_state_write_failed") from exc

    def _remove_readiness(self, *, best_effort: bool = False) -> None:
        try:
            self.config.ready_path.unlink(missing_ok=True)
        except OSError as exc:
            if not best_effort:
                raise SatelliteRunError("readiness_cleanup_failed") from exc

    def _schedule_poweroff(
        self,
        *,
        result: Mapping[str, Any],
        mode: Literal["event", "daily"],
        invocation_id: str,
    ) -> None:
        result_bytes = (
            json.dumps(
                result,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
            + b"\n"
        )
        request = {
            "schema_version": 1,
            "status": "poweroff_requested",
            "mode": mode,
            "invocation_id": invocation_id,
            "device_id": self.config.device_id,
            "pid": os.getpid(),
            "boot_id": self._boot_id_source(),
            "requested_at": to_iso_utc(self._now()),
            "result_sha256": hashlib.sha256(result_bytes).hexdigest(),
        }
        try:
            _write_private_json(self.config.poweroff_request_path, request)
        except SatelliteRunError as exc:
            raise SatelliteRunError("poweroff_schedule_failed") from exc

    def _now(self) -> datetime:
        current = self._clock()
        if current.tzinfo is None:
            raise SatelliteRunError("clock_invalid")
        return current.astimezone(timezone.utc)


def _failure_result(
    *,
    mode: str,
    invocation_id: str,
    error_code: str,
    config: SatelliteConfig | None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "failed",
        "mode": mode if mode in {"event", "daily", "check"} else "invalid",
        "invocation_id": invocation_id if _SAFE_IDENTIFIER.fullmatch(invocation_id) else "invalid",
        "device_id": config.device_id if config is not None else "unknown",
        "camera_id": config.camera_id if config is not None else "unknown",
        "observed_at": to_iso_utc(_utcnow()),
        "error_code": error_code,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one local EdgeWatch camera-satellite cycle")
    parser.add_argument("--mode", choices=("event", "daily", "check"), required=True)
    parser.add_argument(
        "--invocation-id",
        help="Safe MCU/LoRa correlation ID; generated when omitted",
    )
    parser.add_argument(
        "--poweroff-on-success",
        action="store_true",
        help="For event/daily wake cycles only, request fixed clean Linux poweroff after result commit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    mode = cast(RunMode, arguments.mode)
    invocation_id = arguments.invocation_id or os.getenv(
        "EDGEWATCH_SATELLITE_INVOCATION_ID", uuid.uuid4().hex
    )
    config: SatelliteConfig | None = None
    try:
        config = SatelliteConfig.from_env()
        result = CameraSatelliteRunner(config).run(
            mode=mode,
            invocation_id=invocation_id,
            poweroff_on_success=bool(arguments.poweroff_on_success),
        )
    except SatelliteConfigError:
        result = _failure_result(
            mode=mode,
            invocation_id=invocation_id,
            error_code="config_invalid",
            config=config,
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
        return 2
    except SatelliteRunError as exc:
        result = _failure_result(
            mode=mode,
            invocation_id=invocation_id,
            error_code=exc.code,
            config=config,
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
