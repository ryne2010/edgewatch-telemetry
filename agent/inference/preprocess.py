from __future__ import annotations

import cmath
import math
import shutil
import stat
import struct
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol


class PreprocessingError(RuntimeError):
    """Captured evidence could not be converted into the signed tensor contract."""


class QuantizedInputSpec(Protocol):
    @property
    def input_shape(self) -> tuple[int, ...]:
        raise NotImplementedError

    @property
    def input_dtype(self) -> str:
        raise NotImplementedError

    @property
    def input_quantization(self) -> tuple[float, int]:
        raise NotImplementedError


@dataclass(frozen=True)
class PreprocessedInputs:
    vision: tuple[int, ...]
    audio: tuple[int, ...]
    visual_change: float


def _product(values: tuple[int, ...]) -> int:
    result = 1
    for value in values:
        result *= value
    return result


def _quantize(
    values: list[float],
    *,
    spec: QuantizedInputSpec,
    deadline: float,
) -> tuple[int, ...]:
    scale, zero_point = spec.input_quantization
    if not math.isfinite(scale) or scale <= 0:
        raise PreprocessingError("model input quantization scale must be positive")
    dtype = spec.input_dtype
    if dtype != "int8":
        raise PreprocessingError(f"model input must use signed int8, not {dtype}")
    if len(values) != _product(spec.input_shape):
        raise PreprocessingError("preprocessed values do not match the model input shape")
    result: list[int] = []
    for index, value in enumerate(values):
        if index % 4096 == 0 and time.monotonic() >= deadline:
            raise PreprocessingError("tensor preprocessing timed out")
        if not math.isfinite(value):
            raise PreprocessingError("preprocessing produced a non-finite value")
        quantized = round(value / scale + zero_point)
        result.append(max(-128, min(127, quantized)))
    return tuple(result)


