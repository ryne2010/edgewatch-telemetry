# Terraform profiles

These `*.tfvars` files provide **opinionated presets** for common deployment postures.

Use them with the Makefile via `TFVARS=...`:

```bash
make plan-gcp  PROJECT_ID=... REGION=us-central1 TFVARS=infra/gcp/cloud_run_demo/profiles/dev_public_demo.tfvars
make apply-gcp PROJECT_ID=... REGION=us-central1 TFVARS=infra/gcp/cloud_run_demo/profiles/dev_public_demo.tfvars
```

Or use the shortcuts:

```bash
make deploy-gcp-demo PROJECT_ID=... REGION=us-central1
make deploy-gcp-prod PROJECT_ID=... REGION=us-central1
```

## Profiles

- `dev_public_demo.tfvars`
  - Public Cloud Run service for a portfolio demo.
  - Guardrails: `max_instances=1` and scale-to-zero.

- `prod_private_iam.tfvars`
  - Private IAM-only Cloud Run service (recommended production posture).
  - Still scale-to-zero + max instance caps.

> Note: These profiles intentionally do **not** provision a database.
> Set `DATABASE_URL` and `ADMIN_API_KEY` via Secret Manager (see `docs/DEPLOY_GCP.md`).
