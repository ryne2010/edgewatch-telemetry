# ADR: Oil life is runtime-derived with manual reset

Date: 2026-02-20  Status: Accepted

## Context

"Oil life %" is a requested metric but is usually not available as a direct sensor
reading in low-cost edge deployments. We need a model that is:

- simple and explainable
- stable under intermittent connectivity
- easy to reset after maintenance
- good enough for a demo/staging environment

The user preference is **manual reset**.

## Decision

Oil life (`oil_life_pct`) will be computed as a **derived metric** based on cumulative
"engine/pump runtime" since the most recent manual reset:

- A reset event sets `oil_life_reset_at` and `oil_life_runtime_s = 0`.
- While the equipment is considered "running", runtime accumulates.
- Oil life decreases linearly from 100% to 0% over a configurable max runtime:

  `oil_life_pct = max(0, 100 * (1 - runtime_hours / oil_life_max_run_hours))`

Defaults:

- `oil_life_max_run_hours`: 250 (configurable per installation)

"Running" detection (default order):

1. If a `pump_on` boolean is available, use it.
2. Otherwise, infer running state from `oil_pressure_psi > oil_pressure_low_psi` with hysteresis.

State will be stored durably on the device (small JSON/TOML file) so reboots do not
reset oil life.

Optionally (future), the reset event may be sent to the server as an audit record.

## Consequences

- ✅ Simple, explainable, and easy to implement/test
- ✅ Manual reset matches real maintenance workflows
- ✅ Works offline (state lives on the device)
- ❌ Accuracy depends on correct "running" detection
- ❌ Linear model is crude vs true oil condition monitoring

## Alternatives considered

- **Oil quality sensor / conductivity sensor**
  - Pros: measures actual oil properties
  - Cons: adds cost/complexity; harder to calibrate
- **Model based on temperature/pressure cycles**
  - Pros: more nuanced
  - Cons: harder to validate/explain; requires more tuning
- **Server-derived oil life**
  - Pros: centralized and auditable
  - Cons: less reliable offline; requires stronger device/server coupling

## Rollout / migration plan

- Keep `oil_life_pct` in the telemetry contract.
- Implement derived oil life in the edge agent sensor pipeline (`agent/sensors/derived/oil_life.py`).
- Add a device-local command/API to reset oil life (MVP: local CLI; later: UI action).

## Validation

- Unit tests for the oil life function and state persistence.
- Simulated "running" periods reduce oil life predictably.
- Manual reset returns `oil_life_pct` to ~100% and clears runtime.
