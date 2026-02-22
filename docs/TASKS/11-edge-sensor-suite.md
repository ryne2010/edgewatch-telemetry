# Task 11 (Epic) — Edge sensor suite (temp/humidity/pressures/levels)

✅ **Status: Implemented (2026-02-22)**

## Intent

Extend the edge agent from "mock sensors" to a real Raspberry Pi sensor suite that can
reliably capture the requested operational signals:

- temperature (°C)
- humidity (%)
- oil pressure (psi)
- oil level (%)
- oil life (%) (**runtime-derived with manual reset**)
- drip oil level (%)
- water pressure (psi)

The end goal is a production-grade "remote equipment monitor" that still preserves the
repo's core invariants: contract-first telemetry, cost-aware reporting, local buffering,
idempotent ingest, and audit-friendly ops.

Related ADRs:
- `docs/DECISIONS/ADR-20260220-pressure-range.md`
- `docs/DECISIONS/ADR-20260220-oil-life-manual-reset.md`

## Implementation plan (Codex-friendly slices)

This epic was decomposed into smaller tasks and completed end-to-end:

1) ✅ **Framework + config** → `11a-agent-sensor-framework.md`
2) ✅ **I2C temp/humidity** → `11b-rpi-i2c-temp-humidity.md`
3) ✅ **ADC pressures/levels** → `11c-rpi-adc-pressures-levels.md`
4) ✅ **Derived oil life + reset** → `11d-derived-oil-life-reset.md`

All slices landed with tests and docs updates.

## Non-goals

- Full PLC/SCADA replacement.
- OTA updates / fleet-wide provisioning (keep this repo lightweight).
- A full calibration UI (support config + docs first).

## Acceptance criteria (epic-level)

### Agent

- `agent/sensors/` supports **pluggable backends**:
  - `mock` (existing)
  - `rpi_i2c` (digital sensors like temp/humidity)
  - `rpi_adc` (analog sensors for pressure/level)
  - `derived` (oil life model)
  - `composite` (combine multiple)
- Sensor config is explicit and portable:
  - minimal env vars for "which backend"
  - a small local config file (YAML) for channel mapping + scaling constants
  - a documented example under `agent/config/`
- Reading failures degrade gracefully:
  - missing sensors yield `None` for that metric
  - agent continues to heartbeat + flush buffer
  - optionally emit `sensor_health_*` metrics

### Derived oil life (manual reset)

- Oil life computed per ADR:
  - runtime accumulates only while equipment is considered "running"
  - oil life decreases linearly from 100% to 0% over `oil_life_max_run_hours`
  - oil life does not increase except on reset
- Device-local state is durable across reboots.
- Reset mechanism exists (CLI on device).

### Contracts

- The telemetry contract includes canonical keys:
  - `temperature_c`, `humidity_pct`, `water_pressure_psi`, `oil_pressure_psi`
  - `oil_level_pct`, `drip_oil_level_pct`, `oil_life_pct`
- Edge policy includes delta thresholds for these keys.

### UI

- Device detail page can chart the new metrics.
- Oil life is shown as a **gauge** or **progress bar** with last reset time.

### Docs

- `docs/HARDWARE.md` includes wiring + conditioning notes (I2C + 4–20 mA → ADC).
- Runbook exists: `docs/RUNBOOKS/SENSORS.md` covering:
  - Pi bring-up checklist
  - how to validate sensor readings locally before installing in the field
  - calibration constants and scaling sanity checks

## Validation plan

```bash
make fmt
make lint
make typecheck
make test

# end-to-end smoke
make up
make demo-device
make simulate
```
