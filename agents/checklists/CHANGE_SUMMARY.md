# Change Summary

## Auto-deploy on main (2026-02-24)

### What changed

- Enabled automatic dev deploys on `main` pushes in:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/.github/workflows/deploy-gcp.yml`
- `Deploy to GCP (Cloud Run)` now triggers on:
  - `push` to `main`
  - `workflow_dispatch` (manual)
- Added env fallback logic so one workflow supports both trigger modes:
  - `github.event.inputs.env || 'dev'` used for:
    - workflow concurrency group
    - job environment
    - deploy step `ENV`

### Why it changed

- Users expected hosted dev to update when merges land on `main`.
- Previously deploy was manual-only (`workflow_dispatch`), so CI could pass while hosted dev remained on an older revision.

### Validation

- `python scripts/harness.py all --strict` ✅

## CSP-safe theme bootstrap (2026-02-24)

### What changed

- Replaced inline theme bootstrap script in:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/index.html`
- Added same-origin external bootstrap script:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/public/theme-init.js`

### Why it changed

- Hosted dev enforces CSP with `script-src 'self'`.
- Inline script execution was blocked in browser console.
- Moving theme init to an external script preserves strict CSP and removes the violation.

### Validation

- `python scripts/harness.py all --strict` ✅

## Dashboard map/device-create/admin polish (2026-02-23)

### What changed

- Map now plots all devices, not only those with telemetry coordinates:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/components/FleetMap.tsx`
  - devices without telemetry lat/lon now use deterministic fallback coordinates.
  - source label updated to `fallback location` (instead of demo-only wording).
- Fixed admin device creation when `display_name` is omitted:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/schemas.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/admin.py`
  - `AdminDeviceCreate.display_name` is optional; server falls back to `device_id`.
- Added regression test for omitted `display_name` create payload:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_admin_device_create.py`
- Removed dashboard environment pill/text (`env:dev`) from the header:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Dashboard.tsx`
- Admin UI now always sends a concrete `display_name` on create:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Admin.tsx`

### Why it changed

- Users expected offline/unknown/no-telemetry devices to still be visible on the fleet map.
- Creating a device without `display_name` produced HTTP 422 due required schema validation.
- Dashboard environment badge was requested to be removed.

### Validation

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (128 passed)

## Hosted dev device-list hardening (2026-02-23)

### What changed

- Added `safe_display_name(device_id, display_name)` in:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/device_identity.py`
- Updated device serialization paths to use fallback `display_name`:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/devices.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/admin.py`
- Added regression tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_device_identity.py`

### Why it changed

- Hosted dev returned HTTP 500 on `GET /api/v1/devices` because legacy rows had `display_name = NULL`.
- `DeviceOut.display_name` is a required string; direct serialization raised Pydantic validation errors.
- Fallback to `device_id` prevents endpoint-wide failure from a single malformed historical row.

### Validation

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (127 passed)

### Risks / rollout notes

- This is a defensive read-path fix; existing malformed rows are still present until explicitly backfilled.
- UI/API behavior remains stable; fallback display label is deterministic (`device_id`).

## CI IAM hardening + apply image guard (2026-02-23)

### What changed

- Tightened IAM for deploy CI service account `sa-edgewatch-ci@job-search-486101.iam.gserviceaccount.com`:
  - removed project-level `roles/storage.admin`
  - removed project-level `roles/viewer`
  - removed bucket-level `roles/storage.admin` from:
    - `gs://job-search-486101-tfstate`
    - `gs://job-search-486101_cloudbuild`
  - retained bucket-level `roles/storage.objectAdmin` on state/cloudbuild/config buckets for object read/write only.
- Hardened GCP workflows to avoid privileged fallbacks:
  - `/.github/workflows/terraform-apply-gcp.yml`
  - `/.github/workflows/deploy-gcp.yml`
  - `/.github/workflows/terraform-drift.yml`
  - `/.github/workflows/gcp-terraform-plan.yml`
  - all now require `GCP_TF_CONFIG_GCS_PATH` and always fetch `backend.hcl` + `terraform.tfvars` from GCS.
  - all workflow dispatch `tfvars` inputs were removed (strict GCS-only config source in CI).
  - all four workflows now share one cross-workflow concurrency group per env (`gcp-infra-<env>`) to serialize Terraform operations and avoid state-lock failures when users dispatch plan/apply/deploy together.
  - all now pass `TF_BACKEND_HCL=backend.hcl` so CI does not run tfstate bucket bootstrap requiring bucket-admin privileges.
- Prevented non-existent image usage in apply:
  - `terraform-apply-gcp` now accepts optional `image_tag` input.
  - if omitted, it resolves the latest existing Artifact Registry tag.
  - it verifies `IMAGE:TAG` exists before invoking `make apply-gcp`; fails fast with a clear error if not found.
- Cloud Build log-read permission workaround remains in `Makefile`:
  - `gcloud builds submit --suppress-logs --tag "$(IMAGE)" .`

### Why it changed

- The previous apply path could try to deploy an image tag that was never built in Artifact Registry.
- CI had temporary broad storage/viewer roles to get unstuck; those are now reduced while preserving deploy capability.
- Enforcing GCS-backed Terraform config keeps workflow behavior deterministic across envs and avoids bucket-admin operations during routine applies.
- Removing workflow `tfvars` inputs prevents accidental profile/path drift between local runs and CI deploy lanes.

### Validation

- IAM verification:
  - project roles for CI SA no longer include `roles/storage.admin` or `roles/viewer`.
  - tfstate/cloudbuild buckets now show only `roles/storage.objectAdmin` for CI SA.
- Harness:
  - `python scripts/harness.py lint` (fails on existing unrelated notification tests)
  - `python scripts/harness.py typecheck` (pass)
  - `python scripts/harness.py test` (fails on same 3 notification tests)
- Workflow YAML validation:
  - `pre-commit run check-yaml --files .github/workflows/terraform-apply-gcp.yml .github/workflows/deploy-gcp.yml .github/workflows/terraform-drift.yml .github/workflows/gcp-terraform-plan.yml` (pass)
- Reproduced/confirmed old remote workflow failure cause:
  - old `Terraform apply (GCP)` run failed in `bootstrap-state-gcp` due missing `storage.buckets.update` after IAM tightening.
  - local workflow fixes remove that fallback path by requiring `GCP_TF_CONFIG_GCS_PATH` + `TF_BACKEND_HCL`.

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

## Task 11c — Raspberry Pi ADC (ADS1115 pressures + levels) (2026-02-21)

### What changed

- Added pure scaling helpers for analog conversions:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/scaling.py`
  - includes linear mapping, clamp, current/voltage conversion, and reusable scaling config
- Added `rpi_adc` backend implementation:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/backends/rpi_adc.py`
  - ADS1115 single-ended channel reads over I2C
  - per-channel conversion modes:
    - `current_4_20ma` (with shunt resistor)
    - `voltage`
  - per-channel scale mapping (`from` -> `to`) with clamping
  - optional median smoothing via `median_samples`
  - graceful degradation: failed channels return `None` while other channels continue
  - warning logs are rate-limited to avoid spam
- Wired `rpi_adc` into backend construction:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/config.py`
  - supports config keys:
    - `adc.type`, `adc.bus`, `adc.address`, `adc.gain`, `adc.data_rate`, `adc.median_samples`, `adc.warning_interval_s`
    - `channels.<metric>.channel/kind/shunt_ohms/scale/median_samples`
  - added default canonical channel map when `channels` is omitted:
    - `water_pressure_psi`, `oil_pressure_psi`, `oil_level_pct`, `drip_oil_level_pct`
- Updated backend exports:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/backends/__init__.py`
- Added deterministic tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_sensor_scaling.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_sensor_rpi_adc.py`
  - updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_sensor_framework.py` for real `rpi_adc` backend behavior
- Updated operator/dev docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/SENSORS.md` (ADS1115 config and run commands)
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/README.md` (`rpi_adc` support note)
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example` (`SENSOR_BACKEND=rpi_adc` usage)
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/config/example.sensors.yaml` (full ADC channel mapping example)
- Updated task status docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/11c-rpi-adc-pressures-levels.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`

### Why it changed

- Completes Task 11c by delivering testable, configuration-driven ADS1115 ingestion for pressure/level metrics while keeping local non-Pi environments safe.
- Keeps conversion logic pure and unit-tested so scaling math can be verified without hardware.

### How it was validated

- Required full-gate run:
  - `make harness` (fails on pre-existing repo-wide issues unrelated to this task, including existing API lint/type/test failures and repo hygiene `.DS_Store`)
- Task-focused validation:
  - `ruff check agent/sensors/config.py agent/sensors/scaling.py agent/sensors/backends/rpi_adc.py tests/test_sensor_rpi_adc.py tests/test_sensor_scaling.py tests/test_sensor_framework.py agent/sensors/backends/__init__.py` (pass)
  - `pyright agent/sensors/config.py agent/sensors/scaling.py agent/sensors/backends/rpi_adc.py tests/test_sensor_rpi_adc.py tests/test_sensor_scaling.py tests/test_sensor_framework.py agent/sensors/backends/__init__.py` (pass)
  - `DATABASE_URL=sqlite+pysqlite:///:memory: pytest -q tests/test_sensor_scaling.py tests/test_sensor_rpi_adc.py tests/test_sensor_rpi_i2c.py tests/test_sensor_framework.py` (pass)

### Risks / rollout notes

- Runtime on Raspberry Pi requires `smbus2` to access ADS1115.
- The backend currently targets ADS1115 only; other ADC models remain future work.

### Follow-ups / tech debt

- [ ] Add a dedicated optional dependency group for hardware sensor packages once lockfile/tooling drift is resolved.
- [ ] Consider per-metric warning throttles if field deployments need finer-grained channel diagnostics.

## Task 11d — Derived Oil Life + Reset CLI (2026-02-21)

### What changed

- Added durable oil-life state primitives:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/derived/oil_life.py`
  - state fields:
    - `oil_life_runtime_s`
    - `oil_life_reset_at`
    - `oil_life_last_seen_running_at`
    - `is_running`
  - atomic persistence with temp file + fsync + rename
  - reset helper + running-state inference + linear oil-life function
- Added derived backend implementation:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/backends/derived.py`
  - computes `oil_life_pct` from durable runtime state
  - running detection order:
    - `pump_on` boolean when present
    - fallback to `oil_pressure_psi` hysteresis (`run_on_threshold`, `run_off_threshold`)
  - warning logs are rate-limited
- Enabled context-aware composition for derived metrics:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/backends/composite.py`
  - composite now passes accumulated upstream metrics to backends that implement `read_metrics_with_context(...)`
- Wired `derived` backend into config builder:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/config.py`
  - supports config keys:
    - `oil_life_max_run_hours`
    - `state_path`
    - `run_on_threshold`
    - `run_off_threshold`
    - `warning_interval_s`
