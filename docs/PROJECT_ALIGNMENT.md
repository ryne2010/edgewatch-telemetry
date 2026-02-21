# Project alignment

This repository is intentionally shaped to demonstrate **production-minded engineering** across two overlapping tracks:

- **GCP / Platform / DevSecOps engineering**
- **Data architecture / governance / operational data platforms**

The goal is not to build every possible feature; it is to ship a small, coherent system with:

- strong defaults
- clear contracts and invariants
- an operations-ready posture (observability, runbooks, incident readiness)
- IaC-first deployment (Terraform + CI/CD)

## What this repo demonstrates today

### GCP / Platform / DevSecOps

- Terraform-first deploy lane (`infra/gcp/cloud_run_demo/`)
- CI/CD with Workload Identity Federation (`docs/WIF_GITHUB_ACTIONS.md`)
- Secret handling + least privilege patterns (see `docs/security.md`)
- Observability-as-code (dashboards/log views/SLOs) under `infra/gcp/cloud_run_demo/`
- **Environment parity** tooling:
  - local Docker Compose lane
  - Cloud Run migration/offline/simulation jobs

### Data architecture patterns

- Telemetry data contracts (`contracts/telemetry/*`)
- Drift visibility + quarantine/reject posture (`docs/CONTRACTS.md`, admin endpoints)
- Lineage artifacts per ingest (`ingestion_batches`, `docs/TASKS/04-lineage-artifacts.md`)
- Replay/backfill tooling for correctness (`docs/TASKS/07-replay-backfill.md`)
- Optional analytics export lane (BigQuery) (`docs/TASKS/10-analytics-export-bigquery.md`)

## What we are expanding next

### Field-realistic edge node

Planned scope:

- Sensors: temperature, humidity, oil pressure, oil level, oil life % (manual reset), drip oil level, water pressure
- Media: up to 4 cameras (one active at a time)
- Connectivity: LTE data SIM

Tracked by:

- `docs/TASKS/11-edge-sensor-suite.md`
- `docs/TASKS/12-camera-capture-upload.md`
- `docs/TASKS/13-cellular-connectivity.md`

### Production-grade UI/UX

Tracked by:

- `docs/TASKS/14-ui-ux-polish.md`

## Suggested end-to-end walkthrough

If you need a crisp system walk-through:

1) Show a device sending contracted telemetry → ingestion batches show contract hash + drift summary.
2) Trigger a low water pressure event → alert opens; notification routing enforces dedupe/throttling/quiet hours.
3) Pull the device offline → `DEVICE_OFFLINE` opens; bring it back → buffered points replay; duplicates are prevented.
4) (Optional) Export to BigQuery → run a sample query.
5) Show Terraform deploy lane + monitoring-as-code.
