from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from agent.inference.preprocess import FFmpegTensorPreprocessor, PreprocessingError


@dataclass(frozen=True)
class _Spec:
    input_shape: tuple[int, ...]
    input_dtype: str = "int8"
    input_quantization: tuple[float, int] = (0.1, 0)


def _metadata() -> dict[str, dict[str, object]]:
    return {
        "vision": {
            "layout": "nhwc",
            "width": 16,
            "height": 16,
            "channels": 1,
            "resize_filter": "bilinear",
            "value_scale": 1.0 / 255.0,
            "value_offset": 0.0,
        },
        "audio": {
            "layout": "nhwc",
            "feature": "log_mel",
            "sample_rate_hz": 8000,
            "sample_count": 800,
            "window_samples": 64,
            "hop_samples": 64,
            "fft_size": 64,
            "mel_bins": 8,
            "lower_hz": 100.0,
            "upper_hz": 3000.0,
            "log_floor": 1e-10,
            "window": "hann",
            "log_base": "e",
        },
    }


class _DeterministicRunner:
    def __init__(self, *, truncate: bool = False) -> None:
        self.truncate = truncate
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        self.commands.append(list(command))
        output = Path(command[-1])
        expected = int(command[command.index("-fs") + 1])
        if output.suffix == ".rgb":
            source = Path(command[command.index("-i") + 1]).read_bytes()
            value = 20 if source == b"current-jpeg" else 10
            payload = bytes([value]) * expected
        else:
            payload = b"\x00\x00" * (expected // 2)
        if self.truncate:
            payload = payload[:-1]
        output.write_bytes(payload)
        return subprocess.CompletedProcess(command, 0, b"", b"")


class _TimeoutRunner:
    def __call__(self, command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(command, 1.0)


def test_preprocessing_matches_signed_shapes_and_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent.inference.preprocess.shutil.which", lambda _name: "/usr/bin/ffmpeg")
    runner = _DeterministicRunner()
    preprocessor = FFmpegTensorPreprocessor(_metadata(), run_command=runner)
    vision = _Spec((1, 16, 16, 1), input_quantization=(1.0 / 255.0, -128))
    audio = _Spec((1, 12, 8, 1), input_quantization=(0.25, 0))

    first = preprocessor.preprocess(
        still_jpeg=b"current-jpeg",
        audio_wav=b"wav",
        previous_still_jpeg=b"previous-jpeg",
        vision_spec=vision,
        audio_spec=audio,
    )
    second = preprocessor.preprocess(
        still_jpeg=b"current-jpeg",
        audio_wav=b"wav",
        previous_still_jpeg=b"previous-jpeg",
        vision_spec=vision,
        audio_spec=audio,
    )

    assert first == second
    assert len(first.vision) == 256
    assert len(first.audio) == 96
    assert first.visual_change == pytest.approx(10.0 / 255.0, abs=1e-6)
    assert all(
        "-threads" in command and command[command.index("-threads") + 1] == "1" for command in runner.commands
    )
    assert all("+bitexact" in command for command in runner.commands)


def test_preprocessing_rejects_model_shape_drift_before_ffmpeg() -> None:
    runner = _DeterministicRunner()
    preprocessor = FFmpegTensorPreprocessor(_metadata(), run_command=runner)

    with pytest.raises(PreprocessingError, match="vision model input shape"):
        preprocessor.preprocess(
            still_jpeg=b"current-jpeg",
            audio_wav=b"wav",
            vision_spec=_Spec((1, 8, 8, 1)),
            audio_spec=_Spec((1, 12, 8, 1)),
        )

    assert runner.commands == []


def test_preprocessing_rejects_quantization_zero_point_outside_dtype() -> None:
    runner = _DeterministicRunner()
    preprocessor = FFmpegTensorPreprocessor(_metadata(), run_command=runner)

    with pytest.raises(PreprocessingError, match="quantization is invalid"):
        preprocessor.validate_specs(
            vision_spec=_Spec((1, 16, 16, 1), input_quantization=(0.1, 255)),
            audio_spec=_Spec((1, 12, 8, 1)),
        )

    assert runner.commands == []


def test_preprocessing_rejects_unsigned_model_inputs() -> None:
    runner = _DeterministicRunner()
    preprocessor = FFmpegTensorPreprocessor(_metadata(), run_command=runner)

    with pytest.raises(
        PreprocessingError,
        match="vision model input must use signed int8, not uint8",
    ):
        preprocessor.validate_specs(
            vision_spec=_Spec((1, 16, 16, 1), input_dtype="uint8"),
            audio_spec=_Spec((1, 12, 8, 1)),
        )

    assert runner.commands == []


def test_preprocessing_requires_exact_bounded_ffmpeg_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent.inference.preprocess.shutil.which", lambda _name: "/usr/bin/ffmpeg")
    preprocessor = FFmpegTensorPreprocessor(
        _metadata(),
        run_command=_DeterministicRunner(truncate=True),
    )

    with pytest.raises(PreprocessingError, match="output size is not exact"):
        preprocessor.preprocess(
            still_jpeg=b"current-jpeg",
            audio_wav=b"wav",
            vision_spec=_Spec((1, 16, 16, 1)),
            audio_spec=_Spec((1, 12, 8, 1)),
        )


def test_preprocessing_propagates_a_bounded_ffmpeg_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent.inference.preprocess.shutil.which", lambda _name: "/usr/bin/ffmpeg")
    preprocessor = FFmpegTensorPreprocessor(_metadata(), run_command=_TimeoutRunner())

    with pytest.raises(PreprocessingError, match="timed out"):
        preprocessor.preprocess(
            still_jpeg=b"current-jpeg",
            audio_wav=b"wav",
            vision_spec=_Spec((1, 16, 16, 1)),
            audio_spec=_Spec((1, 12, 8, 1)),
        )
