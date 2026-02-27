# EdgeWatch Telemetry (Local‑first) — Edge → API → Postgres → Alerts

## Quickstart

Local-first dev (recommended):

```bash
make doctor
make up

# If you plan to run harness tasks or develop the UI locally:
make doctor-dev
```

For a tighter inner loop (API + UI hot reload on your Mac, Postgres in Docker), see `docs/DEV_FAST.md`.

Hardware + edge node scope (sensors/cameras/LTE): see `docs/HARDWARE.md`.


Optional GCP demo deploy:

```bash
make init GCLOUD_CONFIG=edgewatch-demo PROJECT_ID=YOUR_PROJECT_ID REGION=us-central1
make auth          # only needed once per machine/user
make doctor-gcp
make admin-secret
# make db-secret   # only if enable_cloud_sql=false and you provide external Postgres

# Public demo (dev)
make deploy-gcp-demo

# Or: staging posture (private IAM-only) + synthetic telemetry enabled
make deploy-gcp-stage

# Or: production posture (private IAM-only)
make deploy-gcp-prod

# Or: explicit lane
# make deploy-gcp-safe ENV=dev
# or: make deploy-gcp ENV=dev && make migrate-gcp ENV=dev && make verify-gcp-ready ENV=dev
```

Want a **single image tag** that runs on Cloud Run (`amd64`) and on arm64 devices (Apple Silicon / Raspberry Pi)?
See: `docs/MULTIARCH_IMAGES.md` (includes a GitHub Actions multi-arch publish workflow).

EdgeWatch is a reference implementation of a **lightweight edge telemetry platform** for scenarios like:
- well/pump monitoring (online/offline heartbeat, pressure thresholds)
- remote equipment status
- “low IT overhead” operations that still need **reliability + auditability**

It is designed to be:
- **Local-first** (runs entirely on Docker Compose)
- **Open source only** (no proprietary services required)
- **Cloud-ready** (optional GCP deployment notes included)

## Key features

- **Device heartbeat + last-seen tracking** (online/offline detection)
- **Idempotent ingestion** (dedupe using `(device_id, message_id)`)
- **Local buffering on the device** (SQLite queue; flush on reconnect)
- **Device policy** (ETag-cached config for energy/data optimization)
- **Telemetry contracts** (type safety + drift visibility)
- **Ingestion batches** (contract hash + drift summary + source/pipeline metadata per ingest)
- **Drift events + quarantine lane** (optional type-mismatch quarantine with auditable events)
- **Alerts**
  - device offline / online
  - metric thresholds (water pressure, battery, signal)
  - routing rules (quiet hours, dedupe, throttling) + auditable notification events
- **Synthetic telemetry generator** (Cloud Run Job + Scheduler) for dev/stage environments
- **Retention / compaction job** (Cloud Run Job + Scheduler) to bound Cloud SQL storage growth
- **Replay tooling** (`python -m agent.replay`) for idempotent edge backfill by time range
- **Optional Pub/Sub ingest mode** (`INGEST_PIPELINE_MODE=pubsub`) with worker push endpoint
- **Optional BigQuery export lane** (Cloud Run Job + Scheduler + watermark-based exports)
- **Time-series API**
  - raw points
  - server-side bucketing (minute/hour) for charts
- **Admin API** (protected by `ADMIN_API_KEY`) to register devices
- **DB schema migrations** via Alembic

> Note: This repo is intentionally “platform + patterns.” It’s not a full IoT fleet manager.

---

## Quickstart (local)

macOS dev notes: see `docs/DEV_MAC.md`.

### 1) Requirements
- Docker + Docker Compose

### 2) Configure environment

```bash
cp .env.example .env
```

### 3) Start the stack

```bash
make up
```

`docker compose` will run migrations automatically via the `migrate` one-off service.

If you pull new changes with schema updates:

```bash
make db-migrate
```

If you want a clean slate:

```bash
make reset
make up
```

Endpoints:
- UI (React + TanStack): `http://localhost:8082`
- Swagger docs: `http://localhost:8082/docs`
- Retention runbook: `docs/RUNBOOKS/RETENTION.md`
- API base: `http://localhost:8082/api/v1`

Fast dev lane (tight edit → reload loop):

```bash
make dev      # db + api hot reload + web dev + simulator fleet
```

Manual equivalent:

```bash
make db-up
make api-dev   # API w/ hot reload on http://localhost:8080

# In a second terminal:
make web-dev   # UI dev server on http://localhost:5173 (proxies /api to :8080)
```

Optional toggles:

```bash
DEV_START_SIMULATE=0 make dev         # disable simulator
DEV_STOP_DB_ON_EXIT=1 make dev        # also stop DB when exiting
DEV_BOOTSTRAP_DEMO_DEVICE=0 make dev  # skip demo-device bootstrap
```

### 4) Create a demo device (admin)

```bash
make demo-device
```

### 5) Run the simulator (pretends to be a Raspberry Pi / edge device)

In a new terminal:

```bash
make simulate
```

If you don’t run the simulator (or a real agent), the UI will show devices but no telemetry points.

`make simulate` runs a 3-device demo fleet by default. Override with `SIMULATE_FLEET_SIZE=1 make simulate`.

### 6) Check device status

```bash
make devices
```

### 7) View recent alerts

```bash
make alerts
```

### 8) Replay buffered history (optional)

```bash
uv run python -m agent.replay \
  --since 2026-01-01T00:00:00Z \
  --until 2026-01-02T00:00:00Z \
  --batch-size 100 \
  --rate-limit-rps 2
```

---

## API overview

