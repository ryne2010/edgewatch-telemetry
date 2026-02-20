# Task: Production job triggering (Cloud Scheduler / Cloud Run)

✅ **Status: Implemented** (2026-02-19)

## What changed

- Added **Cloud Run Job** entrypoints:
  - `python -m api.app.jobs.offline_check`
  - `python -m api.app.jobs.migrate`
- Terraform demo stack (`infra/gcp/cloud_run_demo/`) now supports:
  - Cloud Run Job: `edgewatch-offline-check-<env>`
  - Cloud Scheduler trigger (cron) -> Cloud Run Jobs API
  - Scheduler service account + minimal IAM bindings
- `ENABLE_SCHEDULER` is treated as **dev-only**.
  - The Terraform Cloud Run demo deploys the service with `ENABLE_SCHEDULER=false` and relies on Cloud Scheduler/Jobs.

## Why this pattern

- Cloud Run services can scale horizontally.
- In-process schedulers can duplicate work.
- Cloud Run Jobs provide a clean separation for cron / batch workloads.

## Where to look

- Terraform: `infra/gcp/cloud_run_demo/jobs.tf`
- Make shortcuts:
  - `make offline-check-gcp ENV=<env>`
  - `make migrate-gcp ENV=<env>`

## Follow-ups (optional)

- Add a second scheduler/job for other maintenance tasks (pruning old telemetry, materialized views, etc.)
