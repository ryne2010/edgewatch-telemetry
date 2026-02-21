# Task 08: CI/CD with GitHub Actions + GCP Workload Identity Federation (WIF)

## Goal

Provide a **repeatable, secure, and low‑cost** pipeline for:

- PR validation (lint/typecheck/tests/build)
- Terraform hygiene checks
- Optional infra apply
- Optional safe deploy to Cloud Run
- Drift detection

## Status

✅ Implemented in `.github/workflows/`:

- `ci.yml` (repo gates)
- `terraform-hygiene.yml` (fmt/validate/tflint/tfsec/checkov/conftest)
- `terraform-apply-gcp.yml` (manual apply)
- `deploy-gcp.yml` (manual safe deploy)
- `terraform-drift.yml` (scheduled drift detection)

## How to use

1) Configure GitHub Actions repo variables per `docs/WIF_GITHUB_ACTIONS.md`.

2) Confirm the GCP WIF provider + deploy service account are configured.

3) Use:
- PRs: `CI` workflow runs automatically
- Infra apply: run `Terraform apply (GCP)` manually
- Deploy: run `Deploy to GCP (Cloud Run)` manually

## Notes / gotchas

- The workflows intentionally default to **manual deploy/apply** to avoid surprise cost.
- Optional vars like `TF_STATE_BUCKET` are treated as overrides; if you leave them empty,
  the workflows compute safe defaults.

## Future improvements (optional)

- Add image vulnerability scanning (Trivy) as a non-blocking job.
- Add terraform plan output as PR comment.
- Add environment protection rules for `prod` deploys.
