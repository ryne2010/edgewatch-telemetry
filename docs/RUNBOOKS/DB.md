# DB Runbook

This runbook covers **schema migrations** and common operational DB tasks.

> This repo uses **Alembic** for schema evolution (see `migrations/`).

## Local development

### Bring up the stack

```bash
make up
```

`docker compose` will:
- start Postgres (`db`)
- run migrations (`migrate` one-off service)
- start the API (`api`)

### Apply migrations manually

If you changed migrations and want to re-apply locally:

```bash
make db-migrate
```

### Create a new migration

After changing SQLAlchemy models:

```bash
make db-revision msg="add_new_table"
```

Then:
- review the generated file in `migrations/versions/`
- run it locally:

```bash
make db-migrate
```

## GCP / Cloud Run

### Recommended production pattern

- Deploy the Cloud Run service.
- Run migrations as a **separate Cloud Run Job**.
- Only then, roll traffic / scale up.

This repo’s Terraform demo stack can create a job named:

- `edgewatch-migrate-<env>`

### Run migrations (Make)

```bash
make migrate-gcp ENV=dev
```

### Run migrations (gcloud)

```bash
gcloud run jobs execute "edgewatch-migrate-dev" --region "us-central1" --wait
```

### Rollback

Schema rollbacks are risky.

If you must roll back a migration in a dev sandbox:

```bash
uv run alembic downgrade -1
```

For production:
- prefer application-level rollbacks (feature flags / compatibility shims)
- use DB backups / PITR instead of downgrading migrations

## Operational gotchas

- **Backward compatibility:** deploy app code that can tolerate both schemas during rollouts.
- **Locking:** this repo uses a Postgres advisory lock for auto-migrations to prevent concurrent runs.
- **Secrets:** `DATABASE_URL` is stored in Secret Manager in the Terraform demo.
