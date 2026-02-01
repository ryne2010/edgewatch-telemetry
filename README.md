# EdgeWatch Telemetry (Local‑first) — Edge → API → Postgres → Alerts

## Quickstart

Local-first dev (recommended):

```bash
make doctor
make up
```

Optional GCP demo deploy:

```bash
make init GCLOUD_CONFIG=personal-portfolio PROJECT_ID=YOUR_PROJECT_ID REGION=us-central1
make auth          # only needed once per machine/user
make doctor-gcp
make deploy-gcp
```

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
- **Idempotent ingestion** (dedupe using `message_id`)
- **Local buffering on the device** (SQLite queue; flush on reconnect)
- **Alerts**
  - device offline / online
  - metric thresholds (example: water pressure low)
- **Time-series API**
  - raw points
  - server-side bucketing (minute/hour) for charts
- **Admin API** (protected by `ADMIN_API_KEY`) to register devices
- **Open-source OCR not applicable here** (repo focuses on telemetry)

> Note: This repo is intentionally “platform + patterns.” It’s not a full IoT fleet manager.

---

## Quickstart (local)

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

Endpoints:
- UI (React + TanStack): `http://localhost:8082`
- Swagger docs: `http://localhost:8082/docs`
- API base: `http://localhost:8082/api/v1`

### 4) Create a demo device (admin)
```bash
make demo-device
```

### 5) Run the simulator (pretends to be a Raspberry Pi / edge device)

In a new terminal:

```bash
make simulate
```

### 6) Check device status
```bash
make devices
```

### 7) View recent alerts
```bash
make alerts
```

---

## API overview

- `POST /api/v1/ingest` — device telemetry ingestion (requires Bearer token)
- `GET  /api/v1/devices` — list devices with computed status (online/offline)
- `GET  /api/v1/devices/{device_id}/telemetry` — raw telemetry points
- `GET  /api/v1/devices/{device_id}/timeseries` — bucketed time series
- `GET  /api/v1/alerts` — alerts
- `POST /api/v1/admin/devices` — register device (admin only)

---

## Architecture (local)

```
Edge device (RPi) 
   |  HTTPS + Bearer token
   v
FastAPI Ingest API  -----> Postgres (devices, telemetry_points, alerts)
   |                         ^
   | APScheduler             |
   v                         |
Offline monitor + alerting --+
```

See `docs/architecture.md` for more detail.

---

## Security model (reference)

- Each device authenticates using an **opaque token** (`Authorization: Bearer <token>`).
- Server stores only a **bcrypt hash** of the token (never plaintext).
- Admin operations require `X-Admin-Key`.

See `docs/security.md` for threat model notes and hardening recommendations.

---

## Optional GCP deployment (Cloud Run demo)

This repo includes a working, team-ready Cloud Run demo deployment (Terraform + Cloud Build).

```bash
make deploy-gcp
make db-secret
make admin-secret
```

See:
- `docs/DEPLOY_GCP.md`
- `docs/TEAM_WORKFLOW.md`

---

## License
MIT — see `LICENSE`.


## UI stack

- Vite + React
- TanStack Router/Query/Table + Virtual + Pacer + Ranger
- Tailwind + shadcn-style components (vendored in `web/src/portfolio-ui`)