- Added reset/show CLI tool:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/tools/oil_life.py`
  - runnable as:
    - `python -m agent.tools.oil_life reset --state ...`
    - `python -m agent.tools.oil_life show --state ...`
- Updated exports/docs/examples:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/backends/__init__.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/derived/__init__.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/config/example.sensors.yaml`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/SENSORS.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/11d-derived-oil-life-reset.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`
- Added deterministic tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_sensor_derived.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_oil_life_tool.py`
  - updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_sensor_framework.py`

### Why it changed

- Completes Task 11d by implementing a local-first, reboot-safe, manual-reset oil-life model aligned to ADR-20260220.
- Keeps derived logic composable with existing mock/I2C/ADC pipelines without changing route/service boundaries.

### How it was validated

- Required full-gate run:
  - `make harness` (fails on pre-existing repo-wide issues unrelated to this task, including existing API lint/type/test failures and repo hygiene `.DS_Store`)
- Task-focused validation:
  - `ruff check agent/sensors/backends/composite.py agent/sensors/backends/derived.py agent/sensors/derived/oil_life.py agent/sensors/config.py agent/tools/oil_life.py tests/test_sensor_derived.py tests/test_oil_life_tool.py tests/test_sensor_framework.py` (pass)
  - `pyright agent/sensors/backends/composite.py agent/sensors/backends/derived.py agent/sensors/derived/oil_life.py agent/sensors/config.py agent/tools/oil_life.py tests/test_sensor_derived.py tests/test_oil_life_tool.py tests/test_sensor_framework.py` (pass)
  - `DATABASE_URL=sqlite+pysqlite:///:memory: pytest -q tests/test_sensor_derived.py tests/test_oil_life_tool.py tests/test_sensor_scaling.py tests/test_sensor_rpi_adc.py tests/test_sensor_rpi_i2c.py tests/test_sensor_framework.py` (pass)

### Risks / rollout notes

- Oil-life state path must be writable by the agent process.
- Runtime accumulation between samples is interval-based; long sample intervals can smooth short run/stop cycles.

### Follow-ups / tech debt

- [ ] Consider emitting a local audit event when reset is invoked (for optional future upload).
- [ ] Evaluate whether oil-life runtime should be checkpointed less frequently for flash-wear-sensitive deployments.

## Task 12a — Agent Camera Capture + Ring Buffer (2026-02-21)

### What changed

- Added the new media subsystem under:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/media/storage.py`
    - filesystem ring buffer for captured assets
    - per-asset JSON sidecar metadata (`device_id`, `camera_id`, `captured_at`, `reason`, `sha256`, `bytes`, `mime_type`)
    - max-byte enforcement with FIFO eviction
    - atomic writes (`temp + fsync + rename`) for both media bytes and sidecars
    - orphan/temp-file cleanup during scans
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/media/capture.py`
    - capture backend interface
    - `libcamera-still` backend implementation for photo capture MVP
    - in-process capture lock for one-camera-at-a-time serialization
    - camera id parser (`cam1..camN`)
    - service that captures + persists into the ring buffer
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/media/runtime.py`
    - env-driven media config loader (`MEDIA_ENABLED`, `CAMERA_IDS`, intervals, ring settings)
    - scheduled snapshot runtime loop (round-robin across configured camera IDs)
    - graceful unsupported-platform handling when `libcamera-still` is missing
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/media/__init__.py`
- Wired media runtime into the agent loop:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/edgewatch_agent.py`
  - loads media runtime when enabled
  - executes scheduled captures in-loop
  - logs capture success/failure without crashing telemetry path
- Added a manual capture CLI:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/tools/camera.py`
- Updated operator/developer docs and env examples:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/CAMERA.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/12a-agent-camera-capture-ring-buffer.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`
- Added deterministic tests for media behavior:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_media_ring_buffer.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_media_runtime.py`

### Why it changed

- Completes Task 12a by shipping the device-side camera lane foundation:
  - snapshot capture
  - serialized camera access
  - durable local media ring buffer with bounded disk usage
  - stable module interfaces for upcoming 12b/12c integration

### How it was validated

- Required full-gate run:
  - `make harness` (fails on pre-existing repo-wide issues unrelated to Task 12a, including repo hygiene `.DS_Store` and existing API lint/type/test failures)
- Task-specific validation:
  - `ruff format agent/edgewatch_agent.py agent/media agent/tools/camera.py tests/test_media_ring_buffer.py tests/test_media_runtime.py` (pass)
  - `ruff check agent/edgewatch_agent.py agent/media agent/tools/camera.py tests/test_media_ring_buffer.py tests/test_media_runtime.py` (pass)
  - `pyright agent/edgewatch_agent.py agent/media agent/tools/camera.py tests/test_media_ring_buffer.py tests/test_media_runtime.py` (pass)
  - `DATABASE_URL=sqlite+pysqlite:///:memory: pytest -q tests/test_media_ring_buffer.py tests/test_media_runtime.py` (pass)
- Spec validation command status:
  - `make fmt` (fails due existing repo-wide pre-commit/hygiene issues outside Task 12a scope; unrelated file edits were reverted before commit)

### Risks / rollout notes

- Media capture currently depends on `libcamera-still`; when missing, media setup is disabled with a clear log message while telemetry continues.
- Scheduled capture currently uses `reason=scheduled` only in-agent; alert-transition/manual trigger plumbing is intentionally deferred to later tasks.
- Ring buffer eviction is byte-bound and FIFO by `captured_at`; operators should size `MEDIA_RING_MAX_BYTES` to keep the desired local retention window.

### Follow-ups / tech debt

- [ ] Task 12b: wire this media lane into API metadata + upload flow.
- [ ] Add integration tests that exercise end-to-end capture on Raspberry Pi hardware in CI-adjacent smoke lanes.

## Task 12b — API Media Metadata + Storage (2026-02-21)

### What changed

- Added media persistence model + migration:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/models.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/migrations/versions/0007_media_objects.py`
  - new `media_objects` table with idempotency key `(device_id, message_id, camera_id)`, metadata fields, storage pointers, and upload timestamp.
- Added media storage config surface:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/config.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/.env.example`
  - supports `MEDIA_STORAGE_BACKEND=local|gcs`, local root path, GCS bucket/prefix, and max upload bytes.
- Added media service layer (business logic kept out of routes):
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/media.py`
  - deterministic object pathing (`<device>/<camera>/<YYYY-MM-DD>/<message>.<ext>`)
  - idempotent metadata create/get with conflict detection
  - payload integrity checks (declared bytes, SHA-256, content type)
  - local filesystem store and GCS store adapters.
- Added API route surface:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/media.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/main.py`
  - endpoints:
    - `POST /api/v1/media`
    - `PUT /api/v1/media/{media_id}/upload`
    - `GET /api/v1/devices/{device_id}/media`
    - `GET /api/v1/media/{media_id}`
    - `GET /api/v1/media/{media_id}/download`
  - device-auth scoped; device cannot access other device media.
- Added schemas/tests/docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/schemas.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_media_service.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_models.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_migrations_sqlite.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CONTRACTS.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/CAMERA.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docker-compose.yml` now mounts `/app/data/media` via `edgewatch_media` volume.
- Added runtime dependency for cloud storage:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/pyproject.toml`
  - lock refresh in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/uv.lock`.
- Updated task tracking:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/12b-api-media-metadata-storage.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`

### Why it changed

- Completes Task 12b by shipping the API-side media lane needed for camera capture workflows:
  - durable metadata,
  - idempotent create semantics,
  - configurable local/GCS storage backends,
  - authenticated listing and retrieval for downstream UI work (Task 12c).

### How it was validated

- Required full-gate run:
  - `make harness` (fails on existing repo-wide baseline issues unrelated to Task 12b; also auto-edits unrelated files, which were reverted before commit)
- Task-focused validation:
  - `ruff format api/app/config.py api/app/main.py api/app/models.py api/app/schemas.py api/app/routes/media.py api/app/services/media.py tests/test_media_service.py tests/test_models.py tests/test_migrations_sqlite.py migrations/versions/0007_media_objects.py` (pass)
  - `ruff check api/app/routes/media.py api/app/services/media.py api/app/models.py api/app/schemas.py tests/test_media_service.py tests/test_models.py tests/test_migrations_sqlite.py migrations/versions/0007_media_objects.py` (pass)
  - `pyright api/app/routes/media.py api/app/services/media.py api/app/models.py api/app/schemas.py tests/test_media_service.py tests/test_models.py tests/test_migrations_sqlite.py migrations/versions/0007_media_objects.py` (pass)
  - `DATABASE_URL=sqlite+pysqlite:///:memory: pytest -q tests/test_media_service.py tests/test_models.py tests/test_migrations_sqlite.py` (pass)
  - `uv sync --all-groups --locked` (pass after lock refresh)

### Risks / rollout notes

- `make harness` currently remains red on pre-existing repo-wide failures outside this task scope (including existing API/infra files not modified by 12b).
- For Cloud Run deployments with `MEDIA_STORAGE_BACKEND=gcs`, runtime identity must have bucket write/read permissions for the configured `MEDIA_GCS_BUCKET`.
- Current download behavior proxies bytes through the API; signed URL optimization can be layered later if needed.

### Follow-ups / tech debt

- [ ] Task 12c: implement dashboard media gallery against the new `/api/v1/media` endpoints.
- [ ] Add route-level integration tests for media endpoints (auth matrix + response envelopes) once baseline main-route test lane is stabilized.

## Task 12b — CI Harness Stabilization Follow-up (2026-02-21)

### What changed

- Fixed repo-wide Python issues that blocked `harness` in CI:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/main.py`
    - added missing `os` import used for OTEL service name
    - tightened exception payload typing to satisfy pyright
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/devices.py`
    - fixed `status` unbound bug by avoiding local variable shadowing
    - corrected metric filtering typing issues
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/middleware/limits.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/rate_limit.py`
    - moved module docstrings ahead of imports to satisfy `ruff` E402
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/scripts/package_dist.py`
    - removed import-order violation by loading `api/app/version.py` via `importlib` instead of path mutation + late import
- Fixed CI environment gap for Terraform hook:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/.github/workflows/ci.yml`
  - added `hashicorp/setup-terraform@v3` (`1.14.5`) before running `python scripts/harness.py all --strict`
- Fixed Terraform hygiene Docker fallback pathing:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/Makefile`
  - `tf-lint` now mounts `infra/gcp` (parent) and runs in `cloud_run_demo` so `../modules/*` resolves correctly when `tflint` is run via Docker in CI.
  - Docker fallback now runs `tflint --init && tflint` in a single container invocation so plugin initialization is available to the lint step.
- Fixed Node typecheck blockers reached once Python/Terraform gates were green:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx` (severity type narrowing)
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Dashboard.tsx` (missing `fmtAlertType` import)
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/package.json` + `/Users/ryneschroder/Developer/git/edgewatch-telemetry/pnpm-lock.yaml` (added `lucide-react`)
- Included repository-wide formatting drift fixes produced by pre-commit/terraform fmt (docs, infra tf/tfvars, and Python formatting-only files) so CI no longer auto-modifies files and fails.

### Why it changed

- Task 12b PR could not merge because required `harness` check was red from baseline repository issues unrelated to the media feature itself.
- This follow-up makes the PR mergeable and restores deterministic CI behavior for the repo gate.

### How it was validated

- `uv run --locked pre-commit run --all-files` ✅
- `make tf-lint` ✅
- `pnpm -r --if-present typecheck` ✅
- `make harness` ✅
  - includes:
    - pre-commit hooks
    - `ruff` format/check
    - `pyright`
    - `pytest` (77 passed)
    - `terraform fmt` under `infra/gcp`
    - web build/type lanes

### Risks / rollout notes

- This follow-up includes broad formatting-only churn in infra/docs files due existing drift; no functional Terraform behavior changes were introduced by `terraform fmt`.
- CI now depends on an explicit Terraform install step in the harness workflow, aligned with the other Terraform workflows in this repo.

### Follow-ups / tech debt

- [ ] Consider splitting harness into language/tool lanes if future failures in one ecosystem should not block unrelated task PRs.
- [ ] Consider pin-refresh for `pre-commit` hooks (`pre-commit-hooks` deprecation warning about legacy stages) in a dedicated maintenance PR.

## Task 12c — Web Media Gallery (2026-02-21)

### What changed

- Added media API client surface for the web app:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts`
  - new `MediaObjectOut` type
  - new media helpers:
    - `api.media.list(deviceId, { token, limit })`
    - `api.media.downloadPath(mediaId)`
    - `api.media.downloadBlob(mediaId, token)`
  - download requests use `cache: 'no-store'` to avoid stale signed/proxied URL behavior.
