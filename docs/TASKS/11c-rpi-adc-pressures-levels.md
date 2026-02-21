# Task 11c — Raspberry Pi ADC: pressures + levels (0–100 psi + %)

🟢 **Status: Implemented (2026-02-21)**

## Objective

Implement an ADC-based sensor backend for analog sensors:

- `water_pressure_psi` (0–100)
- `oil_pressure_psi` (0–100)
- `oil_level_pct`
- `drip_oil_level_pct`

This task focuses on:

- stable, testable scaling math
- noise tolerance
- configuration-driven channel mapping

## Hardware assumptions

- ADC: ADS1115 (I2C)
- Sensors:
  - Pressure transmitters: **4–20 mA** (preferred for noise immunity)
  - Level sensors: 4–20 mA or voltage output (configurable)

## Scope

### In-scope

- Add `rpi_adc` backend that reads ADS1115 channels.
- Support channel mapping in config:

```yaml
backend: rpi_adc
adc:
  type: ads1115
  address: 0x48
  gain: 1
channels:
  water_pressure_psi:
    channel: 0
    kind: current_4_20ma
    shunt_ohms: 165
    scale:
      from: [4.0, 20.0]
      to: [0.0, 100.0]
  oil_pressure_psi:
    channel: 1
    kind: current_4_20ma
    shunt_ohms: 165
    scale:
      from: [4.0, 20.0]
      to: [0.0, 100.0]
  oil_level_pct:
    channel: 2
    kind: current_4_20ma
    shunt_ohms: 165
    scale:
      from: [4.0, 20.0]
      to: [0.0, 100.0]
```

- Add pure scaling helpers with unit tests:
  - current(mA) → voltage(V) → psi/%
  - clamp behavior

### Out-of-scope

- Tank-specific geometry modeling (keep it linear for MVP).

## Design notes

- The conversion layer must be **pure functions** so it can be tested without hardware.
- The backend must return `None` for any channel that fails.
- Add simple smoothing (optional):
  - median of N samples
  - configurable per metric

## Acceptance criteria

- A full set of ADC metrics can be produced in mock mode from static fixtures.
- Scaling math has unit tests covering:
  - 4 mA → 0
  - 20 mA → 100
  - out-of-range clamps
- Backend can be selected without impacting local dev.

## Deliverables

- `agent/sensors/backends/rpi_adc.py`
- `agent/sensors/scaling.py` (+ tests)
- `docs/RUNBOOKS/SENSORS.md` updated with conditioning notes and calibration steps.

## Validation

```bash
make fmt
make lint
make typecheck
make test
```
