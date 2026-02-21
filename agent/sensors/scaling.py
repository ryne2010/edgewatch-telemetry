from __future__ import annotations

from dataclasses import dataclass


def clamp(value: float, low: float, high: float) -> float:
    if low > high:
        raise ValueError("clamp range is invalid: low must be <= high")
    if value < low:
        return low
    if value > high:
        return high
    return value


def linear_map(
    *,
    value: float,
    from_range: tuple[float, float],
    to_range: tuple[float, float],
    clamp_output: bool = True,
) -> float:
    from_low, from_high = from_range
    to_low, to_high = to_range
    if from_low == from_high:
        raise ValueError("from_range cannot have identical bounds")

    ratio = (value - from_low) / (from_high - from_low)
    mapped = to_low + ratio * (to_high - to_low)
    if not clamp_output:
        return mapped

    out_low = min(to_low, to_high)
    out_high = max(to_low, to_high)
    return clamp(mapped, out_low, out_high)


def current_ma_from_voltage(*, voltage_v: float, shunt_ohms: float) -> float:
    if shunt_ohms <= 0.0:
        raise ValueError("shunt_ohms must be > 0")
    return (voltage_v / shunt_ohms) * 1000.0


def voltage_from_current_ma(*, current_ma: float, shunt_ohms: float) -> float:
    if shunt_ohms <= 0.0:
        raise ValueError("shunt_ohms must be > 0")
    return (current_ma / 1000.0) * shunt_ohms


def current_4_20ma_to_percent(*, current_ma: float) -> float:
    return linear_map(
        value=current_ma,
        from_range=(4.0, 20.0),
        to_range=(0.0, 100.0),
        clamp_output=True,
    )


@dataclass(frozen=True)
class ScalingConfig:
    from_range: tuple[float, float]
    to_range: tuple[float, float]
    clamp_output: bool = True

    def apply(self, value: float) -> float:
        return linear_map(
            value=value,
            from_range=self.from_range,
            to_range=self.to_range,
            clamp_output=self.clamp_output,
        )
