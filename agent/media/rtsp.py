from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote, urlsplit, urlunsplit

from .capture import CameraCaptureError, CapturedPhoto
from .evidence import CapturedEventEvidence, CapturedInferenceSample

_AUDIO_CODECS = frozenset({"aac", "pcm_alaw", "pcm_mulaw"})
_PROTOCOL_WHITELIST = "pipe,rtsp,tcp,udp,rtp"
_MAX_SECRET_BYTES = 4096
_MAX_PROBE_BYTES = 64 * 1024
_MAX_ENDPOINT_CHARACTERS = 2048


class RtspConfigurationError(ValueError):
    """Raised when an RTSP endpoint or credential file is unsafe."""


@dataclass(frozen=True)
class RtspCameraConfig:
    endpoint: str
    credentials_path: Path
    require_audio: bool = True


@dataclass(frozen=True)
class RtspStreamInfo:
    video_codec: str
    audio_codec: str | None


@dataclass(frozen=True)
class RtspCaptureLimits:
    connect_timeout_s: float = 15.0
    event_duration_s: float = 10.0
    max_photo_bytes: int = 5 * 1024 * 1024
    max_audio_bytes: int = 4 * 1024 * 1024
    max_clip_bytes: int = 20 * 1024 * 1024

    def __post_init__(self) -> None:
        if not (1.0 <= self.connect_timeout_s <= 90.0):
            raise ValueError("connect_timeout_s must be within 1..90 seconds")
        if not (0.5 <= self.event_duration_s <= 30.0):
            raise ValueError("event_duration_s must be within 0.5..30 seconds")
        for field_name in ("max_photo_bytes", "max_audio_bytes", "max_clip_bytes"):
            if int(getattr(self, field_name)) < 1024:
                raise ValueError(f"{field_name} must be at least 1024 bytes")


def _validate_public_endpoint(endpoint: str) -> str:
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise RtspConfigurationError("RTSP endpoint must be non-empty")
    normalized = endpoint.strip()
    if len(normalized) > _MAX_ENDPOINT_CHARACTERS:
        raise RtspConfigurationError("RTSP endpoint exceeds the size limit")
    if any(
        char in {"'", "\\"} or char.isspace() or ord(char) < 32 or ord(char) == 127 for char in normalized
    ):
        raise RtspConfigurationError("RTSP endpoint contains unsupported characters")
    try:
        parsed = urlsplit(normalized)
    except ValueError as exc:
        raise RtspConfigurationError("RTSP endpoint is malformed") from exc
    if parsed.scheme.lower() != "rtsp" or not parsed.hostname:
        raise RtspConfigurationError("RTSP endpoint must use rtsp:// and include a host")
    if parsed.username is not None or parsed.password is not None:
        raise RtspConfigurationError("RTSP credentials must be supplied only through the secret file")
    if parsed.fragment:
        raise RtspConfigurationError("RTSP endpoint must not include a fragment")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise RtspConfigurationError("RTSP endpoint contains an invalid port") from exc
    return normalized


