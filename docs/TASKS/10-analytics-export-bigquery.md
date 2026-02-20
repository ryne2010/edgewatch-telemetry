# Task: Analytics export (BigQuery)

## Intent

Add an **optional** analytics lane that exports telemetry to BigQuery for reporting, dashboards, and portfolio-ready "data architect" depth.

Key goals:
- cost-aware defaults (partitioning, clustering, incremental loads)
- contract-aware shaping (known metrics become columns)
- lineage visibility (export batches tied to contract hash)

## Non-goals

- Do not replace Postgres as the source of truth.
- Do not build a full warehouse stack unless requested.
- Do not introduce streaming costs by default.

## Proposed approach (cost-min)

Use a scheduled Cloud Run Job:
- reads new telemetry since last successful export (watermark)
- writes newline-delimited JSON to GCS
- loads into BigQuery (partitioned table)

This avoids always-on services and keeps spend predictable.

## Data shaping

Use the telemetry contract (`contracts/telemetry/v1.yaml`) to define "known" metric keys.

BigQuery table suggestion:
- `ts` (TIMESTAMP) — partition key (daily)
- `device_id` (STRING) — cluster key
- `batch_id` (STRING)
- `metrics` (JSON) — raw metrics map
- Optional: explicit numeric columns for common metrics (water_pressure_psi, oil_pressure_psi, battery_v, ...)

This hybrid approach provides:
- flexible schema for additive drift (JSON)
- fast queries for common metrics (columns)

## Lineage artifacts

Create an `export_batches` table in Postgres (or BigQuery) containing:
- export_batch_id
- started_at / finished_at
- watermark_from / watermark_to
- contract_version / contract_hash
- gcs_uri
- row_count
- success/failure

## Terraform/IaC

Add resources:
- GCS bucket for exports (lifecycle rules)
- BigQuery dataset + table(s)
- Cloud Run Job + Cloud Scheduler trigger

IAM (least privilege):
- Job SA: `roles/storage.objectAdmin` (bucket scope)
- Job SA: `roles/bigquery.dataEditor` (dataset scope)

## Acceptance criteria

- Running the job creates/updates the BigQuery table.
- Incremental loads do not duplicate rows.
- Export batches are auditable and tied to a contract hash.
- Costs are bounded via:
  - partitioned tables
  - bucket lifecycle
  - scheduler frequency defaults (e.g., hourly or daily)

## Validation plan

- Unit tests for export cursor logic.
- Integration test path (optional) using a local Postgres and a mocked GCS/BigQuery client.
- Docs: add runbook + cost notes.
