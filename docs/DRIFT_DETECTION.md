# Drift detection (Terraform)

This repo includes a scheduled GitHub Actions workflow:

- `.github/workflows/terraform-drift.yml`

It runs `terraform plan -detailed-exitcode` to detect drift (resources changed outside Terraform).

## Why it matters

In real teams, drift happens (console hotfixes, emergency IAM edits, manual tweaks).
Drift detection gives early visibility and a clean audit trail.

## How to enable

1. Configure Workload Identity Federation (WIF) for GitHub Actions (`docs/WIF_GITHUB_ACTIONS.md`).

2. Set GitHub Actions variables:

Required:
- `PROJECT_ID`
- `REGION`
- `GCP_WIF_PROVIDER`
- `GCP_WIF_SERVICE_ACCOUNT`

Optional overrides:
- `TF_STATE_BUCKET` (defaults to `${PROJECT_ID}-tfstate`)
- `TF_STATE_PREFIX` (defaults to `edgewatch/<env>`)

Recommended (team protocol):
- `GCP_TF_CONFIG_GCS_PATH` (example: `gs://my-config-bucket/edgewatch/prod`)

When `GCP_TF_CONFIG_GCS_PATH` is set, the drift workflow pulls:
- `${GCP_TF_CONFIG_GCS_PATH}/backend.hcl`
- `${GCP_TF_CONFIG_GCS_PATH}/terraform.tfvars`

before running Terraform.

## What to do when drift is detected

- Review plan output in workflow logs.
- Decide whether to revert the manual change or codify it in Terraform.
- Submit a PR and re-run plan/apply.