def _fft_power(samples: list[float], *, fft_size: int, deadline: float) -> list[float]:
    values = [complex(value, 0.0) for value in samples]
    values.extend([0j] * (fft_size - len(values)))

    target = 0
    for index in range(1, fft_size):
        bit = fft_size >> 1
        while target & bit:
            target ^= bit
            bit >>= 1
        target ^= bit
        if index < target:
            values[index], values[target] = values[target], values[index]

    length = 2
    while length <= fft_size:
        if time.monotonic() >= deadline:
            raise PreprocessingError("tensor preprocessing timed out")
        root = cmath.exp(-2j * math.pi / length)
        half = length // 2
        for start in range(0, fft_size, length):
            weight = 1 + 0j
            for offset in range(half):
                even = values[start + offset]
                odd = values[start + offset + half] * weight
                values[start + offset] = even + odd
                values[start + offset + half] = even - odd
                weight *= root
        length *= 2
    return [abs(value) ** 2 / fft_size for value in values[: fft_size // 2 + 1]]


def _hz_to_mel(value: float) -> float:
    return 2595.0 * math.log10(1.0 + value / 700.0)


def _mel_to_hz(value: float) -> float:
    return 700.0 * (10 ** (value / 2595.0) - 1.0)


def _mel_bins(
    *,
    sample_rate_hz: int,
    fft_size: int,
    count: int,
    lower_hz: float,
    upper_hz: float,
) -> tuple[tuple[int, int, int], ...]:
    low_mel = _hz_to_mel(lower_hz)
    high_mel = _hz_to_mel(upper_hz)
    points = [_mel_to_hz(low_mel + index * (high_mel - low_mel) / (count + 1)) for index in range(count + 2)]
    maximum_bin = fft_size // 2
    bins = [max(0, min(maximum_bin, math.floor((fft_size + 1) * point / sample_rate_hz))) for point in points]
    triangles: list[tuple[int, int, int]] = []
    for index in range(count):
        left, center, right = bins[index : index + 3]
        center = max(center, left + 1)
        right = max(right, center + 1)
        right = min(right, maximum_bin)
        center = min(center, right - 1)
        left = min(left, center - 1)
        if not 0 <= left < center < right <= maximum_bin:
            raise PreprocessingError("signed mel filter configuration collapses FFT bins")
        triangles.append((left, center, right))
    return tuple(triangles)


def _log_mel_features(
    samples: list[int],
    config: Mapping[str, Any],
    *,
    deadline: float,
) -> list[float]:
    sample_rate = int(config["sample_rate_hz"])
    sample_count = int(config["sample_count"])
    window_samples = int(config["window_samples"])
    hop_samples = int(config["hop_samples"])
    fft_size = int(config["fft_size"])
    mel_count = int(config["mel_bins"])
    log_floor = float(config["log_floor"])
    if len(samples) != sample_count:
        raise PreprocessingError("FFmpeg audio output does not match signed sample_count")
    frame_count = 1 + (sample_count - window_samples) // hop_samples
    window = [
        0.5 - 0.5 * math.cos(2.0 * math.pi * index / (window_samples - 1)) for index in range(window_samples)
    ]
    triangles = _mel_bins(
        sample_rate_hz=sample_rate,
        fft_size=fft_size,
        count=mel_count,
        lower_hz=float(config["lower_hz"]),
        upper_hz=float(config["upper_hz"]),
    )
    features: list[float] = []
    for frame_index in range(frame_count):
        if time.monotonic() >= deadline:
            raise PreprocessingError("tensor preprocessing timed out")
        start = frame_index * hop_samples
        frame = [samples[start + index] / 32768.0 * window[index] for index in range(window_samples)]
        power = _fft_power(frame, fft_size=fft_size, deadline=deadline)
        for left, center, right in triangles:
            energy = 0.0
            for index in range(left, center):
                energy += power[index] * (index - left) / (center - left)
            for index in range(center, right + 1):
                energy += power[index] * (right - index) / (right - center)
            features.append(math.log(max(log_floor, energy)))
    return features


class FFmpegTensorPreprocessor:
    """Deterministic, bounded media-to-quantized-tensor preprocessing."""

    def __init__(
        self,
        preprocessing: Mapping[str, Mapping[str, Any]],
        *,
        ffmpeg_binary: str = "ffmpeg",
        timeout_s: float = 20.0,
        run_command: Callable[..., Any] = subprocess.run,
    ) -> None:
        if set(preprocessing) != {"vision", "audio"}:
            raise PreprocessingError("signed preprocessing must contain vision and audio")
        if not 1.0 <= timeout_s <= 60.0:
            raise PreprocessingError("preprocessing timeout must be within 1..60 seconds")
        self.preprocessing = {
            "vision": dict(preprocessing["vision"]),
            "audio": dict(preprocessing["audio"]),
        }
        self.ffmpeg_binary = ffmpeg_binary
        self.timeout_s = float(timeout_s)
        self._run_command = run_command

    def validate_specs(
        self,
        *,
        vision_spec: QuantizedInputSpec,
        audio_spec: QuantizedInputSpec,
    ) -> None:
        vision_config = self.preprocessing["vision"]
        expected_vision_shape = (
            1,
            int(vision_config["height"]),
            int(vision_config["width"]),
            int(vision_config["channels"]),
        )
        if vision_spec.input_shape != expected_vision_shape:
            raise PreprocessingError(
                f"vision model input shape must be {expected_vision_shape}, got {vision_spec.input_shape}"
            )

        audio_config = self.preprocessing["audio"]
        frame_count = 1 + (int(audio_config["sample_count"]) - int(audio_config["window_samples"])) // int(
            audio_config["hop_samples"]
        )
        expected_audio_shape = (1, frame_count, int(audio_config["mel_bins"]), 1)
        if audio_spec.input_shape != expected_audio_shape:
            raise PreprocessingError(
                f"audio model input shape must be {expected_audio_shape}, got {audio_spec.input_shape}"
            )
        _mel_bins(
            sample_rate_hz=int(audio_config["sample_rate_hz"]),
            fft_size=int(audio_config["fft_size"]),
            count=int(audio_config["mel_bins"]),
            lower_hz=float(audio_config["lower_hz"]),
            upper_hz=float(audio_config["upper_hz"]),
        )
        for label, spec in (("vision", vision_spec), ("audio", audio_spec)):
            dtype = spec.input_dtype
            if dtype != "int8":
                raise PreprocessingError(f"{label} model input must use signed int8, not {dtype}")
            scale, zero_point = spec.input_quantization
            if not math.isfinite(scale) or scale <= 0 or isinstance(zero_point, bool):
                raise PreprocessingError(f"{label} model input quantization is invalid")
            if not isinstance(zero_point, int) or not -128 <= zero_point <= 127:
                raise PreprocessingError(f"{label} model input quantization is invalid")

    def preprocess(
        self,
        *,
        still_jpeg: bytes,
        audio_wav: bytes,
        vision_spec: QuantizedInputSpec,
        audio_spec: QuantizedInputSpec,
        previous_still_jpeg: bytes | None = None,
    ) -> PreprocessedInputs:
        self.validate_specs(vision_spec=vision_spec, audio_spec=audio_spec)
        deadline = time.monotonic() + self.timeout_s
        current_pixels = self._vision_pixels(
            still_jpeg,
            vision_spec=vision_spec,
            deadline=deadline,
        )
        previous_pixels = (
            self._vision_pixels(
                previous_still_jpeg,
                vision_spec=vision_spec,
                deadline=deadline,
            )
            if previous_still_jpeg is not None
            else None
        )
        vision_config = self.preprocessing["vision"]
        value_scale = float(vision_config["value_scale"])
        value_offset = float(vision_config["value_offset"])
        vision_real: list[float] = []
        for index, pixel in enumerate(current_pixels):
            if index % 4096 == 0 and time.monotonic() >= deadline:
                raise PreprocessingError("tensor preprocessing timed out")
            vision_real.append(pixel * value_scale + value_offset)
        audio_samples = self._audio_samples(audio_wav, deadline=deadline)
        audio_config = self.preprocessing["audio"]
        audio_features = _log_mel_features(audio_samples, audio_config, deadline=deadline)
        visual_change = 0.0
        if previous_pixels is not None:
            if len(previous_pixels) != len(current_pixels):
                raise PreprocessingError("previous still preprocessing shape changed")
            change_sum = 0
            for index, (current, previous) in enumerate(zip(current_pixels, previous_pixels)):
                if index % 4096 == 0 and time.monotonic() >= deadline:
                    raise PreprocessingError("tensor preprocessing timed out")
                change_sum += abs(current - previous)
            visual_change = change_sum / (255.0 * len(current_pixels))
        return PreprocessedInputs(
            vision=_quantize(vision_real, spec=vision_spec, deadline=deadline),
            audio=_quantize(audio_features, spec=audio_spec, deadline=deadline),
            visual_change=round(visual_change, 6),
        )

    def _vision_pixels(
        self,
        still_jpeg: bytes,
        *,
        vision_spec: QuantizedInputSpec,
        deadline: float,
    ) -> bytes:
        if not still_jpeg or len(still_jpeg) > 5 * 1024 * 1024:
            raise PreprocessingError("captured still size is outside the allowed range")
        config = self.preprocessing["vision"]
        width = int(config["width"])
        height = int(config["height"])
        channels = int(config["channels"])
        expected_shape = (1, height, width, channels)
        if vision_spec.input_shape != expected_shape:
            raise PreprocessingError(
                f"vision model input shape must be {expected_shape}, got {vision_spec.input_shape}"
            )
        pixel_format = "gray" if channels == 1 else "rgb24"
        expected_bytes = width * height * channels
        resize_filter = str(config["resize_filter"])
        return self._run_ffmpeg(
            input_bytes=still_jpeg,
            input_suffix=".jpg",
            output_suffix=".rgb",
            expected_bytes=expected_bytes,
            timeout_s=self._remaining(deadline),
            output_args=[
                "-an",
                "-vf",
                f"scale={width}:{height}:flags={resize_filter}+accurate_rnd+bitexact,format={pixel_format}",
                "-frames:v",
                "1",
                "-pix_fmt",
                pixel_format,
                "-f",
                "rawvideo",
            ],
        )

    def _audio_samples(self, audio_wav: bytes, *, deadline: float) -> list[int]:
        if not audio_wav or len(audio_wav) > 4 * 1024 * 1024:
            raise PreprocessingError("captured audio size is outside the allowed range")
        config = self.preprocessing["audio"]
        sample_rate = int(config["sample_rate_hz"])
        sample_count = int(config["sample_count"])
        raw = self._run_ffmpeg(
            input_bytes=audio_wav,
            input_suffix=".wav",
            output_suffix=".pcm",
            expected_bytes=sample_count * 2,
            timeout_s=self._remaining(deadline),
            output_args=[
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-af",
                (
                    f"aresample={sample_rate}:osf=s16:resampler=swr:dither_method=none:first_pts=0,"
                    f"apad=whole_len={sample_count},atrim=end_sample={sample_count}"
                ),
                "-c:a",
                "pcm_s16le",
                "-f",
                "s16le",
            ],
        )
        return list(struct.unpack(f"<{sample_count}h", raw))

    def _run_ffmpeg(
        self,
        *,
        input_bytes: bytes,
        input_suffix: str,
        output_suffix: str,
        expected_bytes: int,
        timeout_s: float,
        output_args: list[str],
    ) -> bytes:
        ffmpeg = shutil.which(self.ffmpeg_binary)
        if ffmpeg is None:
            raise PreprocessingError("ffmpeg is not installed")
        with tempfile.TemporaryDirectory(prefix="edgewatch-preprocess-") as temp_dir:
            root = Path(temp_dir)
            input_path = root / f"input{input_suffix}"
            output_path = root / f"output{output_suffix}"
            input_path.write_bytes(input_bytes)
            input_path.chmod(0o600)
            command = [
                ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-threads",
                "1",
                "-filter_threads",
                "1",
                "-filter_complex_threads",
                "1",
                "-fflags",
                "+bitexact",
                "-i",
                str(input_path),
                *output_args,
                "-fs",
                str(expected_bytes),
                str(output_path),
            ]
            try:
                completed = self._run_command(
                    command,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=timeout_s,
                )
            except subprocess.TimeoutExpired as exc:
                raise PreprocessingError("ffmpeg preprocessing timed out") from exc
            if int(completed.returncode) != 0:
                raise PreprocessingError("ffmpeg preprocessing failed")
            try:
                metadata = output_path.stat()
            except OSError as exc:
                raise PreprocessingError("ffmpeg preprocessing produced no output") from exc
            if output_path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
                raise PreprocessingError("ffmpeg preprocessing output is unsafe")
            if metadata.st_size != expected_bytes:
                raise PreprocessingError("ffmpeg preprocessing output size is not exact")
            payload = output_path.read_bytes()
            if len(payload) != expected_bytes:
                raise PreprocessingError("ffmpeg preprocessing output read was incomplete")
            return payload

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PreprocessingError("tensor preprocessing timed out")
        return remaining
