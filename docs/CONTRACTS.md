# CONTRACTS.md

Contracts define **behavioral guarantees** and **compatibility rules**.
Treat these as non-negotiable unless explicitly changed via ADR.

## Public interfaces

### HTTP API (v1)

Base: `/api/v1`

- `POST /ingest` — device telemetry ingestion (Bearer token)
- `GET  /devices` — list devices + computed status
- `GET  /devices/{device_id}` — device detail + computed status
- `GET  /devices/{device_id}/telemetry` — raw telemetry points
- `GET  /devices/{device_id}/timeseries` — bucketed time series
- `GET  /alerts` — recent alerts
- `GET  /device-policy` — edge policy/config for devices (Bearer token; ETag cached)
- `POST /admin/devices` — register device (admin key)

**Compatibility:**
- Endpoints under `/api/v1` are intended to be stable for the portfolio demo.
- Breaking changes should:
  - require an ADR
  - bump the API version path (ex: `/api/v2`) or provide backward compatible behavior

### Infra endpoints

These are intentionally unversioned:
- `GET /health`
- `GET /readyz`

### Device agent payload contract

A telemetry point includes:
- `message_id` (string) — unique per device per point (idempotency key)
- `ts` (datetime) — measurement timestamp
- `metrics` (object) — key/value measurements (numbers/strings)

A request includes:
- `points: TelemetryPoint[]`

## Functional invariants (must always hold)

1) **Idempotent ingest**
- Inserting a telemetry point with a previously-seen `(device_id, message_id)` must not create a new row.
- API response reports `duplicates` count.

2) **Monotonic `last_seen_at`**
- `devices.last_seen_at` should only move forward based on the newest observed point timestamp.

2b) **Contract-aware ingest (type safety + drift visibility)**
- The active telemetry contract lives at `contracts/telemetry/<version>.yaml`.
- Unknown metric keys are accepted (additive drift) and recorded in the ingestion batch.
- Known metric keys must match the declared type when `TELEMETRY_CONTRACT_ENFORCE_TYPES=1`.
- Each ingest returns a `batch_id` that can be used to inspect the ingestion lineage.

3) **Token handling**
- Plaintext device tokens are never stored.
- Authentication uses:
  - fingerprint lookup (SHA-256)
  - PBKDF2 hash verification

4) **Offline alert lifecycle**
- A `DEVICE_OFFLINE` alert is opened at most once while the device remains offline.
- When the device returns online, offline alerts resolve and an optional `DEVICE_ONLINE` alert is created.

6) **Device policy caching**
- `GET /api/v1/device-policy` must support `ETag` + `If-None-Match`.
- Devices should be able to run for long periods without re-downloading policy.

5) **No secret leakage**
- Logs and error messages must not include device tokens, admin keys, or database URLs.

## Compatibility policy

- **Backwards compatible changes:**
  - add new metrics keys
  - add new response fields (non-breaking)
  - add new alert types
- **Breaking changes require:**
  - ADR (`docs/DECISIONS/`)
  - explicit versioning plan
  - migration notes in runbooks

## Data contracts

- Postgres schema is the source of truth for persisted telemetry + alerts.
- Schema evolution is tracked via **Alembic migrations** (`migrations/`).
- Local dev applies migrations via the `migrate` service in `docker-compose.yml` (or `AUTO_MIGRATE=1`).
- Production guidance: run migrations as a separate step/job (Cloud Run Job: `edgewatch-migrate-<env>`).

### Contract artifacts

- **Telemetry contract**: `contracts/telemetry/v1.yaml`
- **Edge policy contract**: `contracts/edge_policy/v1.yaml`
- **Ingestion batches**: persisted in Postgres (`ingestion_batches`) and queryable via:
  - `GET /api/v1/admin/ingestions` (admin key)

## Testing contract

Minimum expectations for changes:
- Unit tests for non-trivial logic (idempotency helpers, status logic, security helpers).
- Regression tests for bug fixes.
- Prefer deterministic tests (avoid wall clock; inject timestamps).

## Observability contract

- **Structured logs** (no secrets)
- **Request correlation** via `X-Request-ID`
- **Infra observability-as-code** lives in `infra/gcp/cloud_run_demo/*`.
