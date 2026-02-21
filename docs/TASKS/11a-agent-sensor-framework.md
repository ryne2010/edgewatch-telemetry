# Task 11a — Agent sensor framework + config

🟡 **Status: Planned**

## Objective

Introduce a **pluggable sensor framework** in the edge agent so we can add real Raspberry Pi sensor backends (I2C + ADC) without entangling hardware details with buffering/ingest logic.

This task is deliberately *foundational* and should land before any real sensor drivers.

## Scope

### In-scope

- Add `agent/sensors/` module with a small internal interface (protocol):
  - `read_metrics() -> dict[str, float | int | str | bool | None]`
- Add portable configuration for:
  - selecting a sensor backend (`mock`, `rpi_i2c`, `rpi_adc`, `derived`, `composite`)
  - mapping channels → metric keys
  - scaling constants
- Add `agent/config/` with an example config file.
- Wire the agent so the existing telemetry loop uses the new interface.
- Update unit tests to prove deterministic behavior.

### Out-of-scope

- Real I2C driver integration (handled in Task 11b).
- Real ADC integration (handled in Task 11c).
- Derived oil life (handled in Task 11d).

## Design notes

### Key constraints

- The agent must keep working with **mock sensors** by default.
- If sensors fail, the agent must still:
  - send heartbeat
  - flush buffered telemetry
  - avoid crashing

### Recommended architecture

- `agent/sensors/base.py`
  - `class SensorBackend(Protocol): read_metrics(self) -> dict[str, Any]`
- `agent/sensors/backends/`
  - `mock.py` (existing logic relocated)
  - `composite.py` (combine multiple backends; later used for derived oil life + hardware)
- `agent/sensors/config.py`
  - parse and validate config
  - enforce key constraints (metric key regex, allowed units)

### Config format

Prefer YAML (repo already uses YAML for contracts). Example:

```yaml
backend: composite
backends:
  - backend: mock
  - backend: derived
    derived:
      oil_life_max_run_hours: 300
      state_path: "./agent/state/oil_life_state.json"
```

## Acceptance criteria

- Agent runs with **no hardware** and behaves as today.
- Sensor backend can be selected by env var:
  - `SENSOR_CONFIG_PATH=...` (path)
  - `SENSOR_BACKEND=mock|...` (optional override)
- Invalid config fails fast with a clear error message.
- Failed reads return `None` values (not exceptions), and the agent continues.

## Deliverables

- New modules under `agent/sensors/`
- Example config: `agent/config/example.sensors.yaml`
- Updated agent docs:
  - `agent/README.md` add a short “Sensors” section

## Validation

```bash
make fmt
make lint
make typecheck
make test

# smoke
make up
make demo-device
make simulate
```
