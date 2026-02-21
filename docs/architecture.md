# Architecture

This is the extended architecture doc for **EdgeWatch Telemetry**.

If you want the 30-second overview, see the top-level `ARCHITECTURE.md`.

## System goals

- Collect telemetry from edge nodes (Raspberry Pi) in unreliable networks.
- Provide **near-real-time observability** for operators:
  - device state (online/offline)
  - sensor vitals (water/oil pressure, oil level/life, battery, RSSI)
  - alerts and alert history
- Support **fleet scaling** (many devices) and **clear operations**:
  - scheduled jobs (offline checks, simulation, retention)
  - structured logging with request IDs
  - Terraform-defined infrastructure

## Components

### 1) Edge agent (Raspberry Pi)

Location: `agent/`

Responsibilities:

- Authenticate using a **device token**.
- Fetch device policy (`GET /api/v1/device-policy`) with ETag + Cache-Control.
- Sample sensors and apply device-side optimizations:
  - cadence policies (normal vs alert sampling)
  - delta suppression (send only meaningful changes)
  - buffering and store-and-forward when offline
- Ship batches to the API using `POST /api/v1/ingest`.

Status:

- The agent ships with a **mock sensor backend** for simulation.
- Real sensor + camera + cellular integrations are tracked under `docs/TASKS/`.

### 2) API service (FastAPI)

Location: `api/app/`

Responsibilities:

- Device provisioning (admin)
- Device auth + ingest
- Contract validation + drift tracking
- Persistence to Postgres
- Alerting logic
- Serve the web UI in production (single Cloud Run service)

Key routes:

- `POST /api/v1/ingest` — primary write path
- `GET /api/v1/devices` / `GET /api/v1/devices/{id}` — ops UI read paths
- `GET /api/v1/alerts` — alert feed
- `GET /api/v1/device-policy` — edge policy contract for cadence + thresholds
- `POST /api/v1/admin/devices` — provision devices (admin surface; may be disabled or perimeter-protected)

### 3) Web UI (React + Vite)

Location: `web/`

Responsibilities:

- Operator experience: dashboard, devices, device detail (charts + latest), alerts feed
- Admin experience: create/rotate device tokens

Deployment:

- In Cloud Run, the UI is built into the API container and served as static assets.
- In local dev, Vite runs on `localhost:5173` and proxies to the API.

### 4) Database (Postgres)

Location:

- Models: `api/app/models.py`
- Migrations: `migrations/`

Data model highlights:

- `devices` — device metadata and token hash
- `telemetry_points` — time-series points (per device)
- `alerts` — alert instances with resolve timestamps
- `ingestion_batches` — lineage tracking for each ingest request
- `telemetry_quarantine` — rejected/isolated points for forensic review

### 5) Infrastructure (Terraform)

Location: `infra/gcp/cloud_run_demo/`

Provides:

- Cloud Run service (API + UI)
- Cloud SQL Postgres (optional but enabled in profiles)
- Secret Manager for `DATABASE_URL` and `ADMIN_API_KEY`
- Cloud Run Jobs:
  - migrations
  - offline check
  - simulation (dev/stage)
  - retention
  - analytics export (optional)
- Cloud Scheduler triggers (for jobs)

## Data flows

### Ingest (direct pipeline)

```
[RPi Agent] --(POST /api/v1/ingest + Bearer token)--> [API]
   |                                                     |
   | (contract validation + drift/quarantine)             |
   +---------------------------------------------------->|
                                                         |
                                                     [Postgres]
```

Notes:

- `contracts/telemetry/*` defines expected metrics and types.
- Unknown keys are allowed (additive drift) but recorded.
- Type mismatches can be rejected or quarantined (configurable).

### Ingest (Pub/Sub pipeline - optional)

```
[RPi Agent] --(POST /api/v1/ingest)--> [API] --(publish)--> [Pub/Sub]
                                                       |
                                                  [Worker push]
                                                       v
                                                     [API]
                                                       |
                                                   [Postgres]
```

This mode is useful when you need:

- buffering between ingest bursts and DB
- async processing
- future fan-out (analytics, alerting, enrichment)

### Offline checks + alerting

- Offline checks run as a scheduled job (in production) or in-process scheduler (dev).
- Alert creation is deduped + throttled to avoid noisy notifications.

### Simulation (dev + staging)

- Terraform profiles `dev_public_demo` and `stage_private_iam` enable the simulation job.
- `prod_private_iam` keeps simulation disabled.

## Operational posture

See:

- `docs/PRODUCTION_POSTURE.md` for environment profiles and recommended controls
- `docs/security.md` for threat model and hardening guidance
- `docs/RUNBOOKS/` for operational playbooks

## Planned upgrades

See `docs/NEXT_ITERATION.md` for the prioritized roadmap.