- Implemented a production-ready **Media** tab in device detail:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/DeviceDetail.tsx`
  - replaced the old camera placeholder tab with:
    - per-device media token input (device-auth scoped API compatibility)
    - camera filter (`all`, `cam1..cam4`, plus discovered camera IDs)
    - latest-by-camera cards (`cam1..cam4`)
    - media grid with preview thumbnails
    - full-resolution open modal
    - “Copy link” action for operator sharing
    - skeleton loading states and error toasts
    - empty-state messaging when token/media is absent
- Updated web docs and task tracking:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/WEB_UI.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/12c-web-media-gallery.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`

### Why it changed

- Completes Task 12c by connecting the shipped 12b media API to the operator UI with practical gallery workflows:
  - latest capture visibility by camera,
  - full-res asset inspection,
  - operator-friendly filtering and sharing actions.

### How it was validated

- Task-specific validation from the spec:
  - `pnpm -r --if-present build` ✅
  - `pnpm -C web typecheck` ✅
  - `make test` ✅
- Required repo gate:
  - `make harness` ✅

### Risks / rollout notes

- Media endpoints currently require device bearer tokens; the UI stores per-device token locally in the browser for operator convenience.
- Thumbnail rendering currently uses downloaded blobs from the full media endpoint (no dedicated thumbnail service yet), so very large image sets can increase client bandwidth usage.

### Follow-ups / tech debt

- [ ] Add server-generated thumbnail derivatives for lower-bandwidth gallery rendering.
- [ ] Add IAM/IAP-aware operator media access path to avoid browser-side device token handling in hardened production deployments.

## Task 13a — Cellular Runbook (LTE modem + SIM bring-up) (2026-02-21)

### What changed

- Rewrote and expanded the cellular runbook into a field-ready technician procedure:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/CELLULAR.md`
  - includes:
    - hardware option guidance (LTE HAT vs USB modem vs external router)
    - fresh Pi prerequisites (`ModemManager`, `NetworkManager`, tooling)
    - SIM/APN bring-up with concrete `mmcli`/`nmcli` commands
    - registration/signal/DNS/egress verification commands
    - EdgeWatch validation checks after link bring-up
    - common failure playbook with command sets and expected healthy/failure outputs
    - a field “before leaving site” checklist
    - escalation diagnostics bundle to collect for support.
- Updated hardware recommendations for LTE selection guidance:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/HARDWARE.md`
  - clarified LTE deployment options and when to choose each.
- Updated task status tracking:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/13a-cellular-runbook.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`

### Why it changed

- Completes Task 13a by delivering a documentation-first, operator-executable LTE bring-up runbook with concrete diagnostics for real field failures.

### How it was validated

- `uv run --locked pre-commit run --all-files` ✅
- `make harness` ✅

### Risks / rollout notes

- Commands in the runbook are intentionally carrier-agnostic; exact APN names and SIM provisioning rules remain carrier-specific.
- Modem output fields can vary slightly across modem firmware versions; the runbook focuses on state/registration semantics that remain consistent.

### Follow-ups / tech debt

- [ ] Task 13c: enforce policy-driven cellular cost caps for media + telemetry. (completed in next section)

## Task 13b — Agent Cellular Metrics + Link Watchdog (2026-02-21)

### What changed

- Added a new agent cellular observability module:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/cellular.py`
  - includes:
    - optional env-driven enablement (`CELLULAR_METRICS_ENABLED=true`)
    - best-effort ModemManager (`mmcli`) metric collection
    - parsed metrics:
      - `signal_rssi_dbm`
      - `cellular_rsrp_dbm`
      - `cellular_rsrq_db`
      - `cellular_sinr_db`
      - `cellular_registration_state`
    - lightweight connectivity watchdog (DNS + HTTP HEAD/GET fallback):
      - `link_ok`
      - `link_last_ok_at`
    - best-effort daily byte counters from Linux interface statistics:
      - `cellular_bytes_sent_today`
      - `cellular_bytes_received_today`
- Wired cellular monitor into the main edge loop:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/edgewatch_agent.py`
  - startup now validates cellular env config and reports `cellular=enabled|disabled`.
  - collected cellular metrics are merged into telemetry payloads when enabled.
- Added deterministic tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_agent_cellular.py`
  - covers:
    - env parsing/validation
    - modem/watchdog parsing
    - daily usage counter behavior
    - non-Pi/mmcli-missing safety
- Updated contracts/docs/runbooks:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/contracts/telemetry/v1.yaml`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DOMAIN.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/CELLULAR.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/HARDWARE.md`
- Updated task tracking:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/13b-agent-cellular-metrics-watchdog.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/13-cellular-connectivity.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`

### Why it changed

- Completes Task 13b by adding field-focused cellular link observability while keeping local development and CI environments runnable without modem tooling.

### How it was validated

- `make harness` ✅
- Focused test lane:
  - `DATABASE_URL=sqlite+pysqlite:///:memory: pytest -q tests/test_agent_cellular.py` ✅

### Risks / rollout notes

- Cellular metrics are best-effort and depend on modem/driver output shape; unavailable fields are omitted.
- Daily byte counters currently reset on agent restart (acceptable for best-effort telemetry; Task 13c introduces policy-enforced counters/audit).

### Follow-ups / tech debt

- [ ] Validate full end-to-end media upload counters once device-side upload lane is implemented.

## Task 13c — Cost Caps in Edge Policy (2026-02-21)

### What changed

- Extended edge policy contract with `cost_caps`:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/contracts/edge_policy/v1.yaml`
  - new fields:
    - `max_bytes_per_day`
    - `max_snapshots_per_day`
    - `max_media_uploads_per_day`
- Wired `cost_caps` through API policy loaders and response schemas:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/edge_policy.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/schemas.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/device_policy.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/contracts.py`
- Extended agent policy parsing/cache with cost caps:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/device_policy.py`
- Added durable cost-cap counter module:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/cost_caps.py`
  - persists UTC-day counters across restart:
    - bytes sent
    - snapshots captured
    - media upload units
- Integrated enforcement into agent runtime:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/edgewatch_agent.py`
  - behavior:
    - heartbeat-only telemetry mode once `max_bytes_per_day` is reached
    - skip scheduled media capture when snapshot/upload caps are reached
    - telemetry/log audit metrics:
      - `cost_cap_active`
      - `bytes_sent_today`
      - `media_uploads_today`
      - `snapshots_today`
  - fallback policy now includes cost-cap env defaults when policy fetch is unavailable.
- Added deterministic tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_agent_cost_caps.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_agent_device_policy.py`
  - updated `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_device_policy.py`
- Updated telemetry contract discoverability/docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/contracts/telemetry/v1.yaml`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DOMAIN.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CONTRACTS.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/COST_HYGIENE.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/CELLULAR.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/README.md`
- Updated task status tracking:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/13c-cost-caps-policy.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/13-cellular-connectivity.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`

### Why it changed

- Completes Task 13c by making cellular consumption predictable via policy-driven, durable daily caps with explicit audit visibility.

### How it was validated

- `make harness` ✅
- Focused test lanes:
  - `DATABASE_URL=sqlite+pysqlite:///:memory: uv run --locked pytest -q tests/test_agent_cost_caps.py tests/test_agent_device_policy.py tests/test_device_policy.py` ✅

### Risks / rollout notes

- Current media pipeline captures locally (Task 12a); to stay conservative, each scheduled capture currently increments the media upload unit counter.
- Byte counters are agent-accounted payload estimates (telemetry JSON body size), not carrier-billed octets.

### Follow-ups / tech debt

- [ ] When device-side media upload lane is enabled, wire upload-complete callbacks to increment media upload counters on actual upload success.

## Task 14 (Iteration) — Devices List UX Polish (2026-02-21)

### What changed

- Polished Devices page quick filtering and status clarity:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Devices.tsx`
  - added quick filter toggle for `open alerts only` (in addition to online/offline/unknown status filters)
  - added per-device health explanation labels/details for:
    - offline (stale telemetry threshold context)
    - stale heartbeat
    - weak signal
    - low battery
    - open alerts
    - awaiting telemetry / healthy
  - added open-alert indicators in the table status column and fleet summary counts
  - improved empty-state guidance with actionable next steps and clear-filter affordance.
- Updated web API contract typing to include edge-policy cost caps:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts`
- Updated UI/task docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/WEB_UI.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/14-ui-ux-polish.md`

### Why it changed

- Advances Task 14’s remaining Devices-list goals: clearer status explanations, better empty states, and operator-friendly quick filters including open-alert focus.

### How it was validated

- `pnpm -C web typecheck` ✅
- `pnpm -r --if-present build` ✅
- `make harness` ✅

### Risks / rollout notes

- The open-alert device filter currently derives from `GET /api/v1/alerts?open_only=true&limit=1000`; extremely large fleets may need a dedicated aggregate endpoint in a future iteration.

### Follow-ups / tech debt

- [ ] Complete remaining Task 14 work for IAP operator posture UX after Task 18 lands.

## Task 18 — IAP identity perimeter (2026-02-21)

### What changed

- Added app-level IAP defense-in-depth and admin attribution:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/config.py`
    - new `IAP_AUTH_ENABLED` setting
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/security.py`
    - `require_admin` now accepts `X-Goog-Authenticated-User-Email`
    - when `IAP_AUTH_ENABLED=true`, admin requests without an IAP identity header return `401`
    - returns normalized acting principal for audit attribution
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/admin.py`
    - device create/update mutations now persist admin audit events with acting principal + request id
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/admin_audit.py`
    - centralized admin audit persistence + structured `admin_event` logs
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/models.py`
    - added `admin_events` model/table mapping
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/migrations/versions/0008_admin_events.py`
    - Alembic migration for `admin_events`
- Added Terraform IAP perimeter support for split dashboard/admin Cloud Run services:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/iap.tf`
    - serverless NEGs + HTTPS LB resources + IAP backend config + allowlist IAM bindings
    - Cloud Run invoker binding for IAP service account
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/variables.tf`
    - new `enable_{dashboard,admin}_iap` controls
    - domain, OAuth client, and allowlist variables + validation guardrails
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/main.tf`
    - stable service-name locals
    - admin service sets `IAP_AUTH_ENABLED=true` when admin IAP is enabled
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/iam_bindings.tf`
    - avoids direct group `run.invoker` grants on services when IAP is enabled
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/outputs.tf`
    - new `dashboard_iap_url` and `admin_iap_url` outputs
  - profile examples updated with commented IAP variable blocks.
