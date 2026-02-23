# Team workflow

This doc standardizes the "happy path" for local development and the optional GCP demo lane.

## Local development

```bash
make doctor
make hygiene
make up
```

If you update the schema:

```bash
make db-migrate
```

## Onboarding (GCP deploy lane)

Recommended first steps for a teammate deploying the Cloud Run demo:

```bash
make init GCLOUD_CONFIG=edgewatch-demo PROJECT_ID=YOUR_PROJECT_ID REGION=us-central1
make auth          # only needed once per machine/user
make doctor-gcp

# one-time per project (or whenever secrets rotate)
make db-secret
make admin-secret

# recommended: centralize Terraform backend/vars per environment
make tf-config-print-gcp ENV=dev
make tf-config-pull-gcp ENV=dev

# Public demo posture (dev)
make deploy-gcp-demo TF_BACKEND_HCL=backend.hcl

# Or: production posture (private IAM)
# make tf-config-pull-gcp ENV=prod
# make deploy-gcp-prod TF_BACKEND_HCL=backend.hcl
```

Notes:
- `make init` writes to your active gcloud configuration; if you use `GCLOUD_CONFIG=...` it will create/activate a dedicated config.
- If you changed gcloud configs during `make init`, run your next Make command in a fresh invocation.

---

## Defaults + overrides

Most deploy values default from `gcloud config`.
Override explicitly for CI or multi-project work:

```bash
make deploy-gcp PROJECT_ID=my-proj REGION=us-central1 TAG=v1
```

## Remote state

Terraform uses a GCS backend. The Makefile creates the bucket automatically:

```bash
make bootstrap-state-gcp
```

For team environments, keep `backend.hcl` + `terraform.tfvars` in GCS and sync
them with:

```bash
make tf-config-pull-gcp ENV=dev
make tf-config-push-gcp ENV=dev
```

## Scheduled jobs (Cloud Scheduler -> Cloud Run Jobs)

The Terraform demo stack can create:
- Cloud Run Job: `edgewatch-offline-check-<env>`
- Cloud Scheduler cron trigger

This avoids duplicated offline checks when Cloud Run scales.

---

## Team IAM (Google Groups)

This repo can optionally apply a Google Groups IAM starter pack from Terraform.

Use:
- `WORKSPACE_DOMAIN=yourdomain.com` to enable
- `GROUP_PREFIX=edgewatch` to control group email names

See `docs/IAM_STARTER_PACK.md`.

## CI (recommended)

Use Workload Identity Federation (no service account keys) and require plan output review for IaC changes.

Recommended workflow sequence:

1. `Terraform plan (GCP)` workflow
2. `Terraform apply (GCP)` workflow
3. `Deploy to GCP (Cloud Run)` workflow

## Dependency lockfiles

Generate and commit:
- `uv.lock`
- `pnpm-lock.yaml`

This repo ships a portable `uv.lock` (PyPI/pythonhosted URLs).

If you change dependencies, regenerate lockfiles on your machine.

```bash
make lock
```
