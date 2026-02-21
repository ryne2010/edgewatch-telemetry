# Changelog

## v0.14.1 (2026-02-21)

### Added

- Codex-ready task decomposition for the “field-realistic edge node” milestone (sensors, camera, cellular) and additional production upgrade task specs.

### Changed

- Updated planning docs (`docs/ROADMAP.md`, `docs/NEXT_ITERATION.md`, `docs/CODEX_HANDOFF.md`, `docs/TASKS/README.md`) so the repo has a single coherent task queue and execution order.

## v0.14.0 (2026-02-21)

### Added

- GitHub Actions workflow to publish a **multi-arch** container image (`linux/amd64` + `linux/arm64`) to Artifact Registry.
- Makefile build lane for multi-arch images: `buildx-init`, `docker-login-gcp`, `build-multiarch`, `deploy-gcp-safe-multiarch`.
- Docs: `docs/MULTIARCH_IMAGES.md` and cross-links from `docs/DEV_MAC.md`, `docs/DEPLOY_GCP.md`, `docs/START_HERE.md`.

### Removed

- Removed a stale, unused Dockerfile under `docker/` (the root `Dockerfile` is the canonical build).

## v0.13.0 (2026-02-21)

### Added

- Route surface toggles: `ENABLE_UI`, `ENABLE_READ_ROUTES`, `ENABLE_INGEST_ROUTES`.
- Optional **dashboard Cloud Run service** (read-only UI) + least-privilege IoT profiles.
- Optional OpenTelemetry tracing (`ENABLE_OTEL=1`) with an `otel` dependency group and docs.
- Tests for route surface toggles.

### Changed

- `create_app()` accepts an optional `Settings` object (improves testability and advanced deployments).
- Meta page shows feature flags and hides docs links when docs are disabled.

### Fixed

- Terraform stage IoT profile referenced a non-existent variable (`enable_simulation_job` → `enable_simulation`).

All notable changes to this project will be documented in this file.

