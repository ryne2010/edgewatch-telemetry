# Workload Identity Federation (WIF) for GitHub Actions

This repo includes GitHub Actions workflows that can run Terraform **without** long-lived service account keys.

Workflows:
- `terraform-hygiene.yml` — fmt/validate/lint/sec/policy (no GCP auth required)
- `terraform-apply-gcp.yml` — apply on demand (workflow_dispatch)
- `terraform-drift.yml` — scheduled drift detection (plan -detailed-exitcode)

---

## 1) Create WIF + CI service account (Repo 3)

In this portfolio, Repo 3 (`terraform-gcp-platform`) contains:
- a reusable `modules/github_oidc/`
- an example `examples/github_actions_wif/` to bootstrap WIF + a CI service account + a tfstate bucket

Follow:
- `terraform-gcp-platform/docs/WIF_GITHUB_ACTIONS.md`

---

## 2) Configure GitHub Actions Variables

GitHub → Settings → Secrets and variables → Actions → **Variables**

Set:

### WIF variables
- `GCP_WIF_PROVIDER`  
  Example: `projects/123456789/locations/global/workloadIdentityPools/my-pool/providers/github`

- `GCP_WIF_SERVICE_ACCOUNT`  
  Example: `ci-terraform@my-project.iam.gserviceaccount.com`

### Environment variables
- `PROJECT_ID` (e.g., `my-sandbox-project`)
- `REGION` (e.g., `us-central1`)
- `TFSTATE_BUCKET` (e.g., `my-sandbox-tfstate`)
- `TFSTATE_PREFIX` (e.g., `portfolio/edgewatch`)
- `WORKSPACE_DOMAIN` (optional; enables Google Groups IAM)

---

## 3) Run an apply

Actions → **terraform-apply-gcp** → Run workflow → env: `dev`

If you configure GitHub **Environments** (`dev`, `stage`, `prod`), you can require approvals for applies (recommended).

---

## Security notes

- Do **not** use downloadable service account keys for CI.
- Prefer WIF + short-lived tokens.
- Keep the CI service account least-privilege, and separate state prefixes per env.