- `POST /api/v1/ingest` — device telemetry ingestion (requires Bearer token)
- `GET  /api/v1/devices` — list devices with computed status (online/offline)
- `GET  /api/v1/devices/summary` — fleet-friendly list (status + latest vitals)
- `GET  /api/v1/devices/{device_id}` — device detail (computed status)
- `GET  /api/v1/devices/{device_id}/telemetry` — raw telemetry points
- `GET  /api/v1/devices/{device_id}/timeseries` — bucketed time series
- `GET  /api/v1/alerts` — alerts
- `GET  /api/v1/contracts/telemetry` — active telemetry contract
- `GET  /api/v1/contracts/edge_policy` — active edge policy contract
- `GET  /api/v1/device-policy` — device policy (Bearer token; ETag cached)
- `POST /api/v1/admin/devices` — register device (admin only)
- `GET  /api/v1/admin/ingestions` — ingestion batch audit (admin only)
- `GET  /api/v1/admin/drift-events` — drift event audit (admin only)
- `GET  /api/v1/admin/notifications` — notification delivery decisions (admin only)
- `GET  /api/v1/admin/exports` — analytics export batch audit (admin only)

Infra endpoints:
- `GET /health`
- `GET /readyz` (includes DB + migration check)
- `POST /api/v1/internal/pubsub/push` (internal worker endpoint for Pub/Sub push)

---

## Architecture

Local (single process):

```
Edge device (RPi)
   |  HTTPS + Bearer token
   v
FastAPI Ingest API  -----> Postgres (devices, telemetry_points, alerts)
   |                         ^
   | APScheduler (dev)        |
   v                         |
Offline monitor + alerting --+
```

Production (Cloud Run):
- disable in-process scheduling (`ENABLE_SCHEDULER=0`)
- run offline checks as a Cloud Run Job triggered by Cloud Scheduler

See `docs/architecture.md` for more detail.

---

## Security model (reference)

- Each device authenticates using an **opaque token** (`Authorization: Bearer <token>`).
- Server stores only a **PBKDF2 hash** of the token (never plaintext).
- Admin operations are optional and configurable:
  - `ENABLE_ADMIN_ROUTES=0` removes `/api/v1/admin/*` entirely
  - `ADMIN_AUTH_MODE=key|none` chooses between `X-Admin-Key` or trusting an infrastructure perimeter

See `docs/security.md` for threat model notes and hardening recommendations.

---

## Optional GCP deployment (Cloud Run demo)

This repo includes a working, team-ready Cloud Run demo deployment (Terraform + Cloud Build).

See:
- `docs/START_HERE.md`
- `docs/DEPLOY_GCP.md`
- `docs/TEAM_WORKFLOW.md`
- `docs/NEXT_ITERATION.md`

### Cost-minimized production posture

If your goal is to keep costs minimal while staying “production-shaped”:

- Cloud Run:
  - `min_instances=0` (scale to zero)
  - `max_instances=1` (hard cap)
  - prefer **IAM auth** (`allow_unauthenticated=false`) for internal deployments (blocks unauth traffic before it hits your container)
- Avoid paid networking add-ons unless you need them:
  - keep `enable_vpc_connector=false`
  - skip Cloud Load Balancer / Cloud Armor until you actually need them
- Background jobs:
  - keep the offline check job, but run it less frequently (default: every 5 minutes)
- Database:
  - expect Cloud SQL to be the dominant cost; use the smallest tier that works, and stop it when you’re not demoing

See `docs/COST_HYGIENE.md` for more detail.

See `docs/PRODUCTION_POSTURE.md` for the full posture breakdown (public demo vs private IAM).

---

## Repo-quality gates (harness)

This repo includes an agent-friendly validation harness. Use it locally and in CI:

```bash
make fmt
make lint
make typecheck
make test
make build
make hygiene
```

Or run directly:

```bash
python scripts/harness.py doctor
python scripts/harness.py all
```

---

## License

MIT — see `LICENSE`.

## Web UI

The UI is a React app that talks to the API (and is also served by the API in production).

- Dashboard (fleet overview)
- Devices list + device detail (charts + raw points)
- Alerts feed
- Contracts page (live telemetry contract)
- Admin audit console (requires `X-Admin-Key`)
- Settings + system/health page

See `docs/WEB_UI.md` for a UI walkthrough.

## Edge agent (Raspberry Pi)

The `agent/` folder contains a small Python agent intended to run on a Raspberry Pi (or similar Linux SBC) and send telemetry to the API.

- Current minimal Raspberry Pi profile is microphone-only (`microphone_level_db`).
- Default poll cadence is 10 minutes via edge policy (`sample_interval_s=600`).
- API raises `MICROPHONE_OFFLINE` when level is below threshold (`microphone_offline_db`, default 60).
- Dual-mode power management supports solar or 12V battery input with INA219/INA260 (`rpi_power_i2c`).
- API lifecycle alerts include `POWER_INPUT_OUT_OF_RANGE`/`POWER_INPUT_OK` and `POWER_UNSUSTAINABLE`/`POWER_SUSTAINABLE`.
- Buffers locally when offline (SQLite)
- Retries with backoff
- Flushes buffered points when connectivity returns

See `docs/DEPLOY_RPI.md` for a systemd deployment.

## UI stack

- Vite + React
- TanStack Router/Query/Table + Virtual + Pacer + Ranger
- Tailwind + shadcn-style components (vendored in `web/src/ui-kit`)

## Packaging

To create a clean zip archive (no caches, no node_modules, no terraform state):

```bash
make dist
```

The output is written under `./dist/`.
