# Changelog

All notable changes to this project will be documented in this file.

This project follows the spirit of [Keep a Changelog](https://keepachangelog.com/) and uses
semantic-ish versioning for portfolio iterations.

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
