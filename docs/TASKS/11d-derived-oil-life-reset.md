# Task 11d — Derived oil life (%), durable state + manual reset

🟡 **Status: Planned**

## Objective

Implement the **oil life** model as a derived metric per ADR:

- Runtime-derived, **manual reset**
- Durable across reboots
- Simple, operator-friendly reset workflow

This should land as a self-contained unit that can be used with either mock sensors or real sensors.

Related ADR:
- `docs/DECISIONS/ADR-20260220-oil-life-manual-reset.md`

## Scope

### In-scope

- Add a derived backend (`derived`) that:
  - consumes upstream metrics (pressure, optional pump_on)
  - tracks accumulated runtime (seconds)
  - reports `oil_life_pct` (100 → 0) linearly over configured hours
- Durable state:
  - `oil_life_runtime_s`
  - `oil_life_reset_at`
  - `oil_life_last_seen_running_at` (optional)
- Reset mechanism:
  - CLI command on the device (preferred)

Example:

```bash
python -m agent.tools.oil_life reset --state /var/lib/edgewatch/oil_life.json
```

### Out-of-scope

- Fleet-wide remote reset (could be added later behind admin identity)

## Design notes

### “Running” detection

Default order:

1) If a `pump_on` boolean exists, use it.
2) Else infer from `oil_pressure_psi` with hysteresis:
   - running when `oil_pressure_psi >= run_on_threshold`
   - stopped when `oil_pressure_psi <= run_off_threshold`

Both thresholds must be configurable.

### State persistence

- JSON state file is acceptable for MVP.
- Writes should be atomic:
  - write temp + fsync + rename

## Acceptance criteria

- Oil life decreases only while the unit is “running”.
- Oil life remains stable (no increase) unless reset.
- State survives process restart and device reboot.
- Reset sets oil life back to ~100% and updates reset timestamp.
- Unit tests prove:
  - runtime accumulation
  - hysteresis behavior
  - reset behavior

## Deliverables

- `agent/sensors/backends/derived.py` (or `agent/sensors/derived/oil_life.py`)
- `agent/tools/oil_life.py`
- Docs:
  - `docs/RUNBOOKS/SENSORS.md` reset instructions

## Validation

```bash
make fmt
make lint
make typecheck
make test
```
