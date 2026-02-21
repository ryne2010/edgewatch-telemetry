from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from agent.sensors.backends.composite import CompositeSensorBackend
from agent.sensors.base import Metrics
from agent.sensors.config import SensorConfigError, build_sensor_backend, load_sensor_config_from_env


def _write_yaml(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def test_sensor_config_defaults_to_mock_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SENSOR_CONFIG_PATH", raising=False)
    monkeypatch.delenv("SENSOR_BACKEND", raising=False)

    cfg = load_sensor_config_from_env()
    assert cfg.backend == "mock"

    backend = build_sensor_backend(device_id="demo-well-001", config=cfg)
    metrics = backend.read_metrics()
    assert "water_pressure_psi" in metrics
    assert "temperature_c" in metrics


def test_sensor_backend_override_env_wins_over_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "sensors.yaml"
    _write_yaml(
        config_path,
        """
        backend: composite
        backends:
          - backend: mock
          - backend: derived
        """,
    )

    monkeypatch.setenv("SENSOR_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("SENSOR_BACKEND", "mock")

    cfg = load_sensor_config_from_env()
    assert cfg.backend == "mock"


def test_invalid_sensor_config_fails_fast_with_clear_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "invalid.yaml"
    _write_yaml(
        config_path,
        """
        backend: rpi_adc
        channels:
          bad-key:
            channel: 0
        """,
    )

    monkeypatch.setenv("SENSOR_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("SENSOR_BACKEND", raising=False)

    with pytest.raises(SensorConfigError) as exc:
        load_sensor_config_from_env()
    assert "invalid metric key" in str(exc.value)


class _StaticBackend:
    metric_keys = frozenset({"humidity_pct"})

    def read_metrics(self) -> Metrics:
        return {"humidity_pct": 51.2}


class _FailingBackend:
    metric_keys = frozenset({"temperature_c"})

    def read_metrics(self) -> Metrics:
        raise RuntimeError("sensor disconnected")


def test_composite_backend_returns_none_for_failed_child_reads() -> None:
    backend = CompositeSensorBackend(backends=[_StaticBackend(), _FailingBackend()])

    metrics = backend.read_metrics()
    assert metrics["humidity_pct"] == 51.2
    assert metrics["temperature_c"] is None


def test_placeholder_backend_uses_configured_channel_keys(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "adc.yaml"
    _write_yaml(
        config_path,
        """
        backend: rpi_adc
        channels:
          custom_pressure_psi:
            channel: 0
            unit: psi
        """,
    )
    monkeypatch.setenv("SENSOR_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("SENSOR_BACKEND", raising=False)

    cfg = load_sensor_config_from_env()
    backend = build_sensor_backend(device_id="demo-well-001", config=cfg)
    metrics = backend.read_metrics()

    assert metrics["custom_pressure_psi"] is None
    assert metrics["water_pressure_psi"] is None


def test_composite_config_requires_backends_list(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "missing_backends.yaml"
    _write_yaml(
        config_path,
        """
        backend: composite
        """,
    )
    monkeypatch.setenv("SENSOR_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("SENSOR_BACKEND", raising=False)

    with pytest.raises(SensorConfigError) as exc:
        load_sensor_config_from_env()
    assert "requires non-empty 'backends' list" in str(exc.value)
