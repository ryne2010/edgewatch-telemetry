# ADR-20260227: Production Simulation Requires Explicit Opt-In

## Status

Accepted

## Context

EdgeWatch uses synthetic telemetry to keep demos live across environments, but
production environments must avoid accidental synthetic data generation.

Prior behavior hard-disabled simulation in `prod`, which prevented intentional
validation drills in controlled production windows.

## Decision

Introduce a two-layer opt-in model for production simulation:

1. Runtime gate:
- environment variable `SIMULATION_ALLOW_IN_PROD` (default `false`)
- simulation job exits early when `APP_ENV=prod` and this flag is not enabled

2. Terraform acknowledgement:
- variable `simulation_allow_in_prod` (default `false`)
- `enable_simulation=true` in `prod` is only allowed when `simulation_allow_in_prod=true`

Also keep prod profile defaults with simulation disabled.

## Consequences

- Dev/stage continue to support always-available simulation.
- Production simulation is possible for controlled exercises, but only with
  explicit operator acknowledgement.
- Risk of accidental synthetic data in production is reduced by default.
