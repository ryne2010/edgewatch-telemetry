# Next iteration roadmap

This document captures **validated** next steps after **v0.14.x**, focused on taking EdgeWatch from “strong demo” to a **production-grade, multi-environment IoT telemetry platform**.

The repo targets:

- **Development:** M2 Max MacBook Pro
- **Production:** Cloud Run + Cloud SQL Postgres + Secret Manager, with Raspberry Pi agents

---

## What’s already in place

### Multi-environment deployment posture

- Terraform-first Cloud Run deploy lane (`infra/gcp/cloud_run_demo/`)
- Least-privilege multi-service topology:
  - public ingest (optional)
  - private dashboard (optional)
  - private admin (optional)
- Route surface toggles so each service can expose only what it needs.

### Multi-arch image publishing

- A single tag can include both:
  - `linux/amd64` (Cloud Run)
  - `linux/arm64` (Apple Silicon / Raspberry Pi)

See: `docs/MULTIARCH_IMAGES.md`

---

## 1) Field-realistic edge node (sensors + camera + cellular)

This is the requested product scope for real deployments.

### Sensors

Epic: `docs/TASKS/11-edge-sensor-suite.md`

- 11a — framework + config
- 11b — I2C temp/humidity
- 11c — ADC pressures + levels
- 11d — derived oil life + reset

### Camera

Epic: `docs/TASKS/12-camera-capture-upload.md`

- 12a — device capture + ring buffer
- 12b — API metadata + storage (local + GCS)
- 12c — UI media gallery

### Cellular

Epic: `docs/TASKS/13-cellular-connectivity.md`

- 13a — bring-up runbook
- 13b — agent cellular metrics + link watchdog
- 13c — policy cost caps + enforcement

---

## 2) Identity-based operator access (no shared admin secrets)

This is the “top-notch” professional posture:

- public ingest has **no UI/read/admin**
- dashboard/admin are behind Google identity login

Tracked by:

- `docs/TASKS/18-iap-identity-perimeter.md`
- `docs/TASKS/15-authn-authz.md`

---

## 3) Observability upgrades

**Implemented today:** optional FastAPI tracing (`ENABLE_OTEL=1`).

Next steps:

- SQLAlchemy instrumentation
- basic metrics
- align with Cloud Monitoring dashboards/SLOs

Tracked by:

- `docs/TASKS/16-opentelemetry.md`

---

## 4) Storage scale path

High-frequency telemetry fleets can outgrow a single hot table.

Tracked by:

- `docs/TASKS/17-telemetry-partitioning-rollups.md`

---

## 5) Edge agent robustness

Tracked by:

- `docs/TASKS/19-agent-buffer-hardening.md`

---

## 6) Public ingest edge protection

Tracked by:

- `docs/TASKS/20-edge-protection-cloud-armor.md`
