# module: service_accounts

Creates a **runtime service account** for Cloud Run services and optionally a **CI service account** for
Terraform/CI pipelines.

> Tip: Prefer GitHub Actions Workload Identity Federation over long-lived SA keys.
See `modules/github_oidc`.