- Updated docs and task tracking:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DEPLOY_GCP.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/security.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/PRODUCTION_POSTURE.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/18-iap-identity-perimeter.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CODEX_HANDOFF.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CONTRACTS.md`

### Why it changed

- Completes Task 18 acceptance criteria:
  - supports Google-login IAP perimeter for dashboard/admin services
  - supports principal/group allowlists
  - records acting principal on admin mutations with structured auditability
  - adds app-level checks so admin routes fail closed when IAP identity headers are absent

### How it was validated

- Focused validation:
  - `uv run --locked ruff check api/app/config.py api/app/security.py api/app/main.py api/app/models.py api/app/routes/admin.py api/app/services/admin_audit.py tests/test_security.py tests/test_migrations_sqlite.py tests/test_admin_audit.py migrations/versions/0008_admin_events.py` ✅
  - `DATABASE_URL=sqlite+pysqlite:///:memory: uv run --locked pytest -q tests/test_security.py tests/test_migrations_sqlite.py tests/test_admin_audit.py` ✅
  - `terraform -chdir=infra/gcp/cloud_run_demo fmt -recursive` ✅
- Full-repo validation:
  - `make harness` (see PR notes for result)
  - `make tf-fmt`
  - `make tf-validate`

### Risks / rollout notes

- IAP requires DNS and a valid OAuth client for each enabled service before users can log in successfully.
- Enabling IAP while leaving direct Cloud Run invoker grants in place can bypass the IAP layer; this change avoids that for dashboard/admin service group bindings.
- `IAP_AUTH_ENABLED` currently guards admin endpoints; dashboard/read endpoints remain perimeter-only (IAP + IAM) without additional app header enforcement, which is expected for Task 18.

### Follow-ups / tech debt

- [ ] Task 15: expand admin attribution from `actor_email` to richer RBAC subject/role model and surface audit events in UI.

## Task 15 — AuthN/AuthZ hardening (2026-02-21)

### What changed

- Added in-app auth/authz modules under `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/auth/`:
  - `principal.py`: principal extraction from IAP headers, admin-key mode, and local dev principal mode
  - `rbac.py`: role enforcement helpers (`viewer`, `operator`, `admin`)
  - `audit.py`: normalized audit actor attribution helper
- Added RBAC settings and defaults:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/config.py`
  - new env vars: `AUTHZ_ENABLED`, `AUTHZ_IAP_DEFAULT_ROLE`, role allowlists, and local dev principal controls
- Enforced route-level ACLs:
  - read routes now require `viewer` when RBAC is enabled (mounted via dependency in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/main.py`)
  - admin routes now require `admin` role (`/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/admin.py`)
- Extended admin audit attribution:
  - added `actor_subject` on `admin_events` model and migration
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/models.py`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/migrations/versions/0009_admin_events_actor_subject.py`
  - updated admin audit persistence to include `actor_subject`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/admin_audit.py`
- Added admin mutation audit visibility in UI:
  - new `GET /api/v1/admin/events` endpoint
  - new Admin UI Events tab showing actor email/subject/action/target/request id/details
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Admin.tsx`
- Hardened browser secret handling in production posture:
  - admin-key localStorage persistence is now limited to localhost/dev usage
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/app/settings.tsx`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
- Updated docs and task status:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/security.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DEPLOY_GCP.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CONTRACTS.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/WEB_UI.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/15-authn-authz.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CODEX_HANDOFF.md`

### Why it changed

- Completes Task 15 acceptance:
  - admin actions are blocked without `admin` role (when RBAC is enabled)
  - acting principal attribution includes `actor_email` and optional `actor_subject`
  - attribution is visible in the admin audit UI
  - production posture avoids persisting admin secrets to browser localStorage
- Preserves local-first/dev convenience:
  - default dev key path still works
  - local dev principal mode supports RBAC testing without external identity infrastructure

### How it was validated

- `make fmt` ✅
- `make lint` ✅
- `make typecheck` ✅
- `make test` ✅
- `make harness` ✅
- Targeted checks during implementation:
  - `uv run --locked ruff check ...` ✅
  - `uv run --locked pyright` ✅
  - `DATABASE_URL=sqlite+pysqlite:///:memory: uv run --locked pytest -q tests/test_authz.py tests/test_security.py tests/test_admin_audit.py tests/test_migrations_sqlite.py` ✅

### Risks / rollout notes

- RBAC defaults:
  - `AUTHZ_ENABLED` defaults to `false` in `dev`, `true` in `stage/prod`.
  - In non-dev environments, ensure identity headers and role allowlists are configured before enabling broad operator access.
- Admin key mode remains supported for local/dev; production should prefer perimeter identity (`ADMIN_AUTH_MODE=none` + IAP/IAM).
- New migration `0009_admin_events_actor_subject` must be applied before deploying code that reads/writes `actor_subject`.

### Follow-ups / tech debt

- [ ] Expand RBAC usage to additional mutation surfaces as they are introduced (policy overrides/destructive endpoints).

## Task 16 — OpenTelemetry SQLAlchemy + Metrics (2026-02-21)

### What changed

- Expanded OTEL wiring with SQLAlchemy instrumentation and metric export:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/observability.py`
  - added SQLAlchemy span instrumentation (`opentelemetry-instrumentation-sqlalchemy`)
  - added request correlation attributes on HTTP + DB spans (`edgewatch.request_id`)
  - added OTEL metrics instruments for:
    - HTTP request count/latency by endpoint
    - ingest points accepted/rejected
    - alert open/close transitions
    - monitor loop duration
- Wired monitor loop metric emission:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/main.py`
- Wired ingest accepted/rejected point metrics:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/ingest.py`
- Wired alert lifecycle transition metrics:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/monitor.py`
- Added OTEL dependency for SQLAlchemy instrumentation:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/pyproject.toml`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/uv.lock`
- Updated observability/task docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/OBSERVABILITY.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/OBSERVABILITY_OTEL.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/16-opentelemetry.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`

### Why it changed

- Completes Task 16 so OTEL-enabled deployments include both request and DB spans plus actionable service-level metrics for incident triage.

### How it was validated

- `make harness` ✅

### Risks / rollout notes

- OTEL remains opt-in (`ENABLE_OTEL=1`); when disabled, metric and instrumentation paths are no-ops.
- In non-dev environments, metrics/traces require OTLP endpoint configuration (`OTEL_EXPORTER_OTLP_*`) to leave the process.

### Follow-ups / tech debt

- [ ] Consider adding explicit OTEL collector Terraform module/task for a turnkey Cloud Run deployment path.

## Task 14 (Iteration) — Alerts Timeline + Routing Audit (2026-02-21)

### What changed

- Upgraded the Alerts page to include timeline grouping and expanded filtering:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx`
  - added filters for:
    - device id
    - alert type
    - severity
    - open/resolved
  - added timeline grouping by day with per-severity counts and recent-row previews.
- Added routing decision audit visibility on Alerts:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx`
  - consumes admin notifications when admin routes/auth are available
  - shows dedupe/throttle/quiet-hours decision badges and reasons per alert
  - added a routing audit summary card with decision counts for currently shown alerts.
- Updated docs/task tracking:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/14-ui-ux-polish.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/WEB_UI.md`

### Why it changed

- Completes the remaining Alerts slice in Task 14 so operators can quickly scan incident windows and verify notification routing behavior without leaving the dashboard.

### How it was validated

- `pnpm -C web typecheck` ✅
- `pnpm -r --if-present build` ✅
- `make harness` ✅

### Risks / rollout notes

- Routing audit visibility depends on admin notification endpoints; when admin routes are disabled (or key auth is required but not configured), the UI intentionally degrades to explanatory empty states.
- Alerts timeline is built from loaded pages in the current client view; broad historical analysis still requires loading additional pages.

### Follow-ups / tech debt

- [ ] Complete remaining Task 14 work for IAP operator posture UX after Task 18 lands.

## Task 14 (Iteration) — Device Detail Oil-Life Gauge (2026-02-21)

### What changed

- Added a dedicated oil-life service gauge to the Device Detail Overview:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/DeviceDetail.tsx`
  - added a radial gauge component driven by latest `oil_life_pct`
  - added explicit health bands and service guidance:
    - `Healthy` (50%+)
    - `Watch` (20% to 49%)
    - `Service now` (below 20%)
  - handles missing-contract and missing-telemetry states with clear operator messaging.
- Updated docs/task tracking:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/14-ui-ux-polish.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/WEB_UI.md`

### Why it changed

- Completes the remaining non-IAP Device Detail item in Task 14 so operators can quickly assess maintenance urgency from oil life without opening raw telemetry.

### How it was validated

- `pnpm -C web typecheck` ✅
- `pnpm -r --if-present build` ✅
- `make harness` ✅

### Risks / rollout notes

- Gauge availability depends on `oil_life_pct` being present in both the active telemetry contract and recent telemetry payloads.
- Threshold bands are UI-side operator guidance; they are not yet policy-driven from server-side config.

### Follow-ups / tech debt

- [ ] Complete remaining Task 14 work for IAP operator posture UX after Task 18 lands.

## Task 17 — Telemetry Partitioning + Rollups (2026-02-21)

### What changed

- Added Postgres scale-path migration:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/migrations/versions/0010_telemetry_partition_rollups.py`
  - creates `telemetry_ingest_dedupe` and `telemetry_rollups_hourly`
  - converts Postgres `telemetry_points` to monthly range partitions on `ts`
  - keeps non-Postgres lanes portable (no partition conversion on SQLite)
- Updated ingest runtime to preserve idempotency independent of partitioned-table unique constraints:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/ingestion_runtime.py`
  - reserves `(device_id, message_id)` in `telemetry_ingest_dedupe` before inserting telemetry rows
- Added partition/rollup services + scheduled job:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/telemetry_partitions.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/telemetry_rollups.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/jobs/partition_manager.py`
- Enhanced retention to drop old partitions first (when enabled) and prune dedupe/rollup tables:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/jobs/retention.py`
- Added optional rollup-backed reads for hourly timeseries:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/devices.py`
- Terraform + ops wiring for partition manager Cloud Run Job + Scheduler:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/jobs.tf`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/variables.tf`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles/dev_public_demo.tfvars`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles/stage_private_iam.tfvars`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles/prod_private_iam.tfvars`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/Makefile` (`partition-manager-gcp`)
- Added/updated tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_ingestion_runtime.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_telemetry_scale_services.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_migrations_sqlite.py`
- Updated task/docs/changelog/version:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/17-telemetry-partitioning-rollups.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CODEX_HANDOFF.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/RETENTION.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DEPLOY_GCP.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/PRODUCTION_POSTURE.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/CHANGELOG.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/pyproject.toml`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/version.py`

### Why it changed

- Task 17 requires a production-ready Postgres scale path: partitioned telemetry storage, scheduled partition management, retention via partition drops, and optional hourly rollups for long-range chart workloads.
- Postgres partitioned tables cannot directly preserve the prior `(device_id, message_id)` unique enforcement pattern, so ingest idempotency was moved to a dedicated dedupe table while preserving the same external contract.

### How it was validated

- `make fmt` ✅
- `make harness` ✅
- `make db-up` ✅
- `make db-migrate` ✅
- `make tf-check` ✅ (with existing soft-fail checkov findings in baseline posture)

### Risks / rollout notes

