# Team workflow

## Onboarding (GCP deploy lane)

Recommended first steps for a teammate deploying the Cloud Run demo:

```bash
make init GCLOUD_CONFIG=personal-portfolio PROJECT_ID=YOUR_PROJECT_ID REGION=us-central1
make auth          # only needed once per machine/user
make doctor-gcp
make deploy-gcp
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

## Team IAM (Google Groups)

This repo can optionally apply a Google Groups IAM starter pack from Terraform.

Use: 
- `WORKSPACE_DOMAIN=yourdomain.com` to enable
- `GROUP_PREFIX=edgewatch` to control group email names

See `docs/IAM_STARTER_PACK.md`.

## CI (recommended)

Use Workload Identity Federation (no service account keys) and require plan output review for IaC changes.

## Dependency lockfiles

Generate and commit:
- `uv.lock`
- `pnpm-lock.yaml`

```bash
make lock
```
