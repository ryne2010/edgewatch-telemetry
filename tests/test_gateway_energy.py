from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any, cast

import pytest

from gateway_runtime.energy import EnergyQualificationError, build_energy_report
from scripts.gateway_energy_report import main


def _payload(*, daily: list[float] | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mode_measurements": [
            {"mode": "pi_only", "duration_hours": 1, "energy_wh": 3.2},
            {"mode": "lte_registered_idle", "duration_hours": 1, "energy_wh": 8.5},
            {"mode": "lte_transfer", "duration_hours": 1, "energy_wh": 11.2},
            {"mode": "lte_electrically_off", "duration_hours": 1, "energy_wh": 3.8},
        ],
        "daily_energy_wh": daily or [92, 94, 93, 96, 95, 91, 90],
        "cold_derating": 0.7,
        "conversion_efficiency": 0.85,
    }


def test_report_enforces_power_gate_and_accepted_sizing_formula() -> None:
    report = build_energy_report(_payload())

    assert report["status"] == "passed"
    assert report["p95_daily_energy_wh"] == 96
    assert report["p95_average_power_w"] == 4
    assert report["required_battery_nameplate_wh"] == pytest.approx(1411.7647)
    assert report["minimum_daily_solar_generation_wh"] == 144
    measurements = cast(list[dict[str, object]], report["mode_measurements"])
    assert [row["mode"] for row in measurements] == [
        "pi_only",
        "lte_registered_idle",
        "lte_transfer",
        "lte_electrically_off",
    ]


def test_report_fails_when_p95_average_exceeds_five_watts() -> None:
    report = build_energy_report(_payload(daily=[121, 122, 123, 124, 125, 126, 127]))

    assert report["status"] == "failed"
    assert report["failure_reasons"] == ["p95_average_power_exceeds_5_w"]


def test_report_rejects_missing_mode_short_samples_and_optimistic_sizing() -> None:
    missing = _payload()
    missing["mode_measurements"] = list(missing["mode_measurements"])[1:]
    with pytest.raises(EnergyQualificationError, match="missing required mode"):
        build_energy_report(missing)

    with pytest.raises(EnergyQualificationError, match="at least 7"):
        build_energy_report(_payload(daily=[90]))

    optimistic = _payload()
    optimistic["solar_generation_multiplier"] = 1.49
    with pytest.raises(EnergyQualificationError, match="at least 1.5"):
        build_energy_report(optimistic)


def test_cli_writes_private_report_and_uses_one_day_initial_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "measurements.json"
    output = tmp_path / "report.json"
    source.write_text(json.dumps(_payload(daily=[96])), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "gateway-energy-report",
            "--input",
            str(source),
            "--output",
            str(output),
            "--minimum-daily-samples",
            "1",
        ],
    )

    assert main() == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "passed"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
