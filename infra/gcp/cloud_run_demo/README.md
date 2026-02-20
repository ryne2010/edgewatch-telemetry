# Cloud Run deployment (Terraform) — EdgeWatch

This Terraform root deploys the **EdgeWatch API + UI** to **Cloud Run**.

What this demonstrates:
- remote Terraform state (GCS)
- Artifact Registry + Cloud Build image build flow
- Secret Manager (`DATABASE_URL`, `ADMIN_API_KEY`)
- optional Serverless VPC Access connector (disabled by default)
- optional **Google Groups IAM starter pack** (`iam_bindings.tf`)
- optional **dashboards + alerts as code** (`observability.tf`)
- production-safe **scheduled jobs**:
  - Cloud Run Job: DB migrations (`edgewatch-migrate-<env>`)
  - Cloud Run Job: offline checks (`edgewatch-offline-check-<env>`)
  - Cloud Scheduler cron trigger -> Cloud Run Jobs API

> Like other portfolio repos, this example does not provision a database to keep costs and coupling low. Point `DATABASE_URL` to Cloud SQL, AlloyDB, or another Postgres.

## Quickstart

From the repo root:

```bash
make doctor-gcp
make db-secret
make admin-secret

# Public demo posture (portfolio)
make deploy-gcp-demo

# Or: production posture (private IAM-only)
make deploy-gcp-prod

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
- `allow_public_in_non_dev` — explicit acknowledgment required to make stage/prod public
- `min_instances` / `max_instances` — default `0` / `1`
- `service_cpu` / `service_memory` — default `1` / `512Mi`
- `job_cpu` / `job_memory` — default `1` / `512Mi`

Scheduled jobs:
- `enable_scheduled_jobs` — enable Cloud Scheduler -> Cloud Run Job offline checks
- `offline_job_schedule` — cron schedule (default: every 5 minutes)
- `scheduler_time_zone` — default `Etc/UTC`
- `enable_migration_job` — create a migration job (manual execution)

Demo bootstrap:
- `bootstrap_demo_device` (guardrail: must be `false` for `env=stage|prod`)
- `demo_fleet_size`
- `demo_device_id`, `demo_device_name`, `demo_device_token`

## Optional

### Enable the VPC connector

> Not free. Use for demos of private connectivity patterns.

```bash
TF_VAR_enable_vpc_connector=true make plan-gcp ENV=dev
TF_VAR_enable_vpc_connector=true make apply-gcp ENV=dev
```