This project follows the spirit of [Keep a Changelog](https://keepachangelog.com/) and uses
semantic-ish versioning for demo iterations.

## [0.12.0] - 2026-02-21

### Added
- Admin surface hardening:
  - `ENABLE_ADMIN_ROUTES` to remove `/api/v1/admin/*` entirely from the primary service.
  - `ADMIN_AUTH_MODE=key|none` to choose between `X-Admin-Key` or trusting an infrastructure perimeter.
  - `/api/v1/health` now reports feature flags so the UI can adapt.
- Public-ingest safety:
  - `MAX_POINTS_PER_REQUEST` cap to prevent extremely large point batches even when request size is small.
- Terraform split-admin posture:
  - Optional second Cloud Run service (`enable_admin_service=true`) for private operator/admin endpoints.
  - New tfvars profiles for a production IoT posture (public ingest + private admin service).

### Changed
- Web UI now reads backend feature flags and:
  - hides Admin navigation when admin routes are disabled
  - hides Docs navigation when docs are disabled
  - removes “admin key required” UX when `ADMIN_AUTH_MODE=none`
- Stage/prod private IAM profiles default to `admin_auth_mode=none` (no browser-held shared secret).

### Fixed
- Edge agent retry behavior:
  - Exponential backoff now includes jitter.
  - HTTP 429 respects `Retry-After` to avoid hammering the server.


## [0.11.0] - 2026-02-21

### Added
- Defense-in-depth request protections:
  - Request body size limit middleware (`MAX_REQUEST_BODY_BYTES`).
  - In-app device-scoped ingest rate limiting (`RATE_LIMIT_ENABLED`, `INGEST_RATE_LIMIT_POINTS_PER_MIN`).
- Consistent API error envelopes + request correlation:
  - Added `GET /healthz` liveness endpoint (not in OpenAPI schema).
  - HTTPException + validation errors now return `{error:{...}}` and include `request_id`.
- Packaging support:
  - `make dist` builds a clean zip artifact (uses `git archive` when available).
- Expanded runbooks/docs:
  - `docs/architecture.md` (extended architecture)
  - `docs/security.md` (extended security)
  - `docs/RUNBOOKS/OFFLINE_CHECKS.md`
  - `docs/RPI_AGENT.md` (index/alias for Pi agent docs)

### Fixed
- `scripts/repo_hygiene.py` now correctly skips large folders like `node_modules` and `.terraform`.
- `docs/DEPLOY_RPI.md` env vars updated to match the agent implementation (`BUFFER_DB_PATH`, etc.).
- Removed/filled missing doc links referenced from `docs/START_HERE.md`.

### Changed
- CI now uses `pnpm install --frozen-lockfile` (deterministic web builds).
- Terraform stack now exposes safety limit knobs:
  - `max_request_body_bytes`
  - `rate_limit_enabled`
  - `ingest_rate_limit_points_per_min`

## [0.10.0] - 2026-02-21

### Added
- **Retention / compaction** Cloud Run Job + Scheduler (`edgewatch-retention-<env>`) to prune old telemetry data.
  - Make targets: `make retention`, `make retention-gcp ENV=<env>`
  - Runbook: `docs/RUNBOOKS/RETENTION.md`
- Structured JSON logging improvements:
  - request IDs (`X-Request-ID`)
  - Cloud Trace correlation fields (`logging.googleapis.com/trace`, `spanId`, `trace_sampled`).
- UI toasts (global) + a small `Skeleton` component for future loading states.

### Fixed
- CSP now allows FastAPI Swagger/Redoc pages in dev while keeping a strict CSP for the main UI/API.
- Web package version now matches repo distribution version.

### Changed
- Added partial indexes for open-alert feeds and timestamp indexes to support retention deletes.

## [0.9.0] - 2026-02-21

### Added
- Oil-related alerting driven by the edge policy contract:
  - `OIL_PRESSURE_LOW` / `OIL_PRESSURE_OK`
  - `OIL_LEVEL_LOW` / `OIL_LEVEL_OK`
  - `DRIP_OIL_LEVEL_LOW` / `DRIP_OIL_LEVEL_OK`
  - `OIL_LIFE_LOW` / `OIL_LIFE_OK`
- Cursor pagination + server-side filtering for alerts:
  - Query params: `before`, `before_id`, `severity`, `alert_type`
  - UI "Load more" support in Alerts page.
- Expanded edge policy thresholds returned by:
  - `GET /api/v1/contracts/edge_policy`
  - `GET /api/v1/device-policy`

### Fixed
- Device policy ETag now includes `DEFAULT_BATTERY_LOW_V` + `DEFAULT_SIGNAL_LOW_RSSI_DBM` overrides to prevent stale cached policies.
- Demo fleet derivation is now consistent across API bootstrap and the simulator job.

### Changed
- Dashboard + Devices pages now surface additional maintenance vitals (oil pressure/level, drip oil, oil life).
- Dockerfile frontend build now uses `pnpm-lock.yaml` with `--frozen-lockfile` for deterministic installs.
- Error page upgraded with reload / copy diagnostics actions.
- Added a default Content Security Policy (CSP) + additional HTTP security headers.

## [0.8.0] - 2026-02-21

### Added
- Synthetic telemetry generator (Cloud Run Job + Cloud Scheduler) for **dev + staging**:
  - `python -m api.app.jobs.simulate_telemetry`
  - Terraform knobs: `enable_simulation`, `simulation_schedule`, `simulation_points_per_device`
  - Make target: `make simulate-gcp ENV=dev|stage`
- New Terraform profile: `stage_private_iam.tfvars` (private IAM + demo fleet + simulation enabled).
- Battery + signal threshold alerting (hysteresis) driven by the edge policy contract:
  - `BATTERY_LOW` / `BATTERY_OK`
  - `SIGNAL_LOW` / `SIGNAL_OK`
- Optional threshold override env vars (primarily for debugging):
  - `DEFAULT_BATTERY_LOW_V`, `DEFAULT_SIGNAL_LOW_RSSI_DBM`

### Fixed
- `GET /api/v1/devices/summary` could throw a runtime error due to a missing `fastapi.status` import.

### Changed
- Terraform guardrail updated to allow demo bootstrap in staging only via explicit opt-in (`allow_demo_in_non_dev=true`).

## [0.7.0] - 2026-02-20

### Added
- Fleet-friendly endpoint `GET /api/v1/devices/summary` (status + latest selected telemetry metrics).
- Public edge policy contract endpoint `GET /api/v1/contracts/edge_policy` (cadence + thresholds for UI/edge).
- Dashboard vitals cards (low water pressure / low battery / weak signal / no telemetry) driven by edge policy thresholds.
- Alerts volume sparklines (rolling 7-day hourly buckets on the loaded dataset).
- Device detail “Vitals over time” sparklines (small multiples) for key metrics.
- Contracts page now displays both telemetry + edge policy contracts (including delta thresholds).

### Fixed
- Device detail charting no longer requests >10 metrics from `timeseries_multi` (API limit), preventing 400 errors on large contracts.
- Quick chart now clearly indicates when a selected metric is non-numeric (chart disabled + guidance to raw telemetry).

### Changed
- Removed stale legacy alias `PortfolioDevtools` (kept `AppDevtools`).
- UI pages now prefer contract-driven thresholds (edge policy) over hardcoded heuristics where possible.

## [0.6.0] - 2026-02-20

### Added
- Web UI dashboard home (fleet status, open alerts, offline devices).
- Web UI contracts page (live telemetry contract: keys/types/units/descriptions).
- Web UI settings page (theme + optional admin key).
- Web UI admin console (ingestions, drift events, notifications, exports) gated by admin key.

### Changed
- Web UI navigation shell upgraded (mobile drawer + desktop sidebar) and polished empty states.
- Device detail expanded into tabs (overview, telemetry explorer, and admin audit lanes).
- Tables now support sorting + optional row-click navigation.

## [0.5.1] - 2026-02-20

### Added
- Accepted ADRs capturing edge-node decisions:
  - switched multi-camera capture (one camera active at a time)
  - pressure sensors standardized at 0–100 psi
  - oil life model: runtime-derived with manual reset
- New bring-up runbooks:
  - `docs/RUNBOOKS/SENSORS.md`
  - `docs/RUNBOOKS/CAMERA.md`

### Changed
- Updated `docs/HARDWARE.md` to reflect the accepted ADR decisions and add 4–20 mA conditioning guidance.
- Updated sensor/camera task specs to align with the accepted decisions (manual oil-life reset; serialized camera capture).
- Clarified `oil_life_pct` description in the telemetry contract.

## [0.5.0] - 2026-02-20

### Added
- Alert routing + notification audit trail:
  - `alert_policies`, `notification_events`
  - routing controls: dedupe window, throttling, quiet hours
  - webhook/slack delivery adapter with failure-safe behavior
- Extended contract/lineage artifacts:
  - configurable unknown key handling (`allow|flag`)
  - configurable type mismatch handling (`reject|quarantine`)
  - `drift_events` + `quarantined_telemetry`
  - richer `ingestion_batches` metadata (`source`, `pipeline_mode`, drift summary, processing status)
- Agent replay CLI (`python -m agent.replay`) for bounded, idempotent backfill from local SQLite.
- Optional Pub/Sub ingest lane:
  - `INGEST_PIPELINE_MODE=direct|pubsub`
  - internal worker endpoint: `POST /api/v1/internal/pubsub/push`
- Optional analytics export lane:
  - `export_batches` audit table
  - Cloud Run job entrypoint: `python -m api.app.jobs.analytics_export`
  - optional Terraform resources for export bucket/dataset/table and scheduler
- New admin audit endpoints:
  - `GET /api/v1/admin/drift-events`
  - `GET /api/v1/admin/notifications`
  - `GET /api/v1/admin/exports`

### Changed
- Task queue is now fully marked implemented in `docs/TASKS/README.md`.
- Runbooks/docs updated for replay, pubsub mode, and analytics export lane.
- Added `make analytics-export-gcp` helper for manual Cloud Run Job execution.

## [0.4.5] - 2026-02-20

### Added
- Codex handoff guide (`docs/CODEX_HANDOFF.md`) to make the remaining task queue easier to execute in parallel.

### Fixed
- `docs/TASKS/README.md` queue status now reflects implemented Task 08 (GitHub Actions + WIF).
- `AGENTS.md` non‑negotiable idempotency invariant now matches the DB constraint (`(device_id, message_id)`).

## [0.4.4] - 2026-02-20

### Added
- Fast dev lane Makefile targets: `db-up`, `db-down`, `api-dev` (hot reload), `web-install`, `web-dev`.
- Security automation: Trivy filesystem scan (SARIF), gitleaks secret scan, CodeQL (Python + JS/TS), and Dependabot config.
- Terraform sizing knobs: `service_cpu` / `service_memory` and `job_cpu` / `job_memory` (with a cost-min demo profile).

### Changed
- Updated docs to clearly separate the Docker Compose lane (UI+API on :8082) from the host dev lane (API on :8080, UI on :5173).

### Fixed
- Removed accidental Python cache artifacts (`__pycache__`, `*.pyc`) from the repo snapshot.
- Corrected edge policy tutorial paths (`contracts/edge_policy/` instead of stale `policies/`).

## [0.4.3] - 2026-02-19

### Added
- GitHub Actions workflows for CI, Terraform hygiene, manual deploy/apply, and drift detection.
- `.gitignore` and `.terraform-version` for cleaner dev and reproducible tooling.
- `make dist` + `scripts/package_dist.py` to create a clean distribution zip (no caches/artifacts).

### Changed
- Edge agent now uses **per-alert hysteresis** (prevents cross-alert coupling), adds a **startup snapshot**, and treats
  **water pressure** as a critical alert for faster sampling + periodic alert snapshots.
- Harness now uses `uv run --locked` to enforce reproducible dependency execution.
- Heartbeats are now **silence-based**: any recorded point counts as liveness, avoiding redundant heartbeat traffic.
- Delta baselines are now maintained **per metric** (only update baselines for keys that were actually sent).

### Fixed
- Reduced spurious alerting and extra network usage caused by global-state hysteresis.
- Fixed policy refresh scheduling on HTTP 304 responses (prevents tight refetch loops).

## [0.4.2] - 2026-02-19

### Added
- **Edge policy contract** (`contracts/edge_policy/v1.yaml`) for device-side battery/data optimization.
- Device-authenticated endpoint to fetch policy with **ETag caching** (`GET /api/v1/device-policy`).
- Tutorial: tuning edge policy (`docs/TUTORIALS/EDGE_POLICY.md`).

### Changed
- Edge agent now sends telemetry **only when necessary**:
  - immediate send on alert transitions
  - periodic heartbeat keepalive
  - delta-threshold sends
  - offline buffering + retry backoff + buffer pruning
- Server water pressure alerting uses policy thresholds and adds **hysteresis** to reduce flapping.
- Demo fleet defaults now align with edge policy (heartbeat + offline threshold).
- Removed legacy `POST /api/v1/jobs/offline_check` endpoint (use Cloud Run Job entrypoints).

### Fixed
- Repo hygiene now catches generated artifacts *if they are tracked by git* (prevents accidental commits of caches/buffers).

## [0.4.1] - 2026-02-19

### Added
- Telemetry **data contract** (`contracts/telemetry/v1.yaml`) and a public endpoint to fetch it (`GET /api/v1/contracts/telemetry`).
- **Ingestion batches** (`ingestion_batches` table) to capture contract version/hash, duplicate counts, and additive drift visibility per ingest.
- Admin endpoint to inspect ingestion batches (`GET /api/v1/admin/ingestions`).
- Tutorial: adding a new metric safely (`docs/TUTORIALS/ADDING_A_METRIC.md`).

### Changed
- Ingest responses now include `batch_id` (additive field).
- API version is now derived from distribution metadata / `pyproject.toml` (single source of truth).

### Fixed
- Sanitized `uv.lock` to remove environment-specific/private package index URLs.

## [0.4.0] - 2026-02-19

### Added
- Cost-minimized production posture documentation + Terraform profiles (demo vs prod).
- GCP deploy lane separation and staff-level infrastructure hygiene targets.