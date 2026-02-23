# Deploying to GCP (Cloud Run demo)

This repository includes an **optional** Terraform + Cloud Build demo deployment:

- Cloud Run service for the API (+ optional UI assets)
- Secret Manager for `DATABASE_URL` and `ADMIN_API_KEY`
- Optional observability resources (dashboards/alerts)
- Optional IAP perimeter for dashboard/admin services (HTTPS LB + Google login + allowlists)
- **Cloud Run Jobs** for:
  - DB migrations (`edgewatch-migrate-<env>`)
  - offline checks (`edgewatch-offline-check-<env>`)
  - retention/compaction (`edgewatch-retention-<env>`, recommended)
  - telemetry partition manager (`edgewatch-partition-manager-<env>`, recommended for Postgres scale path)
  - analytics export (`edgewatch-analytics-export-<env>`, optional)
  - synthetic telemetry (`edgewatch-simulate-telemetry-<env>`, optional)
- **Cloud Scheduler** to trigger offline checks on a cron schedule
- Optional Pub/Sub ingest lane (`enable_pubsub_ingest=true`)

The goal is a reproducible, team-friendly workflow.

For a full step-by-step manual runbook (including repo-specific WIF + config bundle setup), see:

- `docs/MANUAL_DEPLOY_GCP_CLOUD_RUN.md`

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

### Team protocol: GCS config bundle (recommended)

For shared environments, keep Terraform backend/vars in GCS:

- `backend.hcl`
- `terraform.tfvars`

Use these helpers:

```bash
# Print the effective path (defaults to gs://<PROJECT_ID>-config/edgewatch/<ENV>)
make tf-config-print-gcp ENV=dev

# Download backend.hcl + terraform.tfvars into infra/gcp/cloud_run_demo/
make tf-config-pull-gcp ENV=dev

# Upload local backend.hcl + terraform.tfvars back to GCS
make tf-config-push-gcp ENV=dev
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

If you want a **single image tag** that runs on both Cloud Run (`linux/amd64`) and arm64 devices
(Apple Silicon, Raspberry Pi), use the multi-arch build lane:

- GitHub Actions: `Publish Multi-Arch Image (Artifact Registry)`
- Local: `make build-multiarch`

See: `docs/MULTIARCH_IMAGES.md`.

### Pick a posture (profiles)

This repo ships Terraform `*.tfvars` profiles under:

`infra/gcp/cloud_run_demo/profiles/`

- **Public demo** (dev): `dev_public_demo.tfvars`
- **Staging** (private IAM + simulation): `stage_private_iam.tfvars`
- **Production** (private IAM): `prod_private_iam.tfvars`
- **Staging IoT posture** (public ingest + private admin service): `stage_public_ingest_private_admin.tfvars`
- **Production IoT posture** (public ingest + private admin service): `prod_public_ingest_private_admin.tfvars`
- **Recommended staging IoT posture (least privilege)** (public ingest + private dashboard + private admin): `stage_public_ingest_private_dashboard_private_admin.tfvars`
- **Recommended production IoT posture (least privilege)** (public ingest + private dashboard + private admin): `prod_public_ingest_private_dashboard_private_admin.tfvars`

Convenience targets:

```bash
make deploy-gcp-demo       # public demo (dev)
make deploy-gcp-stage      # private IAM (stage) + simulation
make deploy-gcp-stage-iot     # public ingest + private admin service (stage)
make deploy-gcp-stage-iot-lp  # public ingest + private dashboard + private admin (stage)
make deploy-gcp-prod          # private IAM (prod)
make deploy-gcp-prod-iot      # public ingest + private admin service (prod)
make deploy-gcp-prod-iot-lp   # public ingest + private dashboard + private admin (prod)
```

Route surface hardening (IoT posture): the provided IoT profiles set these app env vars on the **public ingest** service:

- `ENABLE_UI=0`
- `ENABLE_READ_ROUTES=0`
- `ENABLE_INGEST_ROUTES=1`

This keeps the public surface minimal while still allowing operators to use the private dashboard/admin services.

### Optional: Cloud Armor edge protection for public ingest

For internet-exposed ingest, you can front the primary service with HTTPS LB + Cloud Armor throttling:

- `enable_ingest_edge_protection=true`
- `ingest_edge_domain` (public FQDN for ingest)
- `ingest_edge_rate_limit_count`
- `ingest_edge_rate_limit_interval_sec`
- `ingest_edge_rate_limit_enforce_on_key` (`IP`, `XFF_IP`, or `ALL`)
- optional trusted CIDR bypass: `ingest_edge_allowlist_cidrs`

Terraform outputs:
- `ingest_edge_url`
- `ingest_edge_security_policy_name`

Use `ingest_edge_url` as the device ingest entrypoint when edge protection is enabled.
For operations/tuning guidance, see `docs/RUNBOOKS/EDGE_PROTECTION.md`.

### Optional: IAP perimeter for dashboard/admin

When you deploy split services (`enable_dashboard_service=true` and/or `enable_admin_service=true`), you can put those services behind IAP:

- `enable_dashboard_iap=true`
- `dashboard_iap_domain`
- `dashboard_iap_oauth2_client_id`
- `dashboard_iap_oauth2_client_secret`
- `dashboard_iap_allowlist_members` (for example: `group:ops@example.com`)

- `enable_admin_iap=true`
- `admin_iap_domain`
- `admin_iap_oauth2_client_id`
- `admin_iap_oauth2_client_secret`
- `admin_iap_allowlist_members`

Terraform outputs:
- `dashboard_iap_url`
- `admin_iap_url`

Notes:
- IAP requires DNS for the configured domain(s) and an OAuth client for IAP.
- When `enable_admin_iap=true`, Terraform sets `IAP_AUTH_ENABLED=true` on the admin service so admin routes reject requests that do not include `X-Goog-Authenticated-User-Email`.

Optional in-app RBAC (Task 15):
- set `AUTHZ_ENABLED=1`
- set role allowlists (`AUTHZ_VIEWER_EMAILS`, `AUTHZ_OPERATOR_EMAILS`, `AUTHZ_ADMIN_EMAILS`)
- keep `AUTHZ_IAP_DEFAULT_ROLE=viewer` unless you intentionally want broader default access

> Under the hood these targets set `TFVARS=...` and call `deploy-gcp-safe`.
> If `TF_BACKEND_HCL` is set (for example `backend.hcl` after `make tf-config-pull-gcp`), Terraform init uses that backend config file.

### Recommended deploy lane

Recommended (safe sequence: deploy, run migrations job, then readiness verify):

```bash
make deploy-gcp-safe ENV=dev
```

With GCS config bundle:

```bash
make tf-config-pull-gcp ENV=dev
make deploy-gcp-safe ENV=dev TF_BACKEND_HCL=backend.hcl
```

Or step-by-step:

```bash
make deploy-gcp ENV=dev
make url-gcp ENV=dev
# If enable_admin_service=true, you can also fetch the admin URL:
# make url-gcp-admin ENV=dev
# If enable_dashboard_service=true, you can fetch the dashboard URL:
# make url-gcp-dashboard ENV=dev
make verify-gcp ENV=dev

