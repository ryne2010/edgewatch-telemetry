# Task: Telemetry contracts + drift handling

✅ **Status: Implemented** (2026-02-20)

## Intent

Introduce a lightweight "data contract" for telemetry metrics so the system can:
- validate expected keys/types
- detect drift (additive vs breaking)
- produce a small lineage artifact per ingestion

This bridges a "data architect"-style contract/governance story into EdgeWatch without turning it into a full warehouse product.

## Non-goals

- Full schema registry.
- Real-time stream processing.

## Acceptance criteria

- A versioned telemetry contract exists (ex: YAML under `contracts/telemetry/`).
- Ingest validates metrics against the active contract:
  - unknown keys are either allowed (additive) or flagged (configurable)
  - type mismatches are rejected or quarantined (configurable)
- Drift events are recorded as alerts or audit events.

## Design notes

- Keep contract parsing/validation isolated (pure functions).
- Store contract version/hash with ingested points or with an ingestion log row.

## Validation

```bash
make lint
make typecheck
make test
```