- **Migration ordering is mandatory**: deploys must run Alembic `0010_telemetry_partition_rollups` before app code that depends on new tables/jobs.
- Rollup reads are only used when `TELEMETRY_ROLLUPS_ENABLED=true` and bucket is hourly; otherwise the API remains on raw telemetry aggregation.
- `make tf-check` still reports known policy findings in this repo’s current baseline (soft-fail enabled); no new hard failures were introduced by Task 17 wiring.

### Follow-ups / tech debt

- [ ] Add a Postgres migration integration test lane that asserts partitioned table plans directly (for example, `EXPLAIN` partition pruning checks in CI).

## Task 19 — Agent Buffer Hardening (2026-02-21)

### What changed

- Hardened SQLite buffering in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/buffer.py`:
  - configurable WAL pragmas (`journal_mode`, `synchronous`, `temp_store`)
  - DB byte quota enforcement (`max_db_bytes`) with oldest-first eviction
  - disk-full graceful handling (evict + retry, or drop with audit log)
  - corruption recovery (move malformed DB/WAL/SHM aside, recreate schema)
  - buffer metrics API:
    - `buffer_db_bytes`
    - `buffer_queue_depth`
    - `buffer_evictions_total`
- Wired env-driven buffer config + audit metrics into runtime loops:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/edgewatch_agent.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/simulator.py`
- Added operator-facing config + runbook docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/OFFLINE_CHECKS.md`
- Added deterministic tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_agent_buffer.py`
- Updated task queue status docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/19-agent-buffer-hardening.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CODEX_HANDOFF.md`

### Why it changed

- Task 19 requires field-resilient buffering behavior under power loss, intermittent links, and constrained disk on edge nodes.
- The hardened buffer preserves local-first operation while making data loss events explicit and observable for operators.

### How it was validated

- `make fmt` ✅
- `make lint` ✅
- `make typecheck` ✅
- `make test` ✅
- `make harness` ✅

### Risks / rollout notes

- If `BUFFER_MAX_DB_BYTES` is configured below SQLite’s practical file floor for a device, the buffer now clamps the quota upward and logs a warning to avoid permanent eviction thrash.
- Evictions are intentional oldest-first data loss events; operators should monitor `buffer_evictions_total` and adjust disk quotas per node profile.

### Follow-ups / tech debt

- [ ] Consider exporting buffer metrics as dedicated local health endpoints in addition to telemetry payload embedding.

## Task 20 — Edge Protection for Public Ingest (2026-02-21)

### What changed

- Added optional Cloud Armor edge protection for public ingest in Terraform:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/edge_protection.tf`
  - provisions HTTPS LB + Cloud Armor security policy for the primary ingest service
  - includes edge throttling independent of app logic
  - supports optional trusted CIDR allowlist bypass and preview mode
- Added Terraform inputs/validations:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/variables.tf`
  - `enable_ingest_edge_protection`, `ingest_edge_domain`, rate-limit tuning vars, allowlist vars
- Added Terraform outputs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/outputs.tf`
  - `ingest_edge_url`, `ingest_edge_security_policy_name`
- Fixed Terraform profile var-file handling for `-chdir` workflows:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/Makefile`
  - `TFVARS_ARG` now normalizes `infra/gcp/cloud_run_demo/...` paths to chdir-relative paths.
- Updated profile/docs guidance:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles/stage_public_ingest_private_admin.tfvars`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles/stage_public_ingest_private_dashboard_private_admin.tfvars`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles/prod_public_ingest_private_admin.tfvars`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/infra/gcp/cloud_run_demo/profiles/prod_public_ingest_private_dashboard_private_admin.tfvars`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DEPLOY_GCP.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/security.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/PRODUCTION_POSTURE.md`
- Added runbook:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/EDGE_PROTECTION.md`
- Updated task status/queue:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/20-edge-protection-cloud-armor.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CODEX_HANDOFF.md`

### Why it changed

- Task 20 requires perimeter throttling for internet-exposed ingest so abuse/cost incidents are mitigated before requests hit app code.
- This preserves current least-privilege multi-service posture while adding an optional, Terraform-first edge control layer.

### How it was validated

- `make fmt` ✅
- `make lint` ✅
- `make typecheck` ✅
- `make test` ✅
- `make harness` ✅
- `make tf-check` ✅
- `terraform -chdir=infra/gcp/cloud_run_demo init -backend=false` ✅
- `terraform -chdir=infra/gcp/cloud_run_demo validate` ✅
- `make -n plan-gcp-stage-iot` ✅ confirms normalized profile var-file path (`profiles/...`) with `-chdir`
- `terraform -chdir=infra/gcp/cloud_run_demo plan -var-file=profiles/stage_public_ingest_private_admin.tfvars ...` ✅
  - plan includes new resources:
    - `google_compute_security_policy.ingest_edge`
    - `google_compute_backend_service.ingest_edge`
    - `google_compute_global_forwarding_rule.ingest_edge`
    - `ingest_edge_url` output

### Risks / rollout notes

- Enabling edge protection requires DNS for `ingest_edge_domain` and routing devices to `ingest_edge_url`.
- If a fleet is heavily NATed, per-IP throttling can over-limit; tune `ingest_edge_rate_limit_*` or use `XFF_IP` where appropriate.
- Manual edge-throttle smoke in a real GCP environment is still required before production enforcement.

### Follow-ups / tech debt

- [ ] Add a CI smoke target that exercises Cloud Armor preview-mode logs in a staging project.

## Task 14 — UI/UX Polish (IAP operator posture) (2026-02-22)

### What changed

- Added shared admin auth-error guidance utilities:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/utils/adminAuth.ts`
  - parses HTTP status from client errors and returns mode-aware operator guidance.
- Fixed app shell capability wiring:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/RootLayout.tsx`
  - now passes `adminEnabled` and `adminAuthMode` from `/api/v1/health` into `AppShell`, so Admin nav/badges correctly reflect backend posture.
- Improved IAP/key recovery UX on admin audit surfaces:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Admin.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/DeviceDetail.tsx`
  - each view now shows actionable guidance on 401/403 failures:
    - `ADMIN_AUTH_MODE=none`: sign-in/perimeter + role guidance
    - `ADMIN_AUTH_MODE=key`: admin-key recovery guidance
- Updated docs/task status:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/WEB_UI.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/14-ui-ux-polish.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`

### Why it changed

- Task 14’s final remaining item was IAP operator login/access UX after Task 18.
- Operators previously saw raw 401/403 strings in some audit views, which is not enough for production troubleshooting.
- The shell capability wiring fix ensures role/posture indicators are trustworthy across environments.

### How it was validated

- `make harness` ✅
- `pnpm -r --if-present build` ✅
- `pnpm -C web typecheck` ✅
- `make lint` ✅
- `make test` ✅

### Risks / rollout notes

- Guidance is intentionally based on HTTP status categories (401/403), not brittle backend string matching.
- No backend auth behavior changed; this is UI/operator guidance and shell capability wiring only.

### Follow-ups / tech debt

- [ ] Consider adding dedicated frontend component tests when a web test harness is introduced (currently repo gates web typecheck/build).

## Task 11 (Epic) — Edge Sensor Suite closeout (2026-02-22)

### What changed

- Closed the Task 11 epic status and queue docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/11-edge-sensor-suite.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CODEX_HANDOFF.md`
- Updated sensor runbook wording from planned posture to implemented posture:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/SENSORS.md`
- Completed the remaining Task 11 UI acceptance gap by exposing oil-life reset timestamp end-to-end:
  - agent derived backend now emits `oil_life_reset_at` alongside `oil_life_pct`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/backends/derived.py`
  - telemetry contract now includes `oil_life_reset_at` as a string metric
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/contracts/telemetry/v1.yaml`
  - device detail oil-life gauge now renders “Last reset” when present
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/DeviceDetail.tsx`
  - docs and tests updated:
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DOMAIN.md`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/WEB_UI.md`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_sensor_derived.py`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_contracts.py`

### Why it changed

- Task 11 remained in queue as an epic wrapper even though `11a..11d` were shipped.
- The epic acceptance criteria called for oil-life gauge visibility with last reset context; this change makes that operator context available in the UI via contract-backed telemetry.

### How it was validated

- `make harness` ✅
- `make lint` ✅
- `make test` ✅
- `pnpm -C web typecheck` ✅
- `pnpm -r --if-present build` ✅

### Risks / rollout notes

- `oil_life_reset_at` is additive and backward compatible; devices that do not emit it continue to work.
- No API route or auth behavior changed.
- No Terraform or migration changes.

### Follow-ups / tech debt

- [x] Camera epic (`docs/TASKS/12-camera-capture-upload.md`) closeout completed on 2026-02-22.

## Task 12 (Epic) — Camera capture + media upload closeout (2026-02-22)

### What changed

- Completed the remaining agent integration work for the Task 12 epic:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/media/runtime.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/edgewatch_agent.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/media/storage.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/media/__init__.py`
- Added alert-transition photo capture support in the runtime loop (edge-triggered with cooldown).
- Added metadata-first media upload pipeline in the agent:
  - `POST /api/v1/media` then `PUT /api/v1/media/{id}/upload`
  - deterministic media message IDs for retry idempotency
  - oldest-first upload from ring buffer with per-asset retry backoff
  - successful uploads delete local assets from the ring buffer
- Added/updated operator docs and env knobs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/.env.example`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/RUNBOOKS/CAMERA.md`
- Closed queue bookkeeping docs for Task 12:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/12-camera-capture-upload.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/TASKS/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CODEX_HANDOFF.md`
- Added deterministic tests for upload + alert-transition behavior:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_media_runtime.py`

### Why it changed

- Task 12 was still open at the epic level even though `12a/12b/12c` were shipped.
- The missing production slice was device-side upload orchestration from the local ring buffer to the existing API media endpoints.

### How it was validated

- `uv run --locked pytest -q tests/test_media_runtime.py` ✅
- `python scripts/harness.py lint --only python` ✅
- `python scripts/harness.py test --only python` ✅
- `python scripts/harness.py typecheck --only python` ✅
- `make harness` ✅

### Risks / rollout notes

- Upload retries are per-asset in-memory; after agent restart, pending ring-buffer assets are still retried, but backoff timing state resets.
- Video capture remains out of scope for this epic closeout and should be handled as a separate follow-on task.
- No Terraform/auth/public API contract changes in this PR.

### Follow-ups / tech debt

- [ ] Optional: add a small integration smoke test that exercises media upload loop against a live API fixture.

## Dashboard Fleet Map (2026-02-22)

### What changed

- Added an interactive fleet map to the dashboard:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/components/FleetMap.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Dashboard.tsx`
- Map behavior:
  - reads device coordinates from latest telemetry metrics (`latitude/longitude`, `lat/lon`, `lat/lng`, `gps_latitude/gps_longitude`, `location_lat/location_lon`)
  - renders status-colored markers (online/offline/unknown)
  - supports click selection with device details and open-alert count
  - includes recenter control and map coverage badges
- Added local-demo compatibility so map is useful immediately:
  - mock sensor backend now emits deterministic coordinates per device:
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/mock_sensors.py`
  - telemetry contract now includes:
    - `latitude`
    - `longitude`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/contracts/telemetry/v1.yaml`
- Added Leaflet dependency for interactive mapping:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/package.json`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/pnpm-lock.yaml`
- Updated UI docs:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/WEB_UI.md`

### Why it changed

- Operators need spatial awareness in the dashboard to correlate device status/alerts by location instead of scanning only tables/cards.
- Local simulator and mock-sensor workflows should show useful map output out-of-the-box.

