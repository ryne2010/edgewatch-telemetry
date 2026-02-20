# Release runbook

This runbook is for releasing EdgeWatch to GCP (Cloud Run) in a controlled way.

## Preconditions

- `main` is green in GitHub Actions (`CI` workflow)
- You’ve updated:
  - `pyproject.toml` version
  - `CHANGELOG.md`
- Any DB migrations are reviewed and rehearsed

## Local pre-release checklist

```bash
make clean
make harness
make tf-check
```

## Release options

### Option A: GitHub Actions (recommended)

1) Push your changes to `main`.

2) Run:
- **Deploy to GCP (Cloud Run)** (`.github/workflows/deploy-gcp.yml`)
  - choose `env` (e.g., `dev` or `prod`)
  - optionally choose a `.tfvars` profile

This runs `make deploy-gcp-safe`, which:
1) builds & pushes the API image
2) applies Terraform
3) runs migrations as a Cloud Run Job
4) verifies the service is healthy

### Option B: Local CLI (advanced)

```bash
# Auth
make login-gcp PROJECT_ID=... REGION=...

# Deploy safely
make deploy-gcp-safe PROJECT_ID=... REGION=... ENV=dev
```

## Rollback

### Cloud Run (fastest)

- Roll back to a previous Cloud Run revision in the Cloud Run UI, or via:

```bash
gcloud run services update-traffic edgewatch-<env> --to-revisions=<REVISION_NAME>=100
```

### Database migrations

- Prefer **forward fixes** (new migration) over manual rollback.
- If you must roll back a migration, ensure you understand the data integrity impact.

## Post-release verification

- UI loads and charts render
- `/healthz` returns 200
- New ingest points are being written
- Alerting loop is healthy (no runaway alert spam)

## Packaging a release artifact

```bash
make dist
```

A clean zip is written under `./dist/`.
