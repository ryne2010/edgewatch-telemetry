# Retention / compaction (Cloud SQL + local)

EdgeWatch stores high-frequency telemetry. Without a retention policy, the `telemetry_points` table will grow forever.

This runbook covers:

- local / dev retention
- Cloud Run scheduled retention
- safety guardrails (dry-run + batch deletes)

## What gets deleted

The retention job prunes:

- `telemetry_points` rows older than `TELEMETRY_RETENTION_DAYS`
- `quarantined_telemetry` rows older than `QUARANTINE_RETENTION_DAYS`

It does **not** delete devices, alerts, ingestion batch metadata, drift events, or notification events (those are useful for audit + debugging).

## Local dev

### 1) Start the stack

```bash
make up
make db-migrate
```

### 2) Dry-run counts (recommended)

```bash
RETENTION_ENABLED=true RETENTION_DRY_RUN=true TELEMETRY_RETENTION_DAYS=7 \
  python -m api.app.jobs.retention
```

### 3) Execute retention

```bash
TELEMETRY_RETENTION_DAYS=7 QUARANTINE_RETENTION_DAYS=7 make retention
```

Notes:

- `make retention` sets `RETENTION_ENABLED=true` for you.
- Local defaults are conservative; tune days based on your dev data volume.

## Cloud Run (Terraform)

The Terraform demo stack provisions:

- a Cloud Run Job: `edgewatch-retention-<env>`
- a Cloud Scheduler trigger (cron)

### Enable and tune retention

In a Terraform profile (`infra/gcp/cloud_run_demo/profiles/*.tfvars`), set:

```hcl
enable_retention_job      = true
retention_job_schedule    = "30 3 * * *" # daily at 03:30 UTC
telemetry_retention_days  = 30
quarantine_retention_days = 30
```

Then deploy:

```bash
TFVARS=infra/gcp/cloud_run_demo/profiles/stage_private_iam.tfvars make deploy-gcp
```

### Run the job manually

```bash
ENV=stage make retention-gcp
```

## Safety guardrails

- **Explicit enable**: the job will not delete data unless `RETENTION_ENABLED=true`.
- **Dry run**: set `RETENTION_DRY_RUN=true` to print counts without deleting.
- **Batch deletes** (Postgres): the job deletes in batches (`RETENTION_BATCH_SIZE`) with a maximum number of batches per run (`RETENTION_MAX_BATCHES`).

## Operational notes

- On Cloud SQL Postgres, large deletes can leave bloat. Consider periodic `VACUUM (ANALYZE)` and/or partitioning once the telemetry volume is high.
- For larger fleets and high-frequency sampling, consider **time-based partitioning** for `telemetry_points`.

