# Deploying to GCP (Cloud Run demo)

This repository includes an **optional** Terraform + Cloud Build demo deployment:

- Cloud Run service for the API (+ optional UI assets)
- Secret Manager for `DATABASE_URL` and `ADMIN_API_KEY`
- Optional observability resources (dashboards/alerts)
- **Cloud Run Jobs** for:
  - DB migrations (`edgewatch-migrate-<env>`)
  - offline checks (`edgewatch-offline-check-<env>`)
  - analytics export (`edgewatch-analytics-export-<env>`, optional)
- **Cloud Scheduler** to trigger offline checks on a cron schedule
- Optional Pub/Sub ingest lane (`enable_pubsub_ingest=true`)

The goal is a reproducible, team-friendly workflow.

**Default posture (safe-by-default):** private IAM-only Cloud Run invocations.
Use a profile (below) when you intentionally want a public demo.

## 0) Prerequisites

- `gcloud` installed + authenticated
- `terraform` installed
- A GCP project with billing enabled

Recommended: set a default region:

```bash
gcloud config set run/region us-central1
```

## 1) One-time setup

Persist your project/region into your active gcloud config:

```bash
make init PROJECT_ID=<your-project> REGION=us-central1
```

Authenticate:

```bash
make auth
```

## 2) Create secrets

The Terraform demo expects these Secret Manager secrets:

- `edgewatch-database-url`
- `edgewatch-admin-api-key`

Add secret versions:

```bash
make admin-secret
```

`DATABASE_URL` is managed by Terraform when `enable_cloud_sql=true` (default).
Only run `make db-secret` if you explicitly disable managed Cloud SQL and provide your own shared Postgres backend.
For stronger credential hygiene, set an explicit DB password:

```bash
export TF_VAR_cloudsql_user_password='<strong-random-password>'
```

Important: `deploy-gcp-safe` requires a **shared** database backend reachable by both the Cloud Run
service and Cloud Run jobs. `sqlite:///...` URLs are not suitable for this lane because each container has its own filesystem.

## 3) Deploy

Deploy the service (Cloud Build builds the container image; Terraform deploys Cloud Run).

Note: Cloud Run expects `linux/amd64` (x86_64) container images. Using Cloud Build avoids Apple Silicon cross-arch build issues.

### Pick a posture (profiles)

This repo ships Terraform `*.tfvars` profiles under:

`infra/gcp/cloud_run_demo/profiles/`

- **Public demo** (portfolio): `dev_public_demo.tfvars`
- **Production** (cost-min + secure): `prod_private_iam.tfvars`

Convenience targets:

```bash
make deploy-gcp-demo  # public demo (dev)
make deploy-gcp-prod  # private IAM (prod)
```

> Under the hood these targets set `TFVARS=...` and call `deploy-gcp-safe`.

### Recommended deploy lane

Recommended (safe sequence: deploy, run migrations job, then readiness verify):

```bash
make deploy-gcp-safe ENV=dev
```

Or step-by-step:

```bash
make deploy-gcp ENV=dev
make url-gcp ENV=dev
make verify-gcp ENV=dev

# Apply DB migrations (Cloud Run Job)
make migrate-gcp ENV=dev

# Verify DB connectivity + migrations
make verify-gcp-ready ENV=dev
```

## 4) Run migrations (recommended)

When deployed to Cloud Run, this repo sets `AUTO_MIGRATE=false` intentionally.

Reason: migrations should be an explicit, auditable rollout step (not part of every cold start).

Run migrations as a Cloud Run Job:

```bash
make migrate-gcp ENV=dev
```

The job name convention is:

- `edgewatch-migrate-<env>`

## 5) Scheduled jobs

By default, the Terraform demo stack creates:

- Cloud Run Job: `edgewatch-offline-check-<env>`
- Cloud Scheduler job (cron) to trigger it

Schedule is configurable via Terraform variable `offline_job_schedule` (default: every **5** minutes).

> If you need faster detection, set it to every minute ("*/1 * * * *").

This pattern avoids duplicate work when Cloud Run scales to multiple instances.

Optional analytics lane:

- Cloud Run Job: `edgewatch-analytics-export-<env>`
- Cloud Scheduler job to trigger export (`analytics_export_schedule`, default hourly)
- GCS staging bucket with lifecycle cleanup + partitioned/clustered BigQuery table

Manual trigger:

```bash
make analytics-export-gcp ENV=dev
```

## Production notes

### Authentication

The Terraform stack defaults to **private IAM-only** invocations (`allow_unauthenticated=false`).

For a portfolio demo posture, use the `dev_public_demo.tfvars` profile.

Guardrail: to make stage/prod public, you must also set `allow_public_in_non_dev=true`.

Cost note: IAM-level auth blocks unauthorized traffic before it reaches your container.

### Verifying a private service

If the service is private, `make verify-gcp` and `make verify-gcp-ready` will try to call the
endpoint using an identity token from:

```bash
gcloud auth print-identity-token
```

If verification fails:
- ensure you're logged in (`make auth`)
- ensure your identity has `roles/run.invoker` on the service

### Background schedulers

Avoid in-process schedulers in multi-instance deployments.

This repo uses:
- Cloud Scheduler -> Cloud Run Jobs for offline checks

In the Terraform Cloud Run demo, the service is deployed with `ENABLE_SCHEDULER=false` by default.

## Troubleshooting

- Read logs:

```bash
make logs-gcp ENV=dev
```

- If `/readyz` returns 503, migrations may not be applied:

```bash
make migrate-gcp ENV=dev
```

- If `migrate-gcp` succeeds but `/readyz` still returns 503, verify `DATABASE_URL` points to a
  shared database (not a local SQLite file path).
