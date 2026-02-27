from __future__ import annotations

import struct
from typing import Sequence

import pytest

from agent.sensors.base import SafeSensorBackend
from agent.sensors.backends.rpi_microphone import CaptureResult, RpiMicrophoneSensorBackend
from agent.sensors.config import SensorConfigError, build_sensor_backend, parse_sensor_config


def _pcm_s16_le(samples: Sequence[int]) -> bytes:
    return b"".join(struct.pack("<h", sample) for sample in samples)


def test_rpi_microphone_backend_reports_relative_db() -> None:
    raw = _pcm_s16_le([2000, -2000] * 1000)

    def _runner(_args: Sequence[str], _timeout_s: float) -> CaptureResult:
        return CaptureResult(returncode=0, stdout=raw, stderr=b"")

    backend = RpiMicrophoneSensorBackend(command_runner=_runner)
    metrics = backend.read_metrics()
    assert metrics["microphone_level_db"] == pytest.approx(66.0, abs=0.2)


def test_rpi_microphone_backend_rate_limits_warning_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    times = iter([0.0, 1.0, 301.0])

    def _runner(_args: Sequence[str], _timeout_s: float) -> CaptureResult:
        raise RuntimeError("arecord missing")

    monkeypatch.setattr("builtins.print", lambda message: calls.append(str(message)))

    backend = RpiMicrophoneSensorBackend(
        command_runner=_runner,
        warning_interval_s=300.0,
        monotonic=lambda: next(times),
    )

    assert backend.read_metrics() == {"microphone_level_db": None}
    assert backend.read_metrics() == {"microphone_level_db": None}
    assert backend.read_metrics() == {"microphone_level_db": None}

    assert len(calls) == 2
    assert "rpi_microphone warning" in calls[0]


def test_build_sensor_backend_rpi_microphone_uses_config_values() -> None:
    cfg = parse_sensor_config(
        {
            "backend": "rpi_microphone",
            "rpi_microphone": {
                "device": "hw:1,0",
                "sample_rate_hz": 8000,
                "capture_seconds": 2.5,
                "command_timeout_s": 7.0,
                "warning_interval_s": 10.0,
            },
        },
        origin="test",
    )
    wrapped = build_sensor_backend(device_id="demo-well-001", config=cfg)

    assert isinstance(wrapped, SafeSensorBackend)
    assert isinstance(wrapped.backend, RpiMicrophoneSensorBackend)
    assert wrapped.backend.device == "hw:1,0"
    assert wrapped.backend.sample_rate_hz == 8000
    assert wrapped.backend.capture_seconds == 2.5
    assert wrapped.backend.command_timeout_s == 7.0
    assert wrapped.backend.warning_interval_s == 10.0


def test_invalid_rpi_microphone_sample_rate_fails_config_validation() -> None:
    cfg = parse_sensor_config(
        {
            "backend": "rpi_microphone",
            "rpi_microphone": {"sample_rate_hz": 0},
        },
        origin="test",
    )
    with pytest.raises(SensorConfigError):
        build_sensor_backend(device_id="demo-well-001", config=cfg)
