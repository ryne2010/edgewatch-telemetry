# Task 17 — Telemetry partitioning + rollups (Postgres scale path)

🟡 **Status: Planned**

## Objective

Prepare EdgeWatch for higher-frequency fleets by adding a clear Postgres scale path:

- time-based partitions for `telemetry_points`
- optional rollups for long-range charts
- retention by dropping old partitions (fast + cheap)

This is specifically targeted at **Cloud SQL Postgres** in production.

## Why

Even with retention, a single hot `telemetry_points` table can become:

- expensive to vacuum
- slow for wide-range queries
- a pain point for deletes

Partitioning makes retention and query planning predictable.

## Scope

### In-scope

- Convert `telemetry_points` to a partitioned table (RANGE on `ts`).
- Add an automated partition management strategy:
  - migrations create the parent partitioned table
  - a scheduled job creates upcoming partitions (monthly or weekly)
- Update retention job to:
  - drop partitions older than the retention window
  - fall back to row deletes if partitioning is disabled

- Add “long range chart” rollups (optional, but recommended):
  - `telemetry_rollups_hourly` (device_id + metric key + hour bucket + min/max/avg)

### Out-of-scope

- TimescaleDB migration (can be an alternate path; not required).

## Design notes

### Partition granularity

- Start with **monthly partitions** for simplicity.
- If a fleet runs > 1M points/day, revisit weekly.

### Compatibility

- Ensure existing queries still work:
  - device detail timeseries
  - summary endpoints
  - replay/backfill

### Testing

- Update `tests/test_migrations_sqlite.py` or add a Postgres migration test lane.

## Acceptance criteria

- Partitions are created and used (confirm via query plan).
- Retention drops old partitions in production.
- Queries for recent data remain fast.
- CI passes (migrations + tests).

## Deliverables

- Alembic migrations for partitioning
- Partition manager job (Cloud Run Job + Scheduler hook)
- Docs:
  - `docs/RUNBOOKS/RETENTION.md` updated
  - `docs/PRODUCTION_POSTURE.md` updated

## Validation

```bash
make fmt
make lint
make typecheck
make test

# Postgres-specific validation
make db-migrate
```
