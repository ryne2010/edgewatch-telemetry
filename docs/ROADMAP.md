# Roadmap

This roadmap is organized into **milestones**.

EdgeWatch is intentionally built as a:

- **production-minded demo** (good engineering hygiene, docs, runbooks)
- that can also become a **real field node** (RPi + sensors + cellular + camera)

The repo runs locally on a laptop, but the same patterns scale to GCP.

---

## Milestone 1: MVP telemetry + alerts + platform baseline (DONE)

✅ Edge agent + simulator
- Device policy fetch + caching (ETag / max-age)
- Offline buffering with durable sqlite queue
- Cost-aware send strategy (delta thresholds + heartbeat)

✅ API + storage
- Contract-enforced ingest endpoint
- Postgres storage (JSONB metrics)
- Drift visibility + quarantine/reject posture
- Lineage artifacts: `ingestion_batches` table with payload/contract hashes

✅ Alerting + routing
- Monitor loop (offline + thresholds)
- Alert routing rules (dedupe/throttle/quiet hours)
- Notification adapter(s)

✅ UI
- Dashboard + Devices + Alerts + Device detail telemetry explorer
- Admin console lanes (when enabled)

✅ Harness engineering
- Make targets + onboarding doctor
- Pre-commit hooks + CI gates
- Repo hygiene scripts

✅ GCP deploy lane
- Terraform Cloud Run baseline + env profiles
- Cloud Run Jobs + Scheduler (simulation + retention)
- Split services and route-surface toggles for least-privilege IoT posture
- Multi-arch image publishing workflow

---

## Milestone 2: Field-realistic edge node (requested scope)

This milestone expands the edge node to match a "real" remote equipment monitor.

### Sensors

- temperature (°C)
- humidity (%)
- oil pressure (psi)
- oil level (%)
- oil life (%) (runtime-derived; manual reset)
- drip oil level (%)
- water pressure (psi)

Tracked by:
- `docs/TASKS/11-edge-sensor-suite.md` (epic)
  - `11a` / `11b` / `11c` / `11d`

### Media

- up to 4 cameras per node (photo + short video clips)
- one camera active at a time (switched adapter)

Tracked by:
- `docs/TASKS/12-camera-capture-upload.md` (epic)
  - `12a` / `12b` / `12c`

### Connectivity

- data SIM (LTE) with cost-aware send behavior

Tracked by:
- `docs/TASKS/13-cellular-connectivity.md` (epic)
  - `13a` / `13b` / `13c`

---

## Milestone 3: Operator posture (production-grade)

These upgrades map well to GCP platform / DevSecOps / data engineering job expectations.

### Identity + access control

- IAP / identity perimeter for dashboard + admin
- RBAC roles (viewer/operator/admin)

Tracked by:
- `docs/TASKS/18-iap-identity-perimeter.md`
- `docs/TASKS/15-authn-authz.md`

### Observability

- OpenTelemetry instrumentation (FastAPI present; expand to SQLAlchemy + metrics)

Tracked by:
- `docs/TASKS/16-opentelemetry.md`

### Scale path

- Partitioned telemetry table + rollups

Tracked by:
- `docs/TASKS/17-telemetry-partitioning-rollups.md`

### Edge protection

- Cloud Armor / API Gateway posture for public ingest

Tracked by:
- `docs/TASKS/20-edge-protection-cloud-armor.md`

### Edge agent hardening

- Buffer WAL mode + disk quota + corruption recovery

Tracked by:
- `docs/TASKS/19-agent-buffer-hardening.md`

---

## Stretch milestone: anomaly detection

- Baseline modeling per device
- Alert on anomalies (e.g., pressure decay, unusual pump cycles)
- Backtesting + alert fatigue controls