### How it was validated

- `pnpm -C web typecheck` ✅
- `pnpm -C web build` ✅
- `uv run --locked pytest -q tests/test_sensor_scaling.py tests/test_contracts.py` ✅
- `make harness` ✅

### Risks / rollout notes

- Web bundle size increased due Leaflet (still within existing build warnings).
- Dashboard map relies on OpenStreetMap tile requests at runtime; operator environments with strict egress policies may require an internal tile source later.
- No API route/auth/Terraform changes.

### Follow-ups / tech debt

- [ ] Optional: add dashboard-side location filter controls (status + bounding-box).
- [ ] Optional: support configurable tile providers for private/air-gapped deployments.

## Web Tables — Overflow + Alignment Fix (2026-02-22)

### What changed

- Stabilized all app tables by updating the shared table component:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/DataTable.tsx`
- Removed absolute-position virtualization rows that caused header/body misalignment and row overlap with variable-height cell content.
- Switched to native `<tbody>/<tr>` rendering so column widths and row geometry stay consistent across all pages.
- Tightened cell styles to improve overflow behavior:
  - headers stay on one line (`whitespace-nowrap`)
  - cell content wraps safely (`overflow-wrap:anywhere`)
  - cell content container uses `min-w-0` to prevent spillover.

### Why it changed

- Multiple pages were showing text overflow and visibly misaligned columns because every table uses this shared component.
- The previous virtualization strategy assumed fixed-height rows (`44px`) while many cells contain variable-height content (`details`, JSON previews, badges), which broke layout.

### How it was validated

- `pnpm -C web typecheck` ✅
- `pnpm -C web build` ✅
- `make harness` ✅

### Risks / rollout notes

- Rendering is now non-virtualized; this trades some performance headroom on very large tables for consistent, correct layout.
- No API, auth, migration, or Terraform behavior changed.

### Follow-ups / tech debt

- [ ] If any table grows to very large row counts, reintroduce virtualization with a width-safe row layout strategy and variable-height support.

## Map Rendering + Table Hardening (2026-02-22)

### What changed

- Updated CSP headers to allow OpenStreetMap tile image domains so Leaflet can render map tiles in the dashboard:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/main.py`
  - added `https://tile.openstreetmap.org` and `https://*.tile.openstreetmap.org` to `img-src` for docs and non-docs responses.
- Hardened shared table layout behavior to prevent content overflow and column drift:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/DataTable.tsx`
  - switched table layout to fixed-width columns (`table-fixed`, `w-full`)
  - added `max-w-0` + stronger word wrapping on headers and cells
  - split scroll behavior into explicit `overflow-x-auto overflow-y-auto`.

### Why it changed

- Dashboard map could appear blank when served by the API because strict CSP blocked external OSM tile images.
- Some data-heavy tables still exhibited overflow/misalignment with long values; stronger shared table constraints were needed to keep all pages stable.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅

## Strict Admin Key Gating (2026-02-23)

### What changed

- Added shared admin-access validation hook:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/hooks/useAdminAccess.ts`
  - validates key-mode admin access against `/api/v1/admin/events?limit=1`.
- Wired validated admin state into app shell/nav:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/RootLayout.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/AppShell.tsx`
- Updated admin access gating in pages to rely on validated access (not just non-empty key):
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Contracts.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Admin.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/DeviceDetail.tsx`

### Why it changed

- Prevented admin-only UI affordances (for example, Contracts nav/page visibility) from appearing when an incorrect key is present in browser state.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅

## Settings Admin Key Validation UX (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
- Changed `Save (session)` and `Save + persist` behavior:
  - key is now validated against admin API before being stored
  - success toast is shown only when validation succeeds
  - invalid key now returns an error toast with access guidance
- Replaced raw inline JSON error blocks in Settings with user-facing guidance callouts for admin access/load/save failures.

### Why it changed

- Prevented misleading success toasts when an invalid admin key is entered and removed raw backend error payloads from visible UI content.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅

## Devices Page Policy Blurb Removal (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Devices.tsx`
- Removed the right-side `Policy` info block containing:
  - `policy: v1 · <sha>`
  - implementation note about `/api/v1/devices/summary` + `/api/v1/alerts?open_only=true`
- Adjusted the filters grid from three columns to two columns to match remaining content.

### Why it changed

- Simplified the Devices page by removing low-value implementation-detail text from the UI.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅

## Device Detail Cleanup (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/DeviceDetail.tsx`
- Removed the `Telemetry contract` callout card from the device detail page (`/devices/:deviceId`) overview section.

### Why it changed

- Simplified the page and removed low-value duplicate contract context from the bottom of the device detail view.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅

## Settings: Contract Policy Controls (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
- Added a new admin-only `Contract policy controls` card on Settings.
- Added a curated UI for high-signal edge policy values:
  - reporting cadence
  - key alert thresholds
  - selected cost caps
- Added a full `Edit edge policy contract (YAML)` editor section on Settings.
- Both save paths use existing admin contract endpoints and remain inactive when admin mode is not active.
- Kept `/contracts` page behavior intact.

### Why it changed

- Allows operators to manage important contract policy settings directly from Settings while preserving full YAML control for advanced edits.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅

### Risks / rollout notes

- CSP now permits OSM tile images; if your environment disallows public egress, map tiles will still be blocked by network policy.
- `table-fixed` prioritizes layout stability; very dense tables may wrap more aggressively than before.

### Follow-ups / tech debt

- [ ] Optional: support a configurable internal tile source for private/air-gapped deployments.

## Springfield, CO Device Radius (2026-02-22)

### What changed

- Updated demo/mock telemetry location generation to place devices within 50 miles of Springfield, Colorado:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/agent/sensors/mock_sensors.py`
  - switched from fixed degree offsets to deterministic geodesic placement with a 50-mile cap.
- Updated dashboard demo fallback location logic to the same Springfield, CO + 50-mile radius model:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/components/FleetMap.tsx`
  - uses deterministic distance/bearing math for fallback markers.

### Why it changed

- Aligns the fleet geography with your requested area while keeping deterministic placement behavior.
- Ensures both telemetry-based coordinates and map fallback coordinates use the same regional constraints.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅

### Risks / rollout notes

- Existing telemetry points already stored in the database keep their old coordinates; new simulated points use Springfield-area coordinates.
- Map fallback applies only when location metrics are missing for demo devices.

### Follow-ups / tech debt

- [ ] Optional: expose demo center/radius as configuration instead of code constants.

## Dashboard Tile Navigation (2026-02-22)

### What changed

- Made dashboard metric tiles keyboard/click navigable:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Dashboard.tsx`
  - top summary tiles now route on activation:
    - `Total devices`, `Online`, `Offline` -> `/devices`
    - `Open alerts` -> `/alerts`
  - vitals/threshold tiles now route on activation:
    - `Low water pressure`, `Low battery`, `Weak signal`, `Low oil pressure`, `Low oil level`, `Low drip oil`, `Oil life low`, `No telemetry yet` -> `/devices`
- Added accessibility/interaction behavior:
  - card tiles get `role="button"`, `tabIndex=0`, Enter/Space activation, and focus ring styling.
  - nested interactive controls (existing device links inside tiles) are preserved and do not trigger tile-level navigation.

### Why it changed

- Supports direct dashboard navigation workflow from tile summaries (including the requested alerts tile behavior).

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅

### Risks / rollout notes

- Tiles route to page-level destinations, not pre-filtered deep links; users may still need to apply filters after navigation.

### Follow-ups / tech debt

- [ ] Optional: add route search params for status/threshold filters and wire each tile to a pre-filtered destination.

## Device Detail Timeseries 500 Fix (2026-02-22)

### What changed

- Fixed SQLAlchemy 2 JSON extraction breakage in timeseries routes:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/devices.py`
  - replaced deprecated `.astext` usage with dialect-aware JSON text extraction helper (`->>` for Postgres, `json_extract` for SQLite).
- Hardened metric key handling:
  - validates metric keys against `^[A-Za-z0-9_]{1,64}$` in `/timeseries` and `/timeseries_multi`.
- Kept numeric aggregation safe:
  - Postgres uses regex-guarded cast to avoid invalid numeric cast errors.
  - non-Postgres uses float casting on extracted JSON text.
- Added regression tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_timeseries_routes.py`
  - verifies SQL compilation path for Postgres/SQLite extraction and invalid metric-key rejection.

### Why it changed

- Device detail chart requests to `/api/v1/devices/{id}/timeseries_multi` were returning `500` due `AttributeError` (`.astext`) under SQLAlchemy 2.

### How it was validated

- Reproduced failing request locally against running API (`500`) before patch.
- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅
- Retested failing endpoint request locally after patch (`200`) ✅

### Risks / rollout notes

- Metric-key validation now returns `400` for invalid keys that were previously accepted implicitly.

### Follow-ups / tech debt

- [ ] Optional: add full integration tests for `/timeseries` and `/timeseries_multi` with a Postgres test fixture.

## Professional Copy Refresh (2026-02-22)

### What changed

- Updated `Meta` contracts description for clearer operational intent:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Meta.tsx`
  - now describes contracts as active telemetry/edge-policy artifacts used for validation, policy enforcement, and UI behavior.
- Refined `Settings` copy to a professional operations tone:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
  - removed the explicit “Theme is stored in localStorage.” wording
  - removed informal “Tip” style helper text (including demo-device references)
  - tightened security and admin-access descriptions for production posture
  - updated links card description to “Operational links.”

### Why it changed

- Improve clarity and professionalism of operator-facing language and remove tutorial/portfolio-style wording.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅

### Risks / rollout notes

- Copy-only change; no API behavior, auth model, or data contract changes.

### Follow-ups / tech debt

- [ ] Optional: perform a broader UX copy pass for consistent enterprise tone across all pages.

## Admin Key UX Clarification (2026-02-22)

### What changed

- Clarified admin auth failure guidance:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/utils/adminAuth.ts`
  - 401 hint now explicitly states the key must exactly match server `ADMIN_API_KEY` and includes the local default (`dev-admin-key`).
- Clarified settings helper copy:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
  - admin key help text now explicitly states the key must match server `ADMIN_API_KEY`.

### Why it changed

- Reduce operator confusion when a saved key still fails with `401 Invalid admin key` by making the mismatch cause explicit in-product.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅
- Manual verification against local API:
  - `X-Admin-Key: dev-admin-key` returns `200` on `/api/v1/admin/events`
  - mismatched key returns `401 Invalid admin key`

### Risks / rollout notes

- Copy-only UX clarification; no auth logic or API contract changes.

### Follow-ups / tech debt

- [ ] Optional: add a “Validate admin key” action on Settings to test credentials before navigating to Admin pages.

## Admin Key 401 Persistence Fix (2026-02-22)

### What changed

- Forced admin-query refetch on credential posture changes:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Admin.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/DeviceDetail.tsx`
  - invalidates cached `['admin', ...]` queries when auth mode or admin key changes to prevent sticky 401 states from prior credentials.
- Normalized backend admin key input:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/config.py`
  - reads `ADMIN_API_KEY` via trimmed optional-string helper to avoid hidden leading/trailing whitespace mismatches.
- Added regression coverage:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_route_surface_toggles.py`
  - verifies `load_settings()` trims `ADMIN_API_KEY`.

### Why it changed

