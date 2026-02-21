# GitHub Actions + GCP Workload Identity Federation (WIF)

This repo supports **passwordless deployments to GCP** from GitHub Actions using **Workload Identity Federation (WIF)**.

Why WIF:
- No long‑lived JSON keys in GitHub Secrets
- Least privilege with a dedicated deploy service account
- Easier rotation / incident response

## Workflows in this repo

These live under `.github/workflows/`:

- `ci.yml`
  - Runs repo gates via `python scripts/harness.py all --strict`.
  - Intended to be the default PR/merge gate.

- `terraform-hygiene.yml`
  - Runs `make tf-check` (fmt/validate/tflint/tfsec/checkov/conftest) on Terraform changes.

- `terraform-apply-gcp.yml`
  - **Manual** (`workflow_dispatch`) Terraform apply for GCP.
  - Use this when you want to apply infrastructure changes only.

- `deploy-gcp.yml`
  - **Manual** (`workflow_dispatch`) safe deploy sequence.
  - Runs `make deploy-gcp-safe` which:
    1) builds & pushes an image
    2) applies Terraform
    3) runs migrations
    4) verifies the service is live

- `publish-image-multiarch.yml`
  - **Manual** (`workflow_dispatch`) multi-arch publish.
  - Builds and pushes a single tag containing `linux/amd64` + `linux/arm64` variants to Artifact Registry.
  - Useful when you want one tag for Cloud Run (amd64) and Apple Silicon/RPi (arm64).

- `terraform-drift.yml`
  - Scheduled drift detection.
  - Runs `terraform plan -detailed-exitcode` and fails if drift is detected.

## Required GitHub repo variables

Set these as GitHub Actions **Repository Variables** (Settings → Secrets and variables → Actions → Variables):

- `PROJECT_ID`
- `REGION`
- `GCP_WIF_PROVIDER` (Workload Identity Provider resource name)
- `GCP_WIF_SERVICE_ACCOUNT` (service account email used by GitHub Actions)

Optional (nice-to-have):

- `TF_STATE_BUCKET` (defaults to `${PROJECT_ID}-tfstate` if unset)
- `TF_STATE_PREFIX` (defaults to `edgewatch/<env>` if unset)
- `AR_REPO` (Artifact Registry repo name; defaults to `edgewatch` if unset)

## One-time GCP setup (high level)

1. Create a Workload Identity Pool + Provider that trusts your GitHub org/repo.
2. Create a deploy service account.
3. Allow the provider principal to impersonate the service account.
4. Grant the service account only the minimal roles required for:
   - Cloud Run deploy
   - Artifact Registry push
   - (Optional) Cloud Build
   - Terraform state bucket admin

The exact IAM roles depend on the posture you choose (demo vs prod).

## Running a manual deploy

- From GitHub: Actions → **Deploy to GCP (Cloud Run)** → Run workflow
- Choose `env` (e.g., `dev` or `prod`)
- Optionally pass a Terraform profile `.tfvars` file

## Notes

- The Makefile defaults are designed for a **low-cost demo posture**. For production hardening,
  follow `docs/PRODUCTION_POSTURE.md`.
- Workflows compute safe defaults if optional variables are not set.
