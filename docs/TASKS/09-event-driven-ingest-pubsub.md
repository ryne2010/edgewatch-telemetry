# Task: Event-driven ingestion (Pub/Sub)

## Intent

Add an **optional** event-driven ingestion lane that decouples device HTTP ingestion from database writes.

This aligns with the "GCP engineer" story (event-driven pipelines) while keeping the default posture **cost-minimized**:
- Cloud Run scales to zero
- Pub/Sub absorbs bursts
- idempotency stays intact

## Non-goals

- Do **not** remove the direct HTTP ingest path.
- Do **not** require devices to authenticate directly to Pub/Sub.
- Do **not** introduce Dataflow unless explicitly requested.

## Proposed architecture

### Default (today)

Device -> `POST /api/v1/ingest` -> Postgres `telemetry_points`

### Optional Pub/Sub lane

Device -> `POST /api/v1/ingest`
- API validates auth + contract
- API writes ingestion batch metadata
- API publishes each point to Pub/Sub topic `telemetry-raw`

Pub/Sub subscription -> Cloud Run "worker" service
- receives push messages
- performs idempotent insert into `telemetry_points`
- updates `devices.last_seen_at`
- triggers alert evaluation

### Why this choice

- Keeps device auth the same (Bearer token)
- Uses service identity for Pub/Sub (no edge credentials)
- Allows the worker to be isolated and scaled separately

## Configuration

Introduce:

- `INGEST_PIPELINE_MODE=direct|pubsub` (default: `direct`)

## Data model

No changes required if the worker writes to existing tables.

Optional: add `pubsub_message_id` to `ingestion_batches` for correlation.

## Terraform/IaC

Add modules (demo stack):
- Pub/Sub topic
- subscription (push)
- dead-letter topic + DLQ subscription (optional)

IAM:
- Cloud Run worker SA: `roles/pubsub.subscriber`
- API SA: `roles/pubsub.publisher`

## Acceptance criteria

- `INGEST_PIPELINE_MODE=direct` behaves exactly as today.
- `INGEST_PIPELINE_MODE=pubsub`:
  - ingest endpoint acks quickly after publish
  - worker processes points and persists them
  - idempotency remains enforced via `(device_id, message_id)`
  - alerting continues to work

## Validation plan

```bash
make fmt
make lint
make typecheck
make test
make build

# Local end-to-end (docker compose)
make up
make demo-device
make simulate
```

Add a smoke test script that:
- publishes N points
- waits
- verifies counts via `GET /api/v1/devices/{id}/telemetry`
