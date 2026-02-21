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

## Follow-up Stabilization (2026-02-20)

### Additional changes

- Hardened Terraform local gates in `Makefile`:
  - `grant-cloudbuild-gcp` now uses `--condition=None` for non-interactive IAM binding.
  - `tf-policy` now evaluates only `*.tf` files (excludes `.terraform/*`) and pins `conftest --rego-version v0`.
- Fixed Terraform output compatibility:
  - `infra/gcp/cloud_run_demo/outputs.tf` now uses dashboard `.id` instead of unsupported `.name`.
- Fixed log sink IAM failure:
  - Removed invalid direct writer-member binding from `infra/gcp/cloud_run_demo/log_views.tf`.
- Improved startup resilience:
  - `api/app/main.py` skips demo bootstrap when schema is not yet ready (logs warning, no crash).
- Added SQLite migration portability for Cloud Run job/dev lanes:
  - Updated `migrations/versions/0001_initial.py`, `migrations/versions/0003_ingestion_batches.py`, `migrations/versions/0004_alerting_pipeline.py` to use dialect-aware JSON/defaults.
  - Added SQLite-safe guard for FK alter in `0003` (SQLite cannot alter constraints post-create).
  - Added regression test `tests/test_migrations_sqlite.py`.
- Updated docs to clarify deploy prerequisites:
  - `docs/DEPLOY_GCP.md`
  - `infra/gcp/cloud_run_demo/README.md`
  - Explicitly documents that `deploy-gcp-safe` needs shared DB (Cloud SQL/shared Postgres), not local SQLite file URLs.

### Validation run (follow-up)

- `python scripts/harness.py all --strict` ✅
- `make tf-check` ✅
- Local smoke equivalent ✅
  - `make db-up`
  - host API on `:8082`
  - `make demo-device` with unique id/token
  - bounded `make simulate` run
  - verified telemetry rows inserted for smoke device
- `make deploy-gcp-safe ENV=dev` ⚠️ partial
  - Cloud Build: success
  - Terraform apply: success
  - `migrate-gcp`: success (execution `edgewatch-migrate-dev-dgjxx`)
  - `verify-gcp-ready`: fails with `HTTP 503`, response `{"detail":"not ready: OperationalError"}`
  - Root cause: current `edgewatch-database-url` secret points to SQLite (`sqlite+pysqlite`), which is not a shared backend for Cloud Run service + migration job.

### Remaining operational follow-up

- [ ] Set `edgewatch-database-url` to a shared Postgres backend (Cloud SQL or equivalent), then rerun:
  - `make deploy-gcp-safe ENV=dev`

## Cloud SQL Terraform Wiring (2026-02-20)

### What changed

- Added a new reusable module:
  - `infra/gcp/modules/cloud_sql_postgres/`
  - provisions Cloud SQL Postgres instance + app database + app user
  - includes cost-min defaults and PostgreSQL log flags for tfsec compliance
- Wired Cloud SQL into Cloud Run service and jobs:
  - `infra/gcp/modules/cloud_run_service/main.tf`
  - `infra/gcp/modules/cloud_run_job/main.tf`
  - adds optional `/cloudsql` volume mount + `cloud_sql_instances` input
- Added Cloud SQL config surface in root module:
  - `infra/gcp/cloud_run_demo/variables.tf`
  - `infra/gcp/cloud_run_demo/main.tf`
  - `infra/gcp/cloud_run_demo/jobs.tf`
  - auto-manages `edgewatch-database-url` secret version when `enable_cloud_sql=true`
  - grants runtime SA `roles/cloudsql.client`
- Enabled SQL Admin API by default:
  - `infra/gcp/modules/core_services/variables.tf`
- Added Cloud SQL outputs:
  - `infra/gcp/cloud_run_demo/outputs.tf`
- Updated docs + profiles:
  - `docs/DEPLOY_GCP.md`
  - `infra/gcp/cloud_run_demo/README.md`
  - `infra/gcp/cloud_run_demo/profiles/README.md`
  - `infra/gcp/cloud_run_demo/profiles/dev_public_demo.tfvars`
  - `infra/gcp/cloud_run_demo/profiles/prod_private_iam.tfvars`
- Terraform check stability:
  - `Makefile` `tf-validate` now uses `terraform init -backend=false` (no `-upgrade`) to avoid network-flaky inner-loop stalls.

### Validation run

- `make tf-check` ✅
- `python scripts/harness.py all --strict` ✅
- `make deploy-gcp-safe ENV=dev` ✅
  - Cloud SQL instance created: `edgewatch-dev-pg`
  - migration execution: `edgewatch-migrate-dev-9mwq7` (success)
  - readiness: `OK: /readyz`

### Remaining follow-up

- [ ] For production, set an explicit strong DB password via `TF_VAR_cloudsql_user_password` instead of relying on the derived fallback.

## Task 11a — Agent Sensor Framework + Config (2026-02-21)

### What changed

- Added a pluggable sensor framework under `agent/sensors/`:
  - `agent/sensors/base.py` defines the backend protocol and a safe wrapper that prevents sensor exceptions from crashing the agent loop.
  - `agent/sensors/config.py` adds YAML/env config parsing + validation and backend construction.
  - `agent/sensors/backends/mock.py` wraps the existing mock behavior behind the new interface.
  - `agent/sensors/backends/composite.py` supports backend composition and per-child graceful fallback.
  - `agent/sensors/backends/placeholder.py` provides explicit `None`-emitting placeholders for `rpi_i2c`, `rpi_adc`, and `derived` until Tasks 11b/11c/11d land.
