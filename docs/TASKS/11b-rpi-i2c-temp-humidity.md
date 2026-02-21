# Task 11b — Raspberry Pi I2C: temperature + humidity

🟡 **Status: Planned**

## Objective

Implement a real Raspberry Pi sensor backend for **temperature** and **humidity** over I2C.

This task should produce production-ready behavior:

- predictable units (°C / %)
- good error handling
- clean install path on Raspberry Pi OS

## Hardware assumptions

- I2C enabled in Raspberry Pi OS
- One supported sensor class:
  - **BME280** (recommended baseline)

The implementation should be structured so adding SHT31, etc., is straightforward.

## Scope

### In-scope

- Add an `rpi_i2c` backend under `agent/sensors/backends/`.
- Implement BME280 reads and mapping to:
  - `temperature_c`
  - `humidity_pct`
- Document wiring and bring-up checks.

### Out-of-scope

- ADC channels for pressure/levels (Task 11c).

## Design notes

### Dependency strategy

Prefer to keep the agent’s dependency surface area small.

Two acceptable implementation approaches:

1) Use a thin python library (`smbus2`) and implement BME280 read logic.
2) Use a well-known vendor stack (Adafruit CircuitPython) behind an **optional extra** (so local dev doesn’t need hardware deps).

Whichever is chosen, keep the import isolated inside the backend so the agent can run on non-RPi machines.

### Failure behavior

- If the I2C bus isn’t present or the device can’t be read:
  - set `temperature_c=None`, `humidity_pct=None`
  - emit a warning log (no spam loops; rate limit)

## Acceptance criteria

- On a Raspberry Pi with the sensor wired:
  - values appear in the telemetry stream
  - values have reasonable ranges (e.g., 0–50°C, 0–100%)
- On a laptop / CI:
  - the backend module imports safely (no ImportError unless selected)
  - tests pass without requiring I2C

## Deliverables

- `agent/sensors/backends/rpi_i2c.py` (or similar)
- `docs/RUNBOOKS/SENSORS.md` updated with:
  - wiring
  - enable I2C steps
  - sanity-check commands

## Validation

```bash
make fmt
make lint
make typecheck
make test
```

Field validation (Pi):

- enable I2C
- run agent with `SENSOR_BACKEND=rpi_i2c` and confirm telemetry
