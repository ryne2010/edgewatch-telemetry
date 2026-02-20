# Change Summary

## What changed?

- Completed remaining Codex task specs across alerts, contracts/lineage, replay/backfill, and optional pipeline/analytics lanes.
- Added alert routing + delivery auditing:
  - New services: `api/app/services/routing.py`, `api/app/services/notifications.py`
  - New persistence: `alert_policies`, `notification_events`
  - Wired notifications into all server-side alert creation paths in `api/app/services/monitor.py`.
- Extended contract-aware ingest and lineage:
  - New ingest prep/runtime services: `api/app/services/ingest_pipeline.py`, `api/app/services/ingestion_runtime.py`
  - Ingest now supports unknown-key mode (`allow|flag`) and type mismatch mode (`reject|quarantine`).
  - Added drift/quarantine persistence: `drift_events`, `quarantined_telemetry`.
  - Enriched `ingestion_batches` with drift summary, source/pipeline metadata, and processing state.
  - Added audit endpoints in `api/app/routes/admin.py` (`/admin/drift-events`, `/admin/notifications`, `/admin/exports`).
- Added optional Pub/Sub ingest lane:
  - `INGEST_PIPELINE_MODE=direct|pubsub` handling in `api/app/routes/ingest.py`.
  - New internal worker endpoint: `api/app/routes/pubsub_worker.py`.
  - New Pub/Sub helper service: `api/app/services/pubsub.py`.
- Added optional BigQuery export lane:
  - New export service/job: `api/app/services/analytics_export.py`, `api/app/jobs/analytics_export.py`.
  - New `export_batches` lineage/audit model.
- Added replay/backfill tooling:
  - New agent CLI: `agent/replay.py` (time-bounded replay, batching, rate limiting, stable `message_id`).
- Added Alembic migration:
  - `migrations/versions/0004_alerting_pipeline.py`.
  - Fixed revision id length (`0004_alerting_pipeline`) to remain compatible with Alembic/Postgres `alembic_version.version_num` width.
- Improved local Docker resilience on constrained networks:
  - `Dockerfile` now installs `uv` in-image with increased pip timeout/retry settings.
- Added deterministic tests for new behavior:
  - `tests/test_ingest_pipeline.py`
  - `tests/test_routing.py`
  - `tests/test_pubsub_service.py`
  - `tests/test_analytics_export.py`
  - `tests/test_replay.py`
- Updated docs/runbooks/tasks/changelog/version:
  - Task status updates in `docs/TASKS/*` + `docs/TASKS/README.md`
  - New runbooks: `docs/RUNBOOKS/REPLAY.md`, `docs/RUNBOOKS/PUBSUB.md`, `docs/RUNBOOKS/ANALYTICS_EXPORT.md`
  - Contract/design/deploy/readme updates for new lanes and audit endpoints.
  - Version bump to `0.5.0` in `pyproject.toml`, changelog entry in `CHANGELOG.md`.

## Why?

- Deliver the remaining planned roadmap items while preserving non-negotiables:
  - idempotent ingest,
  - secret-safe logging,
  - cost-min and optional-by-default GCP features,
  - edge/runtime efficiency with replay recoverability.
- Improve production readiness with auditable routing, drift visibility, and operational runbooks.

## How was it validated?

- Commands run:
  - `python scripts/harness.py doctor` (pass)
  - `UV_NO_SYNC=1 python scripts/harness.py all --strict` (pass)
  - `ruff check api/app agent tests` (pass)
  - `pyright` (pass)
  - `DATABASE_URL=sqlite+pysqlite:///:memory: pytest -q` (pass, 27 tests)
  - `pnpm install` (pass)
  - `pnpm -r --if-present typecheck && pnpm -r --if-present build` (pass)
  - `terraform -chdir=infra/gcp/cloud_run_demo fmt -check -recursive` (pass)
  - `python scripts/harness.py all --strict` (pass)
  - `timeout 300 make tf-check` (still timed out during `terraform init -upgrade` provider download in this environment)
  - `make db-up` + `uv run --locked alembic upgrade head` (pass after migration id fix)
  - `make EDGEWATCH_DEVICE_ID=demo-well-010 EDGEWATCH_DEVICE_TOKEN=dev-device-token-010 demo-device` (pass)
  - `timeout 45 make EDGEWATCH_DEVICE_ID=demo-well-010 EDGEWATCH_DEVICE_TOKEN=dev-device-token-010 SIMULATE_FLEET_SIZE=1 simulate` (ran bounded smoke; ingest confirmed via API logs with HTTP 200)
- Tests added/updated:
  - Added unit tests covering routing decisions, drift/quarantine prep, pubsub payload handling, analytics export cursor/client behavior, and replay range/cursor behavior.

## Risks / rollout notes

- DB migration `0004_alerting_pipeline` must be applied before deploying app changes.
- Pub/Sub and analytics lanes remain **off by default** and require explicit Terraform vars.
- Harness strict pass here used `UV_NO_SYNC=1` to avoid environment sync hangs; CI remains protected by explicit `uv sync --all-groups --locked` in workflow.
- `make tf-check` could not fully complete locally due Terraform provider download stall/timeouts; rerun in CI or a network-stable environment.

## Follow-ups

- [ ] Re-run `make tf-check` in CI/runner with stable Terraform registry/network access.
- [ ] Optional hardening: add integration tests around pubsub worker persistence path with DB fixture.
- [ ] Optional hardening: add end-to-end smoke script for analytics export job + admin export audit endpoint.
