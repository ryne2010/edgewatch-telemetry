from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from agent.lorawan.radio import (
    RadioIngressConfig,
    RadioIngressError,
    RadioIngressHealth,
    load_radio_ingress_config,
)


NOW = 1_780_000_000.0


def _private_text(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def _private_json(path: Path, value: object) -> Path:
    return _private_text(path, json.dumps(value, sort_keys=True))


def _files(tmp_path: Path) -> tuple[Path, Path, Path]:
    executable = tmp_path / "radio-adapter"
    executable.write_bytes(b"#!/bin/sh\nexit 1\n")
    executable.chmod(0o700)
    hardware_config = _private_text(tmp_path / "hardware.yaml", "hardware: test-only\n")
    config = _private_text(
        tmp_path / "radio.yaml",
        yaml.safe_dump(
            {
                "schema_version": 1,
                "gateway_id": "AABBCCDDEEFF0011",
                "region": "US915",
                "concentrator": "sx1302",
                "adapter_executable": str(executable),
                "adapter_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                "adapter_config_file": str(hardware_config),
                "status_file": str(tmp_path / "status.json"),
                "instance_file": str(tmp_path / "instance.json"),
                "status_max_age_s": 30,
                "startup_timeout_s": 90,
            }
        ),
    )
    return config, executable, hardware_config


def test_radio_config_pins_a_closed_external_adapter_contract(tmp_path: Path) -> None:
    config_path, executable, _hardware_config = _files(tmp_path)

    config = load_radio_ingress_config(config_path)
    config.validate_installation()

    assert config.gateway_id == "aabbccddeeff0011"
    assert config.command("01" * 16) == [
        str(executable),
        "--config",
        str(tmp_path / "hardware.yaml"),
        "--status-file",
        str(tmp_path / "status.json"),
        "--gateway-id",
        "aabbccddeeff0011",
        "--region",
        "US915",
        "--concentrator",
        "sx1302",
        "--instance-id",
        "01" * 16,
    ]

    executable.write_bytes(b"replaced")
    executable.chmod(0o700)
    with pytest.raises(RadioIngressError, match="SHA-256 pin"):
        config.validate_installation()


def test_radio_config_and_secret_files_fail_closed(tmp_path: Path) -> None:
    config_path, _executable, _hardware_config = _files(tmp_path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw["packet_forwarder_shell_command"] = "anything"
    config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(RadioIngressError, match="unknown key"):
        load_radio_ingress_config(config_path)

    raw.pop("packet_forwarder_shell_command")
    config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    config_path.chmod(0o644)
    with pytest.raises(RadioIngressError, match="private regular file"):
        load_radio_ingress_config(config_path)


def test_health_requires_current_instance_hardware_and_gateway_bridge(tmp_path: Path) -> None:
    config_path, _executable, _hardware_config = _files(tmp_path)
    config = load_radio_ingress_config(config_path)
    health = RadioIngressHealth(config, clock=lambda: NOW)
    instance_id = health.create_instance()
    status = {
        "schema_version": 1,
        "gateway_id": config.gateway_id,
        "region": "US915",
        "concentrator": "sx1302",
        "instance_id": instance_id,
        "concentrator_detected": True,
        "gateway_bridge_connected": True,
        "updated_at": NOW,
    }
    _private_json(config.status_file, status)

    health.assert_ready()

    status["gateway_bridge_connected"] = False
    _private_json(config.status_file, status)
    with pytest.raises(RadioIngressError, match="readiness proof"):
        health.assert_ready()

    status["gateway_bridge_connected"] = True
    status["updated_at"] = NOW - config.status_max_age_s - 1
    _private_json(config.status_file, status)
    with pytest.raises(RadioIngressError, match="stale"):
        health.assert_ready()

    status["updated_at"] = NOW
    status["instance_id"] = "02" * 16
    _private_json(config.status_file, status)
    with pytest.raises(RadioIngressError, match="readiness proof"):
        health.assert_ready()


def test_status_permissions_and_boolean_types_are_strict(tmp_path: Path) -> None:
    config_path, _executable, _hardware_config = _files(tmp_path)
    config = load_radio_ingress_config(config_path)
    health = RadioIngressHealth(config, clock=lambda: NOW)
    instance_id = health.create_instance()
    status = {
        "schema_version": 1,
        "gateway_id": config.gateway_id,
        "region": "US915",
        "concentrator": "sx1302",
        "instance_id": instance_id,
        "concentrator_detected": 1,
        "gateway_bridge_connected": True,
        "updated_at": NOW,
    }
    _private_json(config.status_file, status)
    with pytest.raises(RadioIngressError, match="readiness proof"):
        health.assert_ready()

    status["concentrator_detected"] = True
    _private_json(config.status_file, status).chmod(0o644)
    with pytest.raises(RadioIngressError, match="private regular file"):
        health.assert_ready()


def test_programmatic_config_rejects_non_us915_or_unpinned_paths(tmp_path: Path) -> None:
    values = {
        "gateway_id": "aabbccddeeff0011",
        "adapter_executable": tmp_path / "adapter",
        "adapter_sha256": "aa" * 32,
        "adapter_config_file": tmp_path / "adapter.yaml",
        "status_file": tmp_path / "status.json",
        "instance_file": tmp_path / "instance.json",
    }
    with pytest.raises(RadioIngressError, match="US915"):
        RadioIngressConfig(**values, region="EU868")
    with pytest.raises(RadioIngressError, match="absolute"):
        RadioIngressConfig(**{**values, "adapter_executable": Path("adapter")})
