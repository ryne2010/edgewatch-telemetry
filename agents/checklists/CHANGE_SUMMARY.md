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

- [ ] Complete remaining Task 14 work for device-detail and alerts timeline/audit UX enhancements.
