# Start here

This repo is designed to be **productive on an M2 Max MacBook Pro** for development and to deploy to **Cloud Run + Cloud SQL** for production, with a Raspberry Pi agent for edge ingest.

If you're new to the project, follow this doc first, then jump into the detailed runbooks.

## What you get

- FastAPI backend (telemetry ingest, devices, alerts, policies)
- React + Vite web UI (dashboard, device detail, admin provisioning)
- Raspberry Pi agent (direct HTTP ingest or Pub/Sub lane)
- Terraform (Cloud Run service, Cloud SQL Postgres, Secret Manager, scheduled jobs)
- Simulation (Cloud Run Job that generates telemetry in dev/stage)
  - default profile: microphone + power (`rpi_microphone_power_v1`)
  - legacy full profile opt-in: `SIMULATION_PROFILE=legacy_full`
- Retention job (Cloud Run Job + Scheduler to prune old telemetry)

## Prereqs

### Local

- Docker Desktop
- Python 3.11+
- `uv`
- Node 20+
- `pnpm`

Run:

```bash
make doctor
```

### GCP

- `gcloud auth login`
- Terraform 1.6+

Run:

```bash
make doctor-gcp
```

## Local dev

You have two supported development lanes:

### Lane A: Docker Compose (simplest)

Runs **Postgres + API + web UI** in containers.

```bash
make up
open http://localhost:8082
```

### Lane B: Fast inner loop (recommended for day-to-day)

Runs **Postgres in Docker** and runs **API + web dev server on your host** for
faster reloads.

```bash
make db-up
make db-migrate
make api-dev
make web-dev
open http://localhost:5173
```

Optional helpers:

```bash
# Seed a demo device (dev only)
make demo-device

# Run a local simulator fleet that posts telemetry
make simulate
```

Docs:

- Mac setup + troubleshooting: `docs/DEV_MAC.md`
- Local stack details: `docs/DEV_FAST.md`
- Simulation runbook: `docs/RUNBOOKS/SIMULATION.md`

## Deploy to Cloud Run (Terraform)

Choose a profile:

- `dev_public_demo` — public demo posture
- `stage_private_iam` — private IAM posture + simulation
- `prod_private_iam` — private IAM-only posture
- `stage_public_ingest_private_admin` — public ingest + private admin service (IoT posture)
- `prod_public_ingest_private_admin` — public ingest + private admin service (IoT posture)
- `stage_public_ingest_private_dashboard_private_admin` — **recommended** least-privilege IoT posture (public ingest + private dashboard + private admin)
- `prod_public_ingest_private_dashboard_private_admin` — **recommended** least-privilege IoT posture (public ingest + private dashboard + private admin)

Deploy:

```bash
TFVARS=infra/gcp/cloud_run_demo/profiles/stage_private_iam.tfvars make deploy-gcp

# IoT posture example:
# TFVARS=infra/gcp/cloud_run_demo/profiles/stage_public_ingest_private_admin.tfvars make deploy-gcp
```

Convenience targets are also available:

```bash
make deploy-gcp-stage-iot
make deploy-gcp-stage-iot-lp
make deploy-gcp-prod-iot
make deploy-gcp-prod-iot-lp
```

Docs:

- GCP deploy overview: `docs/DEPLOY_GCP.md`
- Manual GCP deploy runbook: `docs/MANUAL_DEPLOY_GCP_CLOUD_RUN.md`
- Multi-arch images (amd64 + arm64): `docs/MULTIARCH_IMAGES.md`
- Terraform stack details: `infra/gcp/cloud_run_demo/README.md`
- Production posture checklist: `docs/PRODUCTION_POSTURE.md`

## Raspberry Pi agent

Docs:

- Setup + provisioning: `docs/RPI_AGENT.md`
- Agent config reference: `agent/README.md`
- Sensor bring-up (microphone-first default): `docs/RUNBOOKS/SENSORS.md`
- Solar/12V power management bring-up: `docs/RUNBOOKS/POWER.md`
- Zero-touch first boot tutorial: `docs/TUTORIALS/RPI_ZERO_TOUCH_BOOTSTRAP.md`
- Owner controls + durable delivery tutorial: `docs/TUTORIALS/OWNER_CONTROLS_AND_COMMAND_DELIVERY.md`
- BYO cellular provider checklist: `docs/TUTORIALS/BYO_CELLULAR_PROVIDER_CHECKLIST.md`
- Hybrid disable safeguard:
  - owner/operator disable is logical-only
  - admin shutdown intent requires `EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=1` on the device

## Operations

Runbooks:

- Alerts + offline checks: `docs/RUNBOOKS/OFFLINE_CHECKS.md`
- Simulation (dev/stage): `docs/RUNBOOKS/SIMULATION.md`
- Retention / compaction: `docs/RUNBOOKS/RETENTION.md`

Observability:

- OpenTelemetry tracing (optional): `docs/OBSERVABILITY_OTEL.md`


## Planning / tasks

- Task specs (Codex-ready): `docs/TASKS/README.md`
- Roadmap milestones: `docs/ROADMAP.md`
- Codex execution guide: `docs/CODEX_HANDOFF.md`
