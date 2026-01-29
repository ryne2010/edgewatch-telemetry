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
  - telemetry_points (JSONB metrics)
  - alerts
```

## Online/offline detection

- Each device record has:
  - `last_seen_at`
  - `offline_after_s`

- A background scheduler job runs every `OFFLINE_CHECK_INTERVAL_S` and:
  - creates a `DEVICE_OFFLINE` alert if `now - last_seen_at > offline_after_s`
  - resolves the offline alert (and optionally emits a `DEVICE_ONLINE` event) when the device returns

## Threshold alerts

Example included:
- `WATER_PRESSURE_LOW` if `water_pressure_psi < DEFAULT_WATER_PRESSURE_LOW_PSI`

The alert is “stateful”:
- it opens when the metric crosses below threshold
- it resolves when the metric returns to normal

## Data model highlights

- Telemetry points are stored as JSONB metrics so you can add new signals without schema changes.
- `message_id` is unique to enforce idempotent ingestion.

For a larger implementation, you would likely:
- add per-metric typed columns for high-value metrics
- partition telemetry points by time (native Postgres partitioning)
- add a streaming buffer (Pub/Sub / Kafka) and a worker for enrichment