- Resolve repeated `401 Invalid admin key` outcomes after key updates by ensuring the frontend does not keep stale auth-query state, and by hardening server-side key parsing against accidental whitespace.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`116 passed`)

### Risks / rollout notes

- Frontend now performs extra admin-query invalidation when key/mode changes; expected to be low-cost and bounded to admin query namespace.
- `ADMIN_API_KEY` trimming changes behavior only for accidental surrounding whitespace.

### Follow-ups / tech debt

- [ ] Optional: add a one-click “validate key” probe in Settings for immediate credential verification.

## Admin Key Normalization Hardening (2026-02-22)

### What changed

- Normalized admin key input client-side before storage and request headers:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/app/settings.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts`
  - accepts common paste formats (`ADMIN_API_KEY=...`, `export ADMIN_API_KEY=...`, quoted values).
- Normalized admin key server-side before HMAC compare:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/auth/principal.py`
  - prevents format/paste artifacts from causing false `401 Invalid admin key`.
- Added backend regression tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_security.py`
  - covers assignment-style and quoted admin-key headers.

### Why it changed

- Repeated operator reports of `401 Invalid admin key` despite saving keys indicated key-format mismatch risk (copied env syntax/quotes), not only value mismatch.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`118 passed`)
- Manual curl verification against local API:
  - `X-Admin-Key: "dev-admin-key"` -> `200`
  - `X-Admin-Key: ADMIN_API_KEY=dev-admin-key` -> `200`
  - `X-Admin-Key: export ADMIN_API_KEY=dev-admin-key` -> `200`

### Risks / rollout notes

- Admin key parser is now intentionally tolerant of common env/paste wrappers; auth still requires exact normalized key match.

### Follow-ups / tech debt

- [ ] Optional: add a dedicated Settings “Validate key” action that probes `/api/v1/admin/events?limit=1` and surfaces immediate pass/fail.

## UI-Managed Alert Webhook Destinations (2026-02-22)

### What changed

- Added persistent notification destination model and migration:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/models.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/migrations/versions/0011_notification_destinations.py`
  - new table: `notification_destinations` (name, channel, kind, webhook_url, enabled, timestamps).
- Added admin API for destination management:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/admin.py`
  - endpoints:
    - `GET /api/v1/admin/notification-destinations`
    - `POST /api/v1/admin/notification-destinations`
    - `PATCH /api/v1/admin/notification-destinations/{destination_id}`
    - `DELETE /api/v1/admin/notification-destinations/{destination_id}`
  - includes URL validation, masked URL responses, and admin audit events.
- Extended schemas for destination CRUD:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/schemas.py`
- Updated notification delivery pipeline:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/notifications.py`
  - uses all enabled UI-configured destinations (supports multiple webhooks).
  - keeps backward compatibility fallback to `ALERT_WEBHOOK_URL` when no DB destinations are configured.
- Added Settings UI management for webhook destinations:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
  - users can add, list, enable/disable, and remove multiple webhook destinations.
- Added frontend API bindings/types:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts`
- Added notification service tests:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_notifications_service.py`
  - covers no-adapter behavior, multi-destination delivery, and env fallback.

### Why it changed

- Enable operators to configure alert webhook URLs directly in the UI and support multiple destinations without editing deployment environment variables.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`121 passed`)
- Runtime verification:
  - rebuilt and restarted compose services with migration (`docker compose up -d --build migrate api`)
  - verified `POST` + `GET` + `DELETE` on `/api/v1/admin/notification-destinations` with `X-Admin-Key`.

### Risks / rollout notes

- Webhook URLs are persisted in database storage for UI management; responses expose only masked URL + fingerprint.
- If at least one DB destination exists, delivery uses DB destinations; env `ALERT_WEBHOOK_URL` remains fallback only when no DB destination is configured.

### Follow-ups / tech debt

- [ ] Optional: add per-destination test-send action in Settings.
- [ ] Optional: add destination-level rate controls / channel-specific routing policy.

## Discord/Telegram Notification Kinds (2026-02-22)

### What changed

- Extended alert delivery kind support:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/config.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/schemas.py`
  - allowed kinds now include `discord` and `telegram` (while keeping `generic` and `slack` for compatibility).
- Implemented Discord/Telegram payload behavior:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/services/notifications.py`
  - `discord`: sends `content` message payload.
  - `telegram`: requires `chat_id` in webhook URL query and sends Telegram-style payload.
- Updated Settings UI webhook kind options:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
  - primary options now `Discord`, `Telegram`, plus `Generic`.
  - added Telegram guidance for `chat_id` query requirement.
- Updated frontend API typing:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts`
- Added test coverage:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_notifications_service.py`
  - validates multi-destination delivery including Discord+Telegram and Telegram missing-`chat_id` failure behavior.

### Why it changed

- Align notification delivery with operator requirements to use Discord/Telegram instead of Slack.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`122 passed`)
- Runtime verification:
  - rebuilt API container (`docker compose up -d --build api`)
  - confirmed admin destination API accepts `discord` and `telegram` kinds.

### Risks / rollout notes

- Telegram delivery now requires `chat_id` on the configured URL query string; otherwise events are recorded as `delivery_failed` with explicit reason.

### Follow-ups / tech debt

- [ ] Optional: support Telegram `chat_id` as a dedicated field instead of URL query parsing.

## Admin-Only Contracts + Edge Policy Editing (2026-02-22)

### What changed

- Restricted Contracts navigation visibility to authenticated admin access:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/RootLayout.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/AppShell.tsx`
  - Contracts now require both admin routes enabled and active admin access.
- Added Contracts page admin gating + edit UX:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Contracts.tsx`
  - non-admin users now see explicit access callouts.
  - admins can edit active edge-policy YAML inline and save/reset changes.
- Added admin contract source/update API bindings:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/api.ts`
- Added backend support for editable edge policy contract:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/edge_policy.py`
  - new helpers to read/write YAML source with full policy validation and cache invalidation.
- Added admin endpoints for edge policy contract management:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/routes/admin.py`
  - `GET /api/v1/admin/contracts/edge-policy/source`
  - `PATCH /api/v1/admin/contracts/edge-policy`
  - update calls are audit-attributed via `admin_events`.
- Added schemas/docs/tests for the new contract edit surface:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/api/app/schemas.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/CONTRACTS.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_device_policy.py`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_route_surface_toggles.py`

### Why it changed

- Ensure contract controls are limited to admin users.
- Enable direct admin management of the active edge policy contract without manual file edits outside the UI.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`125 passed`)

### Risks / rollout notes

- Contract edits persist to the active YAML artifact on disk; in ephemeral/readonly runtimes this can fail with a server error.
- Validation prevents saving malformed policy content or version mismatches.

### Follow-ups / tech debt

- [ ] Optional: add optimistic concurrency (expected hash) for multi-admin edit collisions.

## Admin Page Input Lock + Key Callout Emphasis (2026-02-22)

### What changed

- Updated admin input behavior in:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Admin.tsx`
- Added a shared `inputsDisabled` guard tied to admin access state.
- Applied disabled state to all Admin page text inputs (and related provisioning controls), so fields are inactive when admin is inactive.
- Updated `Callout` to support a warning tone and applied it to the `Admin key required` message for stronger visual emphasis.

### Why it changed

- Prevent accidental interaction with admin form controls when no active admin access is present.
- Make missing-admin-key state more obvious and actionable.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅

### Risks / rollout notes

- None beyond presentation/state changes in the Admin UI.

### Follow-ups / tech debt

- [ ] Optional: apply warning callout variant to other access-blocked admin contexts for consistency.

## Sidebar Footer Reachability (2026-02-22)

### What changed

- Updated desktop shell layout in:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/ui-kit/components/AppShell.tsx`
- Made the desktop sidebar viewport-pinned (`sticky top-0 h-screen`) instead of stretching with full page content height.
- Enabled internal scrolling for long nav lists (`overflow-y-auto`) so footer actions remain reachable.

### Why it changed

- Prevented a UX issue where users had to scroll to the bottom of long pages to access sidebar footer controls (Theme toggle / API Docs links).

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅

### Risks / rollout notes

- Low risk CSS-only layout change scoped to desktop sidebar behavior.

## Idempotent Demo Device Bootstrap (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/Makefile`
- `make demo-device` is now idempotent:
  - first attempts `POST /api/v1/admin/devices`
  - on `409 Conflict`, automatically falls back to `PATCH /api/v1/admin/devices/{device_id}`
  - prints final response body in either path

### Why it changed

- Rerunning local setup was failing when the demo device already existed, causing noisy failures during normal iteration.

### How it was validated

- `make demo-device` ✅
  - returned `Demo device already existed; updated: demo-well-001`

### Risks / rollout notes

- Low risk; scoped to local developer tooling behavior.

## Settings Layout Cleanup (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
- Removed the `Links` card from the Settings page.
- Adjusted the Settings card grid to `items-start` so cards keep natural height and `Appearance` no longer stretches to the full row height.

### Why it changed

- Simplified the Settings page and corrected card sizing behavior for a cleaner professional layout.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅

## Settings YAML-to-Controls Sync Hardening (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
- Hardened contract YAML numeric extraction used by `Contract policy controls`:
  - accepts `key : value` and `key: value` spacing variants
  - normalizes quoted numeric literals and numeric underscores (for example `"30"`, `50_000_000`)
- Updated contract control sync behavior so YAML edits re-sync controls even when the draft initializes later:
  - `policyYamlDraft` changes now sync against `importantDraft` with fallback to `importantInitial`
  - effect now depends on both `policyYamlDraft` and `importantInitial`
- Updated YAML key replacement regex used by `Save policy values` to also support `key : value` formatting.

### Why it changed

- Users editing `Edit edge policy contract (YAML)` could end up with stale values in `Contract policy controls` when YAML formatting varied or when YAML was edited before the controls draft state fully initialized.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`125 passed`)

### Risks / rollout notes

- YAML-to-controls sync still intentionally targets the explicit high-signal key list shown in `Contract policy controls`; non-exposed contract keys remain YAML-only.

## Contracts UI Consolidation Into Settings (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Settings.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Contracts.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/RootLayout.tsx`
- Moved contract details previously shown on `/contracts` into Settings (admin-active only):
  - telemetry contract table (metrics/types/units/descriptions)
  - edge policy contract summary (reporting + alert thresholds)
  - delta thresholds table
- Kept existing quick `Contract policy controls` and full `Edit edge policy contract (YAML)` sections in Settings.
- Contract sections on Settings now render only when admin mode is active.
- Removed `Contracts` from sidebar navigation.
- Simplified `/contracts` page to a handoff card linking users to Settings.

### Why it changed

- Consolidates all contract management and visibility into one admin-focused page and removes duplicate surfaces.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`125 passed`)

### Risks / rollout notes

- Users with old `/contracts` bookmarks are not blocked (page remains), but editing/inspection now happens in Settings.

## One-Command Host Dev Lane (`make dev`) (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/Makefile`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/README.md`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/docs/DEV_FAST.md`
- Added `make dev` target to run the fast host dev loop in one command:
  - starts local DB container (`db-up` equivalent)
  - starts API with hot reload on `http://localhost:8080`
  - waits for API readiness (`/readyz`)
  - bootstraps demo device by default (`make demo-device` against `:8080`)
  - starts Vite dev server on `http://localhost:5173`
  - starts simulator fleet against host API by default
  - handles Ctrl-C cleanup for spawned host processes