def _read_credentials(path: Path) -> tuple[str, str]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RtspConfigurationError("RTSP credential secret file cannot be opened safely") from exc

    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RtspConfigurationError("RTSP credential secret must be a regular file")
        if metadata.st_size <= 0 or metadata.st_size > _MAX_SECRET_BYTES:
            raise RtspConfigurationError("RTSP credential secret size is outside the allowed range")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise RtspConfigurationError("RTSP credential secret must have mode 0600")
        if metadata.st_uid not in {0, os.geteuid()}:
            raise RtspConfigurationError("RTSP credential secret must be owned by root or the service user")
        payload = os.read(descriptor, _MAX_SECRET_BYTES + 1)
    finally:
        os.close(descriptor)

    if len(payload) > _MAX_SECRET_BYTES:
        raise RtspConfigurationError("RTSP credential secret exceeds the size limit")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RtspConfigurationError("RTSP credential secret contains duplicate keys")
            result[key] = value
        return result

    try:
        raw = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                RtspConfigurationError("RTSP credential secret contains an invalid number")
            ),
        )
    except RtspConfigurationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RtspConfigurationError("RTSP credential secret must contain valid JSON") from exc
    if not isinstance(raw, Mapping) or set(raw) != {"username", "password"}:
        raise RtspConfigurationError("RTSP credential secret must contain exactly username and password")
    username = raw.get("username")
    password = raw.get("password")
    if not isinstance(username, str) or not username or len(username) > 256:
        raise RtspConfigurationError("RTSP username is invalid")
    if not isinstance(password, str) or not password or len(password) > 256:
        raise RtspConfigurationError("RTSP password is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in username + password):
        raise RtspConfigurationError("RTSP credentials contain control characters")
    return username, password


def _authenticated_url(endpoint: str, username: str, password: str) -> str:
    parsed = urlsplit(endpoint)
    hostname = parsed.hostname or ""
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    if parsed.port is not None:
        rendered_host = f"{rendered_host}:{parsed.port}"
    userinfo = f"{quote(username, safe='')}:{quote(password, safe='')}"
    return urlunsplit((parsed.scheme, f"{userinfo}@{rendered_host}", parsed.path, parsed.query, ""))


def _concat_input(url: str) -> bytes:
    # The URL, including credentials, is delivered over stdin to the concat
    # demuxer. It therefore never appears in process arguments or error text.
    return f"ffconcat version 1.0\nfile '{url}'\n".encode("utf-8")


def _safe_process_environment() -> dict[str, str]:
    environment = dict(os.environ)
    # FFmpeg's opt-in report file can include input URLs. Never allow a host
    # setting to turn credential-bearing RTSP input into a persistent log.
    environment.pop("FFREPORT", None)
    return environment


def _read_bounded_file(path: Path, *, maximum_bytes: int, label: str) -> bytes:
    try:
        metadata = path.stat()
    except OSError as exc:
        raise CameraCaptureError(f"RTSP capture did not produce {label}") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise CameraCaptureError(f"RTSP capture produced an unsafe {label} file")
    if metadata.st_size <= 0:
        raise CameraCaptureError(f"RTSP capture produced empty {label}")
    if metadata.st_size > maximum_bytes:
        raise CameraCaptureError(f"RTSP capture exceeded the {label} size limit")
    with path.open("rb") as handle:
        payload = handle.read(maximum_bytes + 1)
    if len(payload) > maximum_bytes:
        raise CameraCaptureError(f"RTSP capture exceeded the {label} size limit")
    return payload


class FFmpegRtspBackend:
    """Bounded FFmpeg/FFprobe backend for local authenticated RTSP cameras."""

    def __init__(
        self,
        cameras: Mapping[str, RtspCameraConfig],
        *,
        limits: RtspCaptureLimits | None = None,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        run_command: Callable[..., Any] = subprocess.run,
    ) -> None:
        if not cameras:
            raise RtspConfigurationError("at least one RTSP camera must be configured")
        normalized: dict[str, RtspCameraConfig] = {}
        for raw_camera_id, config in cameras.items():
            camera_id = raw_camera_id.strip().lower()
            if not camera_id or camera_id in normalized:
                raise RtspConfigurationError("RTSP camera IDs must be unique and non-empty")
            normalized[camera_id] = RtspCameraConfig(
                endpoint=_validate_public_endpoint(config.endpoint),
                credentials_path=Path(config.credentials_path),
                require_audio=bool(config.require_audio),
            )
        self.cameras = normalized
        self.limits = limits or RtspCaptureLimits()
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary
        self._run_command = run_command

    def is_supported(self) -> bool:
        return shutil.which(self.ffmpeg_binary) is not None and shutil.which(self.ffprobe_binary) is not None

    def capture_photo(self, *, camera_id: str, timeout_s: float) -> CapturedPhoto:
        config = self._camera(camera_id)
        timeout = self._bounded_timeout(timeout_s)
        with tempfile.TemporaryDirectory(prefix="edgewatch-rtsp-") as temp_dir:
            output_path = Path(temp_dir) / "still.jpg"
            self._run_ffmpeg(
                config=config,
                timeout_s=timeout,
                output_args=[
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    "-an",
                    "-c:v",
                    "mjpeg",
                    "-q:v",
                    "3",
                    "-fs",
                    str(self.limits.max_photo_bytes),
                    str(output_path),
                ],
            )
            payload = _read_bounded_file(
                output_path,
                maximum_bytes=self.limits.max_photo_bytes,
                label="still image",
            )
        return CapturedPhoto(payload=payload, mime_type="image/jpeg")

    def probe(self, *, camera_id: str, timeout_s: float | None = None) -> RtspStreamInfo:
        config = self._camera(camera_id)
        timeout = self._bounded_timeout(timeout_s or self.limits.connect_timeout_s)
        command = [
            self._resolve_binary(self.ffprobe_binary, label="ffprobe"),
            "-v",
            "error",
            "-timeout",
            str(int(timeout * 1_000_000)),
            "-f",
            "concat",
            "-safe",
            "0",
            "-protocol_whitelist",
            _PROTOCOL_WHITELIST,
            "-i",
            "pipe:0",
            "-show_entries",
            "stream=codec_type,codec_name",
            "-of",
            "json",
        ]
        secret_input = self._secret_input(config)
        try:
            completed = self._run_command(
                command,
                input=secret_input,
                env=_safe_process_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CameraCaptureError(f"RTSP probe timed out for {camera_id}") from exc
        if int(completed.returncode) != 0:
            raise CameraCaptureError(f"RTSP probe failed for {camera_id}")
        raw_stdout = completed.stdout
        if not isinstance(raw_stdout, (bytes, bytearray)) or len(raw_stdout) > _MAX_PROBE_BYTES:
            raise CameraCaptureError(f"RTSP probe returned an invalid response for {camera_id}")
        try:
            payload = json.loads(bytes(raw_stdout).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CameraCaptureError(f"RTSP probe returned invalid JSON for {camera_id}") from exc
        if not isinstance(payload, Mapping) or not isinstance(payload.get("streams"), list):
            raise CameraCaptureError(f"RTSP probe response is missing streams for {camera_id}")
        streams = payload["streams"]
        if len(streams) > 16:
            raise CameraCaptureError(f"RTSP probe returned too many streams for {camera_id}")
        video_codecs = [
            stream.get("codec_name")
            for stream in streams
            if isinstance(stream, Mapping) and stream.get("codec_type") == "video"
        ]
        audio_codecs = [
            stream.get("codec_name")
            for stream in streams
            if isinstance(stream, Mapping) and stream.get("codec_type") == "audio"
        ]
        if "h264" not in video_codecs:
            raise CameraCaptureError(f"RTSP camera {camera_id} does not expose H.264 video")
        audio_codec = next(
            (str(codec) for codec in audio_codecs if isinstance(codec, str) and codec in _AUDIO_CODECS),
            None,
        )
        if config.require_audio and audio_codec is None:
            raise CameraCaptureError(f"RTSP camera {camera_id} does not expose AAC or G.711 audio")
        return RtspStreamInfo(video_codec="h264", audio_codec=audio_codec)

    def capture_event(
        self,
        *,
        camera_id: str,
        timeout_s: float | None = None,
    ) -> CapturedEventEvidence:
        config = self._camera(camera_id)
        timeout = self._bounded_timeout(
            timeout_s or self.limits.connect_timeout_s + self.limits.event_duration_s
        )
        started_at = time.monotonic()
        self.probe(camera_id=camera_id, timeout_s=min(timeout, self.limits.connect_timeout_s))
        remaining_timeout = timeout - (time.monotonic() - started_at)
        if remaining_timeout <= 0:
            raise CameraCaptureError("RTSP event capture timed out")

        with tempfile.TemporaryDirectory(prefix="edgewatch-rtsp-event-") as temp_dir:
            root = Path(temp_dir)
            still_path = root / "still.jpg"
            clip_path = root / "clip.mkv"
            audio_path = root / "audio.wav"
            duration = f"{self.limits.event_duration_s:.3f}"
            self._run_ffmpeg(
                config=config,
                timeout_s=remaining_timeout,
                output_args=[
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    "-an",
                    "-c:v",
                    "mjpeg",
                    "-q:v",
                    "3",
                    "-fs",
                    str(self.limits.max_photo_bytes),
                    str(still_path),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0",
                    "-t",
                    duration,
                    "-c:v",
                    "copy",
                    "-c:a",
                    "copy",
                    "-fs",
                    str(self.limits.max_clip_bytes),
                    "-f",
                    "matroska",
                    str(clip_path),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-t",
                    duration,
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    "-fs",
                    str(self.limits.max_audio_bytes),
                    "-f",
                    "wav",
                    str(audio_path),
                ],
            )
            still = _read_bounded_file(
                still_path,
                maximum_bytes=self.limits.max_photo_bytes,
                label="event still",
            )
            clip = _read_bounded_file(
                clip_path,
                maximum_bytes=self.limits.max_clip_bytes,
                label="event clip",
            )
            audio = _read_bounded_file(
                audio_path,
                maximum_bytes=self.limits.max_audio_bytes,
                label="event audio",
            )
        return CapturedEventEvidence(
            still_jpeg=still,
            audio_wav=audio,
            clip_matroska=clip,
        )

    def capture_sample(
        self,
        *,
        camera_id: str,
        timeout_s: float | None = None,
    ) -> CapturedInferenceSample:
        """Capture a bounded still plus WAV without retaining an event clip."""

        config = self._camera(camera_id)
        timeout = self._bounded_timeout(
            timeout_s or self.limits.connect_timeout_s + self.limits.event_duration_s
        )
        started_at = time.monotonic()
        self.probe(camera_id=camera_id, timeout_s=min(timeout, self.limits.connect_timeout_s))
        remaining_timeout = timeout - (time.monotonic() - started_at)
        if remaining_timeout <= 0:
            raise CameraCaptureError("RTSP sample capture timed out")

        with tempfile.TemporaryDirectory(prefix="edgewatch-rtsp-sample-") as temp_dir:
            root = Path(temp_dir)
            still_path = root / "still.jpg"
            audio_path = root / "audio.wav"
            duration = f"{self.limits.event_duration_s:.3f}"
            self._run_ffmpeg(
                config=config,
                timeout_s=remaining_timeout,
                output_args=[
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    "-an",
                    "-c:v",
                    "mjpeg",
                    "-q:v",
                    "3",
                    "-fs",
                    str(self.limits.max_photo_bytes),
                    str(still_path),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-t",
                    duration,
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    "-fs",
                    str(self.limits.max_audio_bytes),
                    "-f",
                    "wav",
                    str(audio_path),
                ],
            )
            still = _read_bounded_file(
                still_path,
                maximum_bytes=self.limits.max_photo_bytes,
                label="sample still",
            )
            audio = _read_bounded_file(
                audio_path,
                maximum_bytes=self.limits.max_audio_bytes,
                label="sample audio",
            )
        return CapturedInferenceSample(still_jpeg=still, audio_wav=audio)

    def _run_ffmpeg(
        self,
        *,
        config: RtspCameraConfig,
        timeout_s: float,
        output_args: list[str],
    ) -> None:
        command = [
            self._resolve_binary(self.ffmpeg_binary, label="ffmpeg"),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-timeout",
            str(int(timeout_s * 1_000_000)),
            "-f",
            "concat",
            "-safe",
            "0",
            "-protocol_whitelist",
            _PROTOCOL_WHITELIST,
            "-i",
            "pipe:0",
            *output_args,
        ]
        secret_input = self._secret_input(config)
        try:
            completed = self._run_command(
                command,
                input=secret_input,
                env=_safe_process_environment(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CameraCaptureError("RTSP capture timed out") from exc
        if int(completed.returncode) != 0:
            raise CameraCaptureError("RTSP capture failed")

    def _secret_input(self, config: RtspCameraConfig) -> bytes:
        username, password = _read_credentials(config.credentials_path)
        return _concat_input(_authenticated_url(config.endpoint, username, password))

    def _camera(self, camera_id: str) -> RtspCameraConfig:
        normalized = camera_id.strip().lower()
        try:
            return self.cameras[normalized]
        except KeyError as exc:
            raise CameraCaptureError(f"unknown RTSP camera id '{camera_id}'") from exc

    def _bounded_timeout(self, requested_s: float) -> float:
        timeout = float(requested_s)
        if timeout <= 0:
            raise CameraCaptureError("RTSP timeout must be > 0")
        maximum = self.limits.connect_timeout_s + self.limits.event_duration_s + 5.0
        return min(timeout, maximum)

    @staticmethod
    def _resolve_binary(binary: str, *, label: str) -> str:
        resolved = shutil.which(binary)
        if resolved is None:
            raise CameraCaptureError(f"{label} is not installed")
        return resolved
