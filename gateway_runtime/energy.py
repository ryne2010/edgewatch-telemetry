"""Measured gateway energy qualification and storage/solar sizing."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Iterable, Mapping


REQUIRED_MODES = (
    "pi_only",
    "lte_registered_idle",
    "lte_transfer",
    "lte_electrically_off",
)


class EnergyQualificationError(ValueError):
    """Raised when meter evidence is incomplete or physically invalid."""


@dataclass(frozen=True)
class ModeMeasurement:
    """One inline-meter observation for a required gateway power mode."""

    mode: str
    duration_hours: float
    energy_wh: float

    @property
    def average_w(self) -> float:
        return self.energy_wh / self.duration_hours


def _finite_positive(value: object, *, name: str) -> float:
    if isinstance(value, bool):
        raise EnergyQualificationError(f"{name} must be a finite positive number")
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise EnergyQualificationError(f"{name} must be a finite positive number") from exc
    if not math.isfinite(result) or result <= 0:
        raise EnergyQualificationError(f"{name} must be a finite positive number")
    return result


def parse_mode_measurements(raw: object) -> tuple[ModeMeasurement, ...]:
    """Parse exactly one measurement for each required electrical mode."""

    if not isinstance(raw, list):
        raise EnergyQualificationError("mode_measurements must be a list")
    parsed: list[ModeMeasurement] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping) or set(item) != {"mode", "duration_hours", "energy_wh"}:
            raise EnergyQualificationError(f"mode_measurements[{index}] has an invalid schema")
        mode = item["mode"]
        if not isinstance(mode, str) or mode not in REQUIRED_MODES:
            raise EnergyQualificationError(f"mode_measurements[{index}].mode is unsupported")
        if mode in seen:
            raise EnergyQualificationError(f"mode {mode!r} is duplicated")
        duration = _finite_positive(item["duration_hours"], name=f"{mode}.duration_hours")
        energy = _finite_positive(item["energy_wh"], name=f"{mode}.energy_wh")
        if duration < 0.25:
            raise EnergyQualificationError(f"{mode}.duration_hours must be at least 0.25")
        seen.add(mode)
        parsed.append(ModeMeasurement(mode=mode, duration_hours=duration, energy_wh=energy))
    required_modes: set[str] = set(REQUIRED_MODES)
    missing = sorted(required_modes - seen)
    if missing:
        raise EnergyQualificationError(f"missing required mode measurements: {', '.join(missing)}")
    return tuple(parsed)


def _nearest_rank_percentile(values: Iterable[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise EnergyQualificationError("daily_energy_wh must contain at least one sample")
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def build_energy_report(
    payload: Mapping[str, object],
    *,
    minimum_daily_samples: int = 7,
) -> dict[str, object]:
    """Validate meter evidence and calculate the accepted sizing equations."""

    allowed = {
        "schema_version",
        "mode_measurements",
        "daily_energy_wh",
        "cold_derating",
        "conversion_efficiency",
        "depth_of_discharge",
        "autonomy_days",
        "solar_generation_multiplier",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise EnergyQualificationError(f"unknown energy input fields: {', '.join(unknown)}")
    if payload.get("schema_version") != 1:
        raise EnergyQualificationError("schema_version must be 1")
    if not 1 <= minimum_daily_samples <= 366:
        raise EnergyQualificationError("minimum_daily_samples must be within 1..366")

    modes = parse_mode_measurements(payload.get("mode_measurements"))
    raw_daily = payload.get("daily_energy_wh")
    if not isinstance(raw_daily, list):
        raise EnergyQualificationError("daily_energy_wh must be a list")
    daily = tuple(
        _finite_positive(value, name=f"daily_energy_wh[{index}]") for index, value in enumerate(raw_daily)
    )
    if len(daily) < minimum_daily_samples:
        raise EnergyQualificationError(f"daily_energy_wh requires at least {minimum_daily_samples} samples")

    cold_derating = _finite_positive(payload.get("cold_derating"), name="cold_derating")
    efficiency = _finite_positive(payload.get("conversion_efficiency"), name="conversion_efficiency")
    depth_of_discharge = _finite_positive(payload.get("depth_of_discharge", 0.8), name="depth_of_discharge")
    autonomy_days = _finite_positive(payload.get("autonomy_days", 7), name="autonomy_days")
    solar_multiplier = _finite_positive(
        payload.get("solar_generation_multiplier", 1.5),
        name="solar_generation_multiplier",
    )
    for name, value in (
        ("cold_derating", cold_derating),
        ("conversion_efficiency", efficiency),
        ("depth_of_discharge", depth_of_discharge),
    ):
        if value > 1:
            raise EnergyQualificationError(f"{name} must be at most 1")
    if solar_multiplier < 1.5:
        raise EnergyQualificationError("solar_generation_multiplier must be at least 1.5")

    p95_daily_wh = _nearest_rank_percentile(daily, 0.95)
    p95_average_w = p95_daily_wh / 24.0
    battery_wh = p95_daily_wh * autonomy_days / (depth_of_discharge * cold_derating * efficiency)
    mode_rows = [
        {**asdict(item), "average_w": round(item.average_w, 4)}
        for item in sorted(modes, key=lambda item: REQUIRED_MODES.index(item.mode))
    ]
    passed = p95_average_w <= 5.0
    return {
        "schema_version": 1,
        "status": "passed" if passed else "failed",
        "daily_sample_count": len(daily),
        "minimum_daily_samples": minimum_daily_samples,
        "p95_daily_energy_wh": round(p95_daily_wh, 4),
        "p95_average_power_w": round(p95_average_w, 4),
        "gateway_average_power_limit_w": 5.0,
        "required_battery_nameplate_wh": round(battery_wh, 4),
        "minimum_daily_solar_generation_wh": round(p95_daily_wh * solar_multiplier, 4),
        "sizing_inputs": {
            "autonomy_days": autonomy_days,
            "depth_of_discharge": depth_of_discharge,
            "cold_derating": cold_derating,
            "conversion_efficiency": efficiency,
            "solar_generation_multiplier": solar_multiplier,
        },
        "mode_measurements": mode_rows,
        "failure_reasons": [] if passed else ["p95_average_power_exceeds_5_w"],
    }
