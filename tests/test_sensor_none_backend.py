from __future__ import annotations

from pathlib import Path

import pytest

from agent.sensors.backends import NoneSensorBackend
from agent.sensors.config import build_sensor_backend, load_sensor_config_from_env


def test_sensor_backend_none_is_hardware_free_and_silent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "sensors.yaml"
    config_path.write_text(
        "backend: composite\nbackends:\n  - backend: mock\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SENSOR_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("SENSOR_BACKEND", "none")

    config = load_sensor_config_from_env()
    backend = build_sensor_backend(device_id="bring-up-pi", config=config)

    assert config.backend == "none"
    assert config.backends == ()
    assert isinstance(backend.backend, NoneSensorBackend)
    assert backend.metric_keys == frozenset()
    assert backend.read_metrics() == {}
    assert backend.read_metrics() == {}
    assert capsys.readouterr() == ("", "")


def test_none_backend_can_be_selected_in_yaml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "sensors.yaml"
    config_path.write_text("backend: none\n", encoding="utf-8")
    monkeypatch.setenv("SENSOR_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("SENSOR_BACKEND", raising=False)

    config = load_sensor_config_from_env()
    backend = build_sensor_backend(device_id="bring-up-pi", config=config)

    assert config.backend == "none"
    assert backend.read_metrics() == {}
