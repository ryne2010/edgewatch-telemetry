# Cloud Run deployment (Terraform) — EdgeWatch

This Terraform root deploys the **EdgeWatch API + UI** to **Cloud Run**.

What this demonstrates:
- remote Terraform state (GCS)
- Artifact Registry + Cloud Build image build flow
- Secret Manager (`DATABASE_URL`, `ADMIN_API_KEY`)
- optional managed Cloud SQL Postgres (`enable_cloud_sql=true` by default)
- optional Serverless VPC Access connector (disabled by default)
- optional **Google Groups IAM starter pack** (`iam_bindings.tf`)
- optional **dashboards + alerts as code** (`observability.tf`)
- production-safe **scheduled jobs**:
  - Cloud Run Job: DB migrations (`edgewatch-migrate-<env>`)
  - Cloud Run Job: offline checks (`edgewatch-offline-check-<env>`)
  - Cloud Run Job: analytics export (`edgewatch-analytics-export-<env>`, optional)
  - Cloud Run Job: synthetic telemetry (`edgewatch-simulate-telemetry-<env>`, optional)
  - Cloud Scheduler cron trigger -> Cloud Run Jobs API
- optional Pub/Sub ingest lane (`enable_pubsub_ingest=true`)

By default this stack provisions a minimal-cost Cloud SQL Postgres instance and writes
`DATABASE_URL` into Secret Manager from Terraform.
`sqlite:///...` is not compatible with the `deploy-gcp-safe` lane because Cloud Run jobs and services do not share a local filesystem.

## Quickstart

From the repo root:

```bash
make doctor-gcp
make admin-secret

# Public demo posture (dev)
make deploy-gcp-demo

# Or: staging posture (private IAM + simulation)
make deploy-gcp-stage

# Or: staging IoT posture (public ingest + private admin service)
make deploy-gcp-stage-iot

# Or: staging IoT posture (least privilege: public ingest + private dashboard + private admin)
make deploy-gcp-stage-iot-lp

# Or: production posture (private IAM-only)
make deploy-gcp-prod

# Or: production IoT posture (public ingest + private admin service)
make deploy-gcp-prod-iot

# Or: production IoT posture (least privilege: public ingest + private dashboard + private admin)
make deploy-gcp-prod-iot-lp

# Raw lane (explicit)
# make deploy-gcp-safe ENV=dev
# or: make deploy-gcp ENV=dev && make migrate-gcp ENV=dev && make verify-gcp-ready ENV=dev
```

## Variables

Terraform variables (passed implicitly via the Makefile defaults, or overridden via `TF_VAR_*`):

- `env` — `dev|stage|prod`
- `workspace_domain` + `group_prefix` — optional Google Group IAM bindings
- `enable_observability` — create dashboard + alert policies

Service exposure + sizing:
- `allow_unauthenticated` — default `false` (private IAM); set `true` for a public demo
- `enable_ui` / `enable_read_routes` / `enable_ingest_routes` — app-level route surface toggles (recommended for IoT posture)
- `allow_public_in_non_dev` — explicit acknowledgment required to make stage/prod public
- `min_instances` / `max_instances` — default `0` / `1`
- `service_cpu` / `service_memory` — default `1` / `512Mi`
- `job_cpu` / `job_memory` — default `1` / `512Mi`

Admin surface + auth posture:
- `enable_admin_routes` — mount `/api/v1/admin/*` on the primary service (set `false` for a public ingest service)
- `admin_auth_mode` — `key|none` (`none` trusts an infrastructure perimeter like Cloud Run IAM/IAP)
- `enable_admin_service` — deploy a second, private admin Cloud Run service (recommended for production IoT)
- `admin_service_name` — optional name override for the admin service
- `admin_allow_unauthenticated` — default `false` (keep admin private)
- `admin_service_admin_auth_mode` — `key|none` for the admin service (default `none`)

Optional dashboard service (read-only UI):
- `enable_dashboard_service` — deploy a second Cloud Run service that serves UI + read endpoints only
- `dashboard_service_name` — optional name override
- `dashboard_allow_unauthenticated` — default `false` (keep dashboard private in stage/prod)



Scheduled jobs:
- `enable_scheduled_jobs` — enable Cloud Scheduler -> Cloud Run Job offline checks
- `offline_job_schedule` — cron schedule (default: every 5 minutes)
- `scheduler_time_zone` — default `Etc/UTC`
- `enable_migration_job` — create a migration job (manual execution)

Retention / compaction (recommended):
- `enable_retention_job` — provision a Cloud Run Job + Scheduler that prunes old telemetry
- `retention_job_schedule` — cron schedule (default daily)
- `telemetry_retention_days` / `quarantine_retention_days` — deletion horizon
- `retention_batch_size` / `retention_max_batches` — safety guardrails

Synthetic telemetry (dev/stage):
- `enable_simulation` — provision a Cloud Run Job + Scheduler that generates synthetic telemetry
- `simulation_schedule` — cron schedule (default: every minute)
- `simulation_points_per_device` — burst size per run

Cloud SQL:
- `enable_cloud_sql` — provision managed Postgres and manage `DATABASE_URL` secret version
- `cloudsql_tier` — default `db-f1-micro` (cost-min)
- `cloudsql_disk_size_gb` / `cloudsql_disk_type` — storage controls
- `cloudsql_deletion_protection` — recommended `true` for prod profile
- `cloudsql_user_password` — optional override (`TF_VAR_cloudsql_user_password=...`) to avoid derived fallback passwords

Optional Pub/Sub ingest:
- `enable_pubsub_ingest` — create topic + push subscription and switch app mode to `pubsub`
- `pubsub_topic_name`
- `pubsub_push_subscription_name`

Optional analytics export:
- `enable_analytics_export` — provision analytics bucket/dataset/table + export job/scheduler
- `analytics_export_schedule` — cron schedule (default hourly)
- `analytics_export_bucket_name` — optional custom bucket name
- `analytics_export_bucket_lifecycle_days` — lifecycle cleanup for staged files
- `analytics_export_dataset` / `analytics_export_table` / `analytics_export_gcs_prefix`

Demo bootstrap:
- `bootstrap_demo_device` (guardrail: must be `false` for `env=stage|prod` unless `allow_demo_in_non_dev=true`)
- `allow_demo_in_non_dev` — explicit opt-in to allow demo fleet bootstrap in staging
- `demo_fleet_size`
- `demo_device_id`, `demo_device_name`, `demo_device_token`

## Optional

### Enable the VPC connector

> Not free. Use for demos of private connectivity patterns.

```bash
TF_VAR_enable_vpc_connector=true make plan-gcp ENV=dev
TF_VAR_enable_vpc_connector=true make apply-gcp ENV=dev
```