- Wired `agent/edgewatch_agent.py` to the framework:
  - reads `SENSOR_CONFIG_PATH` and optional `SENSOR_BACKEND` override
  - fails fast on invalid config with a clear startup error
  - uses backend reads in the telemetry loop
- Added sensor config example:
  - `agent/config/example.sensors.yaml`
- Updated docs:
  - `agent/README.md` sensors section
  - `agent/.env.example` sensor env vars
  - task status updates in `docs/TASKS/11a-agent-sensor-framework.md` and `docs/TASKS/README.md`
- Added deterministic tests:
  - `tests/test_sensor_framework.py`

### Why it changed

- Establishes the required foundation for real Raspberry Pi backends without coupling hardware-specific reads to buffering/ingest logic.
- Preserves local-first behavior (`mock` default) while introducing validated, portable configuration.

### How it was validated

- Baseline before task (required by process):
  - `make doctor-dev` (pass)
  - `make harness` (fails on pre-existing repo-wide issues unrelated to Task 11a; see risks)
- Task-focused validation:
  - `python scripts/harness.py lint --only python` (blocked by existing `uv.lock` drift when harness enforces `uv run --locked`)
  - `make test` (same `uv run --locked` lockfile block)
  - `ruff check agent/edgewatch_agent.py agent/sensors tests/test_sensor_framework.py` (pass)
  - `pyright agent/edgewatch_agent.py agent/sensors tests/test_sensor_framework.py` (pass)
  - `DATABASE_URL=sqlite+pysqlite:///:memory: pytest -q tests/test_sensor_framework.py` (pass)
  - `make harness` (rerun after changes; still blocked by existing unrelated failures)

### Risks / rollout notes

- `rpi_i2c`, `rpi_adc`, and `derived` are intentionally placeholders in this task and emit `None` metrics until their dedicated tasks land.
- Full-repo `make harness` is currently red due pre-existing unrelated failures in API and tooling paths; Task 11a changes are isolated to agent sensor framework scope.

### Follow-ups / tech debt

- [ ] Task 11b: replace `rpi_i2c` placeholder with real BME280 implementation.
- [ ] Task 11c: replace `rpi_adc` placeholder and use channel/scaling config in real conversions.
- [ ] Task 11d: replace `derived` placeholder with durable oil-life model + reset CLI.

## Task 11b — Raspberry Pi I2C (BME280 temp + humidity) (2026-02-21)

### What changed

- Added `rpi_i2c` backend implementation:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/backends/rpi_i2c.py`
  - lazy `smbus2` import (no import-time failure on laptops/CI)
  - BME280 calibration + compensation logic for:
    - `temperature_c`
    - `humidity_pct`
  - robust fallback behavior:
    - sensor read failures return `None` values
    - warning logs are rate-limited to avoid spam loops
- Wired backend selection:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/config.py`
  - `rpi_i2c` now constructs a real backend (not placeholder)
  - supports config fields:
    - `sensor` (currently `bme280`)
    - `bus`
    - `address` (int or hex string)
    - `warning_interval_s`
- Updated backend exports:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/backends/__init__.py`
- Added deterministic tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_sensor_rpi_i2c.py`
  - covers BME280 decoding, rounding, failure fallback, warning rate limiting, and config wiring
- Updated operator/dev docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/SENSORS.md` (wiring + setup + sanity checks)
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/README.md` (backend status + smbus2 install)
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example` (I2C backend env example)
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/config/example.sensors.yaml` (commented `rpi_i2c` config block)
- Updated task status docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/11b-rpi-i2c-temp-humidity.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`

### Why it changed

- Completes Task 11b by providing production-ready Pi I2C reads for temperature/humidity without breaking local-first developer lanes.
- Keeps dependency imports isolated so CI and non-Pi environments run without hardware libraries.

### How it was validated

- Required full-gate run:
  - `make harness` (fails on pre-existing repo-wide issues unrelated to this task, including existing API lint/type/test failures and repo hygiene `.DS_Store`)
- Task-focused validation:
  - `ruff check agent/sensors/backends/rpi_i2c.py agent/sensors/config.py tests/test_sensor_rpi_i2c.py tests/test_sensor_framework.py agent/sensors/backends/__init__.py` (pass)
  - `pyright agent/sensors/backends/rpi_i2c.py agent/sensors/config.py tests/test_sensor_rpi_i2c.py tests/test_sensor_framework.py agent/sensors/backends/__init__.py` (pass)
  - `DATABASE_URL=sqlite+pysqlite:///:memory: pytest -q tests/test_sensor_rpi_i2c.py tests/test_sensor_framework.py` (pass)

### Risks / rollout notes

- Runtime on Raspberry Pi still requires installing `smbus2` in the device environment.
- Backend currently targets BME280 only; additional I2C sensors remain future work.

### Follow-ups / tech debt

- [ ] Add an explicit optional dependency group for Pi sensor runtime packages (`smbus2`) once lockfile/tooling drift is resolved.
- [ ] Extend `rpi_i2c` to support additional sensor families (for example SHT31) behind the same backend contract.
