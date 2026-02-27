from __future__ import annotations

from api.app.contracts import load_telemetry_contract


def test_load_contract_v1_has_expected_keys() -> None:
    c = load_telemetry_contract("v1")
    assert c.version == "v1"
    assert "rpi_microphone_power_v1" in c.profiles
    assert "water_pressure_psi" in c.metrics
    assert c.metrics["water_pressure_psi"].type == "number"
    assert "oil_life_reset_at" in c.metrics
    assert c.metrics["oil_life_reset_at"].type == "string"


def test_validate_metrics_unknown_keys_are_allowed_but_visible() -> None:
    c = load_telemetry_contract("v1")

    unknown, errors = c.validate_metrics({"water_pressure_psi": 42.0, "new_metric": 1})
    assert errors == []
    assert unknown == {"new_metric"}


def test_validate_metrics_type_mismatch_is_an_error() -> None:
    c = load_telemetry_contract("v1")

    unknown, errors = c.validate_metrics({"water_pressure_psi": "42"})
    assert unknown == set()
    assert errors
    assert "water_pressure_psi" in errors[0]
