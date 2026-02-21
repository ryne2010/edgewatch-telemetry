# Retention / compaction (Cloud SQL + local)

EdgeWatch stores high-frequency telemetry. Without a retention policy, the `telemetry_points` table will grow forever.

This runbook covers:

- local / dev retention
- Cloud Run scheduled retention
- safety guardrails (dry-run + batch deletes)
- Postgres partition drop behavior and partition manager job

## What gets deleted

The retention job prunes:

- whole `telemetry_points` monthly partitions older than `TELEMETRY_RETENTION_DAYS` (Postgres + partitioning enabled)
- fallback row deletes from `telemetry_points` for non-partitioned tables and partial-window cleanup
- `quarantined_telemetry` rows older than `QUARANTINE_RETENTION_DAYS`
- `telemetry_ingest_dedupe` rows older than `TELEMETRY_RETENTION_DAYS`
- `telemetry_rollups_hourly` rows older than `TELEMETRY_RETENTION_DAYS`

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

To keep monthly partitions pre-created (and refresh hourly rollups), also set:

```hcl
enable_partition_manager_job        = true
partition_manager_job_schedule      = "0 */6 * * *"
telemetry_partition_lookback_months = 1
telemetry_partition_prewarm_months  = 2
telemetry_rollups_enabled           = true
telemetry_rollup_backfill_hours     = 168
```

If you want API hourly chart endpoints to read from rollups when available, set:

```bash
TELEMETRY_ROLLUPS_ENABLED=true
```

Then deploy:

```bash
TFVARS=infra/gcp/cloud_run_demo/profiles/stage_private_iam.tfvars make deploy-gcp
```

### Run the job manually

```bash
ENV=stage make retention-gcp
ENV=stage make partition-manager-gcp
```

## Safety guardrails

- **Explicit enable**: the job will not delete data unless `RETENTION_ENABLED=true`.
- **Dry run**: set `RETENTION_DRY_RUN=true` to print counts without deleting.
- **Batch deletes** (Postgres): when row-delete fallback is used, the job deletes in batches (`RETENTION_BATCH_SIZE`) with a maximum number of batches per run (`RETENTION_MAX_BATCHES`).
- **Partition drop first**: with `TELEMETRY_PARTITIONING_ENABLED=true`, the retention job drops whole old monthly partitions before row-delete fallback.

## Operational notes

- Cloud SQL Postgres: partition drops are fast and minimize bloat compared to large row deletes.
- Keep `TELEMETRY_PARTITION_PREWARM_MONTHS` > 0 so ingest does not hit missing partition errors.
