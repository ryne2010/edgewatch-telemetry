# Task specs

This folder contains **Codex-ready** specs for larger changes.

Each spec should include:
- intent and non-goals
- acceptance criteria
- design notes (boundaries, data model changes)
- validation plan (harness commands)

When a task changes contracts or boundaries, also write an ADR in `docs/DECISIONS/`.

---

## How to execute tasks (recommended)

For each task:

1) Read the durable sources of truth (in order):
   - `docs/DOMAIN.md`
   - `docs/DESIGN.md`
   - `docs/CONTRACTS.md`
   - `docs/WORKFLOW.md`

2) Implement the smallest safe slice.

3) Validate with the harness before finalizing:

```bash
make harness
```

For faster inner loops:

```bash
python scripts/harness.py lint --only python
python scripts/harness.py test --only python
python scripts/harness.py lint --only node
```

---

## Queue status

### Implemented

- `01-alert-routing-rules.md`
- `02-notification-adapters.md`
- `03-telemetry-contracts.md`
- `04-lineage-artifacts.md`
- `05-production-jobs-cloud-scheduler.md`
- `06-db-migrations-alembic.md`
- `07-replay-backfill.md`
- `08-ci-cd-github-actions-wif.md`
- `09-event-driven-ingest-pubsub.md`
- `10-analytics-export-bigquery.md`
- `11a-agent-sensor-framework.md`
- `11b-rpi-i2c-temp-humidity.md`
- `11c-rpi-adc-pressures-levels.md`
- `11d-derived-oil-life-reset.md`
- `12a-agent-camera-capture-ring-buffer.md`
- `12b-api-media-metadata-storage.md`
- `12c-web-media-gallery.md`
- `13-cellular-connectivity.md` (epic)
- `13a-cellular-runbook.md`
- `13b-agent-cellular-metrics-watchdog.md`
- `13c-cost-caps-policy.md`
- `15-authn-authz.md`
- `16-opentelemetry.md`
- `17-telemetry-partitioning-rollups.md` (Postgres scale path)
- `18-iap-identity-perimeter.md`
- `19-agent-buffer-hardening.md` (WAL mode, disk quota, corruption recovery)

### In progress / partial

- `14-ui-ux-polish.md` (core UX shipped; remaining items tracked inside)

### Planned

#### Requested “field-realistic edge node” scope

- `11-edge-sensor-suite.md` (epic)

- `12-camera-capture-upload.md` (epic)

#### Production upgrades

- `20-edge-protection-cloud-armor.md` (Cloud Armor / API Gateway posture for public ingest)