# Apply DB migrations (Cloud Run Job)
make migrate-gcp ENV=dev

# Verify DB connectivity + migrations
make verify-gcp-ready ENV=dev
```

### Accessing a private IAM-only service from your browser

If `allow_unauthenticated=false` (recommended for staging/production posture), the Cloud Run URL
requires an authenticated identity token.

For local browser access, the easiest workflow is the gcloud proxy:

```bash
gcloud run services proxy "edgewatch-telemetry-<env>" --project "$PROJECT_ID" --region "$REGION" --port 8082
open http://localhost:8082
```

Replace `<env>` with `stage` or `prod`.

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


Retention is configurable via Terraform variables:

- `enable_retention_job=true`
- `retention_job_schedule` (default: daily 03:15 UTC)
- `telemetry_retention_days` / `quarantine_retention_days`

Postgres partition manager is configurable via Terraform variables:

- `enable_partition_manager_job=true`
- `partition_manager_job_schedule` (default: every 6 hours)
- `telemetry_partition_lookback_months` / `telemetry_partition_prewarm_months`
- `telemetry_rollups_enabled`
- `telemetry_rollup_backfill_hours`

To use rollups for hourly API chart reads, set `TELEMETRY_ROLLUPS_ENABLED=true` on the Cloud Run service environment.

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

Manual trigger (retention):

```bash
make retention-gcp ENV=dev
```

Manual trigger (partition manager):

```bash
make partition-manager-gcp ENV=dev
```

## 6) Synthetic telemetry (dev + staging)

For dev/staging environments, Terraform can provision a **Cloud Run Job** plus a **Cloud Scheduler** trigger
that generates realistic-looking telemetry every minute so the UI stays "live" even without hardware.

The job entrypoint is:

```bash
python -m api.app.jobs.simulate_telemetry
```

Enable it via Terraform variables:

- `enable_simulation=true`
- `simulation_schedule="*/1 * * * *"`
- `simulation_points_per_device=1`

The `dev_public_demo` and `stage_private_iam` profiles already enable these defaults.

Manual trigger:

```bash
make simulate-gcp ENV=dev
make simulate-gcp ENV=stage
```

Guardrails:

- The simulator job is blocked from running in `APP_ENV=prod`.
- Terraform enforces `enable_simulation=false` when `env=prod`.
- Demo fleet bootstrap in staging requires explicit opt-in: `allow_demo_in_non_dev=true`.

## Production notes

### Authentication

The Terraform stack defaults to **private IAM-only** invocations (`allow_unauthenticated=false`).

For a public demo posture, use the `dev_public_demo.tfvars` profile.

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

## GitHub Actions protocol (team-ready)

Use these manual workflows:

- `.github/workflows/gcp-terraform-plan.yml`
- `.github/workflows/terraform-apply-gcp.yml`
- `.github/workflows/deploy-gcp.yml`
- `.github/workflows/terraform-drift.yml`

Required GitHub variables:

- `PROJECT_ID`
- `REGION`
- `GCP_WIF_PROVIDER`
- `GCP_WIF_SERVICE_ACCOUNT`

Recommended GitHub Environment variable (`dev`, `stage`, `prod`):

- `GCP_TF_CONFIG_GCS_PATH` (example: `gs://my-config-bucket/edgewatch/dev`)

When `GCP_TF_CONFIG_GCS_PATH` is set, workflows automatically pull
`backend.hcl` + `terraform.tfvars` from that GCS path before Terraform runs.
