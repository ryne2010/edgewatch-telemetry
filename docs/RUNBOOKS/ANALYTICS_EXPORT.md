# Analytics Export Runbook (BigQuery)

## Purpose

Run optional incremental telemetry exports from Postgres into BigQuery using a Cloud Run Job.

## Enable (Terraform)

Set:

- `enable_analytics_export=true`
- `analytics_export_dataset` / `analytics_export_table` (optional overrides)
- `analytics_export_schedule` (default hourly)

Then deploy/apply:

```bash
make apply-gcp ENV=dev
```

## Runtime behavior

- Export job entrypoint: `python -m api.app.jobs.analytics_export`
- Reads telemetry rows after last successful export watermark.
- Stages NDJSON in GCS bucket with lifecycle policy.
- Loads into partitioned+clustered BigQuery table.
- Records each run in `export_batches` (status, watermark, row_count, gcs_uri, contract hash).

## Manual execution

```bash
make analytics-export-gcp ENV=dev
```

## Verification

```bash
curl -s -H "X-Admin-Key: dev-admin-key" \
  http://localhost:8082/api/v1/admin/exports | jq
```

## Cost controls

- Lane is optional and off by default.
- Scheduled frequency defaults conservative (hourly).
- Staging bucket lifecycle auto-deletes old objects.
