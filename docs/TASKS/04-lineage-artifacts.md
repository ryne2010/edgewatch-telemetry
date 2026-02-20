# Task: Lineage artifacts (audit-friendly ingestion log)

✅ **Status: Implemented** (2026-02-20)

## Intent

Add a lightweight **lineage / audit trail** for telemetry ingestion so operators can answer:

- *What data arrived, when, and from which device?*
- *Which contract/version was used to validate it?*
- *Was there drift (unknown keys, type mismatches), and what did we do?*

This bridges the **data architect** story (contracts, drift, lineage) into EdgeWatch without turning it into a full data warehouse.

## Non-goals

- A full enterprise lineage system.
- Replacing BigQuery / dbt / Data Catalog.
- Streaming pipelines.

## Acceptance criteria

- A new persistent artifact exists for each ingestion batch (each call to `POST /api/v1/ingest`).
- Each artifact includes, at minimum:
  - `device_id`
  - `received_at`
  - `num_points`
  - time bounds of the batch (min/max timestamp)
  - contract identifier (version/hash) **if** contracts are enabled
  - drift summary (unknown keys, type mismatches) **if** contracts are enabled
- Artifacts are queryable via API (admin-only or read-only endpoint).
- Unit tests cover:
  - artifact creation on ingest
  - drift summary logic is deterministic

## Design notes

### Data model

Add a table like `ingestion_batches`:

- `id` (UUID)
- `device_id` (FK)
- `received_at` (server timestamp)
- `num_points`
- `min_ts` / `max_ts`
- `contract_version` (nullable)
- `contract_hash` (nullable)
- `drift_summary` (JSONB, nullable)

Keep the schema intentionally small.

### Code boundaries

- Put the persistence logic under `api/app/services/ingestion_audit.py` (or similar).
- Keep `api/app/routes/ingest.py` thin:
  - authenticate
  - write points
  - write ingestion batch artifact

### UI (optional)

- Add a read-only UI page:
  - recent ingestion batches
  - drill down to drift summary

## Validation

```bash
make lint
make typecheck
make test
```
