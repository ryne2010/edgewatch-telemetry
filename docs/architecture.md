# Architecture

EdgeWatch is intentionally simple and local-first:

```
Edge device (RPi, NUC, etc.)
  - reads sensors / system signals
  - buffers locally if offline (SQLite queue)
  - sends batched telemetry when online

        HTTPS + Bearer token
                |
                v
FastAPI API (ingest + query)
  - validates + dedupes messages (message_id)
  - updates last_seen
  - writes telemetry_points to Postgres
  - creates/resolves alerts (threshold + offline)

                |
                v
Postgres
  - devices
  - ingestion_batches (contract hash + drift visibility)
  - telemetry_points (JSONB metrics)
  - alerts

Schema evolution:
  - Alembic migrations (`migrations/`)
```

## Online/offline detection

- Each device record has:
  - `last_seen_at`
  - `offline_after_s`

### Dev mode (single process)

In local/dev, an in-process scheduler can run every `OFFLINE_CHECK_INTERVAL_S` to:
- create a `DEVICE_OFFLINE` alert if `now - last_seen_at > offline_after_s`
- resolve the offline alert (and optionally emit a `DEVICE_ONLINE` event) when the device returns

### Production mode (Cloud Run)

Cloud Run services can scale horizontally. To avoid duplicate work:
- disable in-process scheduling (`ENABLE_SCHEDULER=0`)
- trigger the offline check as a **Cloud Run Job** on a schedule via **Cloud Scheduler**

See: `infra/gcp/cloud_run_demo/jobs.tf`.

## Threshold alerts

Example included:
- `WATER_PRESSURE_LOW` if `water_pressure_psi < water_pressure_low_psi`

Thresholds come from the **edge policy contract**:
- `contracts/edge_policy/v1.yaml`

The alert is “stateful”:
- it opens when the metric crosses below threshold
- it resolves when the metric returns to normal (with hysteresis via a separate recover threshold)

## Device policy (battery & data optimization)

Devices fetch a small policy document from the API:
- `GET /api/v1/device-policy` (Bearer token)

The endpoint supports **ETag caching** so devices can avoid re-downloading policy.
The agent uses policy to:
- send immediately on alert transitions
- send minimal heartbeats when stable
- send on meaningful deltas (thresholded)
- buffer offline safely and flush on reconnect

## Data model highlights

- Telemetry points are stored as JSONB metrics so you can add new signals without schema changes.
- A lightweight **telemetry contract** (`contracts/telemetry/v1.yaml`) defines expected keys/types.
  - Unknown keys are accepted (additive drift)
  - Type mismatches for known keys are rejected (breaking drift)
- Each ingest creates an **ingestion batch** row that captures:
  - contract version/hash
  - duplicates
  - unknown metric keys
- `(device_id, message_id)` is unique to enforce idempotent ingestion *per device*.

For a larger implementation, you would likely:
- add per-metric typed columns for high-value metrics
- partition telemetry points by time (native Postgres partitioning)
- add a streaming buffer (Pub/Sub / Kafka) and a worker for enrichment
