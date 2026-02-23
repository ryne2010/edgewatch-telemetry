# GitHub Actions + GCP Workload Identity Federation (WIF)

This repo supports passwordless deployments to GCP from GitHub Actions using Workload Identity Federation (WIF).

Why WIF:
- no long-lived JSON keys in GitHub
- least privilege with a dedicated deploy service account
- simpler key rotation and incident response

## Workflows in this repo

These live under `.github/workflows/`:

- `ci.yml`
  - Runs repo gates via `python scripts/harness.py all --strict`.
- `terraform-hygiene.yml`
  - Runs Terraform quality/security/policy checks.
- `gcp-terraform-plan.yml`
  - Manual Terraform plan lane (recommended before apply).
- `terraform-apply-gcp.yml`
  - Manual Terraform apply lane.
- `deploy-gcp.yml`
  - Manual safe deploy lane (`make deploy-gcp-safe`: build, apply, migrate, readiness verify).
- `publish-image-multiarch.yml`
  - Manual multi-arch image publish (`linux/amd64` + `linux/arm64`).
- `terraform-drift.yml`
  - Scheduled/manual drift detection (`terraform plan -detailed-exitcode`).

## Required GitHub variables

Set these in GitHub Actions variables (repo-level or environment-level):

- `GCP_WIF_PROVIDER`
- `GCP_WIF_SERVICE_ACCOUNT`
- `PROJECT_ID`
- `REGION`

Optional overrides:
- `TF_STATE_BUCKET` (defaults to `${PROJECT_ID}-tfstate`)
- `TF_STATE_PREFIX` (defaults to `edgewatch/<env>`)
- `AR_REPO` (defaults to `edgewatch`)

## Recommended team protocol: GCS config bundle

For production-grade team workflows, keep Terraform backend/vars in GCS per environment:

- `backend.hcl`
- `terraform.tfvars`

Set this variable on each GitHub Environment (`dev`, `stage`, `prod`):

- `GCP_TF_CONFIG_GCS_PATH` (example: `gs://my-config-bucket/edgewatch/dev`)

When `GCP_TF_CONFIG_GCS_PATH` is set, deploy/apply/plan/drift workflows automatically download:

- `${GCP_TF_CONFIG_GCS_PATH}/backend.hcl`
- `${GCP_TF_CONFIG_GCS_PATH}/terraform.tfvars`

### Bootstrap and manage the bundle locally

From repo root:

```bash
# Print the default path (override ENV as needed)
make tf-config-print-gcp ENV=dev

# Pull config from GCS into infra/gcp/cloud_run_demo/
make tf-config-pull-gcp ENV=dev

# Push local backend.hcl + terraform.tfvars back to GCS
make tf-config-push-gcp ENV=dev
```

## One-time GCP setup (high level)

1. Create a Workload Identity Pool + Provider trusted for this GitHub repo.
2. Create a deploy service account.
3. Allow the provider principal to impersonate that service account.
4. Grant minimal roles for Cloud Run deploy, Artifact Registry, Terraform backend access, and any required jobs.

## Running deploy lanes

- Plan: Actions -> **Terraform plan (GCP)**
- Apply: Actions -> **Terraform apply (GCP)**
- Full safe deploy: Actions -> **Deploy to GCP (Cloud Run)**

All are manual (`workflow_dispatch`) by design.
