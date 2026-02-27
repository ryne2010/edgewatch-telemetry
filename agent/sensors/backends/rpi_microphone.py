from __future__ import annotations

import math
import struct
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

from ..base import Metrics


@dataclass(frozen=True)
class CaptureResult:
    returncode: int
    stdout: bytes
    stderr: bytes


CaptureCommand = Callable[[Sequence[str], float], CaptureResult]


def run_capture_command(args: Sequence[str], timeout_s: float) -> CaptureResult:
    completed = subprocess.run(
        list(args),
        capture_output=True,
        check=False,
        timeout=timeout_s,
    )
    stdout = completed.stdout if isinstance(completed.stdout, (bytes, bytearray)) else b""
    stderr = completed.stderr if isinstance(completed.stderr, (bytes, bytearray)) else b""
    return CaptureResult(returncode=int(completed.returncode), stdout=bytes(stdout), stderr=bytes(stderr))


def _pcm_rms_db(raw_pcm_s16_le: bytes) -> float:
    sample_count = len(raw_pcm_s16_le) // 2
    if sample_count == 0:
        return 0.0

    total = 0.0
    for (sample,) in struct.iter_unpack("<h", raw_pcm_s16_le[: sample_count * 2]):
        total += float(sample) * float(sample)

    rms = math.sqrt(total / float(sample_count))
    return 20.0 * math.log10(max(rms, 1.0))


@dataclass
class RpiMicrophoneSensorBackend:
    """Read a short PCM clip from ALSA and report a relative microphone level."""

    device: str = "default"
    sample_rate_hz: int = 16_000
    capture_seconds: float = 1.0
    command_timeout_s: float = 5.0
    warning_interval_s: float = 300.0
    command_runner: CaptureCommand = run_capture_command
    monotonic: Callable[[], float] = time.monotonic
    metric_keys: frozenset[str] = field(default_factory=lambda: frozenset({"microphone_level_db"}))
    _last_warning_at: float | None = field(default=None, init=False, repr=False)

    def _warn(self, message: str) -> None:
        now = self.monotonic()
        if self._last_warning_at is None or (now - self._last_warning_at) >= self.warning_interval_s:
            print(f"[edgewatch-agent] rpi_microphone warning: {message}")
            self._last_warning_at = now

    def _none_metrics(self) -> Metrics:
        return {"microphone_level_db": None}

    def _command(self) -> list[str]:
        samples = max(1, int(round(float(self.sample_rate_hz) * float(self.capture_seconds))))
        return [
            "arecord",
            "-q",
            "-D",
            self.device,
            "-f",
            "S16_LE",
            "-c",
            "1",
            "-r",
            str(self.sample_rate_hz),
            "--samples",
            str(samples),
            "-t",
            "raw",
        ]

    def read_metrics(self) -> Metrics:
        try:
            result = self.command_runner(self._command(), float(self.command_timeout_s))
        except Exception as exc:
            self._warn(f"capture command failed: {exc}")
            return self._none_metrics()

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            detail = stderr[:200] if stderr else "no stderr"
            self._warn(f"capture command exited {result.returncode}: {detail}")
            return self._none_metrics()

        if not result.stdout:
            self._warn("capture command returned no audio samples")
            return self._none_metrics()

        try:
            level_db = _pcm_rms_db(result.stdout)
        except Exception as exc:
            self._warn(f"failed to compute microphone RMS: {exc}")
            return self._none_metrics()

        return {"microphone_level_db": round(float(level_db), 1)}