- Added `make dev` tuning env vars:
  - `DEV_START_SIMULATE=0`
  - `DEV_BOOTSTRAP_DEMO_DEVICE=0`
  - `DEV_STOP_DB_ON_EXIT=1`

### Why it changed

- Simplifies local development into a single command while retaining hot reload for API and UI.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`125 passed`)

### Risks / rollout notes

- `make dev` intentionally runs long-lived processes in one terminal; logs from API/UI/simulators are interleaved.
- Default behavior leaves the DB container running after exit (`DEV_STOP_DB_ON_EXIT=0`) for faster restarts.

## Dashboard Tile Filter Navigation Sync (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Dashboard.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Devices.tsx`
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx`
- Dashboard stat tiles now navigate with filter-aware query params:
  - `Online` -> `/devices?status=online`
  - `Offline` -> `/devices?status=offline`
  - `Open alerts` -> `/alerts?openOnly=true`
- Devices page now initializes and syncs filter state from URL search params (`status`, `q`/`search`, `openAlertsOnly`).
- Alerts page now initializes and syncs the `openOnly` filter from URL search params (`openOnly`/`open_only`).

### Why it changed

- Tile clicks previously navigated to the correct page path but did not carry or apply the expected filter state, causing mismatch between dashboard intent and destination-page filters.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`125 passed`)

### Risks / rollout notes

- URL filter sync currently targets the filters wired from dashboard tiles and common aliases; additional advanced filter state remains local unless explicitly encoded in search params.

## Alerts Page Routing Audit Card Removal (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx`
- Removed the `Routing audit` card section from the Alerts page.
- Removed card-only derived state and access-hint wiring that became unused after card removal.
- Updated Alerts page description copy to remove routing-audit wording.

### Why it changed

- Simplify the Alerts page by removing the routing-audit panel per product direction.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`125 passed`)

## Alerts Summary Tiles: Interactive Feed Filters (2026-02-23)

### What changed

- Updated:
  - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx`
- Made top summary tiles interactive (keyboard + click):
  - `Total` tile -> sets feed resolution filter to `all` and scrolls to Feed
  - `Open` tile -> sets feed resolution filter to `open` and scrolls to Feed
  - `Resolved` tile -> sets feed resolution filter to `resolved` and scrolls to Feed
  - `Page size` tile -> scrolls to Feed controls
- Added a tri-state feed resolution filter model (`all|open|resolved`) and corresponding Feed buttons.
- Extended alert search-param parsing to support resolution filter mapping:
  - `openOnly/open_only` -> `open`
  - `resolvedOnly/resolved_only` -> `resolved`
  - optional explicit `resolution=all|open|resolved`
- Kept dashboard deep-link behavior compatible (`/alerts?openOnly=true`).

### Why it changed

- Align tile interactions with operator expectations so summary cards act as quick pivots into the Feed with the correct filter state.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (`125 passed`)

## Dashboard Timeline Relocation + Expansion (2026-02-23)

### What changed

- Moved timeline functionality off Alerts and onto Dashboard:
  - Added a new, richer `Timeline` card to `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Dashboard.tsx`.
  - Removed the old timeline card from `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Alerts.tsx`.
- Expanded timeline capability on Dashboard:
  - Added window controls (`24h`, `72h`, `7d`, `14d`).
  - Added status scope controls (`Open only`, `Open + resolved`).
  - Added severity scope controls (`All`, `Critical`, `Warning`, `Info`).
  - Added summary tiles: alerts in scope, distinct devices, peak hour, latest alert.
  - Added severity sparklines (`total`, `critical`, `warning`, `info`).
  - Added daily drill-down with per-day totals and sample alert rows.
  - Added top impacted devices and top alert types panels.
  - Added “Open in Alerts” deep-link preserving resolution/severity context.
- Improved Alerts page filter parsing to support `severity` query parameter initialization, so links from Dashboard apply expected feed filters.

### Why it changed

- You requested that Timeline live on Dashboard instead of Alerts.
- The prior Timeline card had limited utility; the new Dashboard version adds practical incident-triage functionality and faster drill-down paths.

### How it was validated

- `python scripts/harness.py lint` (pass)
- `python scripts/harness.py typecheck` (pass)
- `python scripts/harness.py test` (pass, 125 tests)

### Risks / rollout notes

- Timeline data is built from the most recent alert page query (`limit=500`), so very high-volume fleets may need pagination or server-side aggregated endpoints for full historical completeness.
- Existing dashboard sections remain unchanged outside timeline relocation/addition.

### Follow-ups

- [ ] If needed, add a backend timeline aggregation endpoint to avoid client-side grouping limits at larger fleet sizes.
- [ ] Optionally persist dashboard timeline filter selections in URL/search params for shareable triage views.

## Dashboard Open Alerts Clarity Fix (2026-02-23)

### What changed

- Updated Dashboard open-alert semantics to show only actionable unresolved incidents.
- Added resolution-event filtering in `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Dashboard.tsx`:
  - excludes `DEVICE_ONLINE` and `*_OK` events from Dashboard “Open alerts”.
- Applied the same filter consistently to:
  - top “Open alerts” tile count,
  - Fleet map open-alert context,
  - “Open alerts” table card rows/empty state.
- Updated card copy to explicitly say recovery events are excluded.
- Also aligned Dashboard Timeline “Open only” mode to exclude resolution events.

### Why it changed

- Recovery/info events were appearing as “open” because they are unresolved event records by design, which made the dashboard look like active issues still existed.
- Dashboard now reflects user intent: show actionable unresolved problems.

### How it was validated

- `python scripts/harness.py lint` (pass)
- `python scripts/harness.py typecheck` (pass)
- `python scripts/harness.py test` (pass, 125 tests)

## Pre-Push Review Fixes (2026-02-23)

### What changed

- Fixed contracts access control gap in web UI:
  - `/contracts` now validates admin mode/access and redirects to `/settings` when admin is not active.
  - File: `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Contracts.tsx`.
- Removed raw admin key value from React Query cache keys:
  - `useAdminAccess` now uses a non-sensitive fingerprint for `key-validation` query key.
  - File: `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/hooks/useAdminAccess.ts`.
- Addressed pre-commit completeness risk:
  - Added required new source files to git tracking:
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/hooks/useAdminAccess.ts`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/migrations/versions/0011_notification_destinations.py`
    - `/Users/ryneschroder/Developer/git/edgewatch-telemetry/tests/test_notifications_service.py`
- Reduced local runtime artifact noise in working tree:
  - Added ignore rules for `edgewatch_buffer_*.sqlite-shm` and `edgewatch_buffer_*.sqlite-wal`.
  - File: `/Users/ryneschroder/Developer/git/edgewatch-telemetry/.gitignore`.

### How it was validated

- `python scripts/harness.py lint` (pass)
- `python scripts/harness.py typecheck` (pass)
- `python scripts/harness.py test` (pass, 125 tests)

## Remove Legacy Contracts Page Route (2026-02-23)

### What changed

- Removed the legacy frontend `/contracts` route from the router.
- Deleted the obsolete contracts page component; contract management remains in Settings (admin-gated).

Files:
- `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/router.tsx`
- `/Users/ryneschroder/Developer/git/edgewatch-telemetry/web/src/pages/Contracts.tsx` (deleted)

### How it was validated

- `python scripts/harness.py lint` (pass)
- `python scripts/harness.py typecheck` (pass)
- `python scripts/harness.py test` (pass, 125 tests)

## CI/CD Protocol Alignment (2026-02-23)

### What changed

- Added optional GCS-backed Terraform config workflow support (team protocol):
  - `Makefile` new vars/targets:
    - `TF_CONFIG_BUCKET`, `TF_CONFIG_PREFIX`, `TF_CONFIG_GCS_PATH`, `TF_BACKEND_HCL`
    - `tf-config-print-gcp`, `tf-config-pull-gcp`, `tf-config-push-gcp`, `tf-config-bucket-gcp`
  - `tf-init-gcp` now supports `TF_BACKEND_HCL` (file-based backend config) while preserving existing bucket/prefix mode.
- Added a manual Terraform plan workflow:
  - `.github/workflows/gcp-terraform-plan.yml`
- Updated deploy/apply/drift workflows to support optional config bundle pull from GCS when `GCP_TF_CONFIG_GCS_PATH` is set:
  - `.github/workflows/deploy-gcp.yml`
  - `.github/workflows/terraform-apply-gcp.yml`
  - `.github/workflows/terraform-drift.yml`
- Updated deployment and team docs for the new protocol:
  - `docs/WIF_GITHUB_ACTIONS.md`
  - `docs/DEPLOY_GCP.md`
  - `docs/DRIFT_DETECTION.md`
  - `docs/TEAM_WORKFLOW.md`
- Added ignore rules for local Terraform config files downloaded from GCS:
  - `.gitignore` now ignores `infra/gcp/cloud_run_demo/backend.hcl` and `infra/gcp/cloud_run_demo/terraform.tfvars`.

### Why it changed

- Align this repo with the production-grade, team-friendly protocol used in `grounded-knowledge-platform`:
  - centralized per-environment Terraform config in GCS,
  - WIF-only CI/CD auth,
  - explicit plan/apply/deploy lanes,
  - reproducible, less ad-hoc operator workflow.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅ (125 passed)
- Additional YAML parse check for workflows (including new untracked file):
  - `python - <<'PY' ... yaml.safe_load(...)` ✅

### Risks / rollout notes

- GitHub environments should define `GCP_TF_CONFIG_GCS_PATH` (recommended) to fully use the GCS config bundle flow.
- Existing deploy flow remains backward-compatible if `GCP_TF_CONFIG_GCS_PATH` is unset.

### Follow-ups

- [ ] Add `backend.hcl` + `terraform.tfvars` to each environment’s config path in GCS.
- [ ] Configure GitHub Environment variables per env (`dev|stage|prod`) and use the new `Terraform plan (GCP)` workflow as pre-apply gate.

## Manual Deploy Runbook for EdgeWatch (2026-02-23)

### What changed

- Added a new manual deployment runbook:
  - `docs/MANUAL_DEPLOY_GCP_CLOUD_RUN.md`
- The runbook is tailored for EdgeWatch and documents:
  - reusing the existing GCP project and tfstate bucket,
  - creating a repo-specific WIF provider + deploy service account,
  - using separate config prefixes in GCS: `edgewatch/dev`, `edgewatch/stage`, `edgewatch/prod`,
  - setting GitHub Environment variables for `dev|stage|prod`,
  - deploying through the repo’s plan/apply/deploy workflows.
- Added discoverability links:
  - `docs/DEPLOY_GCP.md`
  - `docs/START_HERE.md`

### Why it changed

- Provide the same proven, production-minded manual setup flow used in `grounded-knowledge-platform`, adapted to EdgeWatch naming and workflow conventions.

### How it was validated

- `python scripts/harness.py lint` ✅
- `python scripts/harness.py typecheck` ✅
- `python scripts/harness.py test` ✅

### Risks / rollout notes

- IAM role scopes in the runbook are intentionally broad enough for first-time success; tighten after first successful deploy.
- If WIF provider branch condition remains `main`-only, non-main workflow runs will fail by design.

### Follow-ups

- [ ] Add initial `backend.hcl` + `terraform.tfvars` objects to each env prefix under `edgewatch/*`.
- [ ] Run `Terraform plan (GCP)` for `dev` after setting environment variables.
