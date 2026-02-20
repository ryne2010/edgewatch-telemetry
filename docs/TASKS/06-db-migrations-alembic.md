# Task: Database migrations (Alembic)

✅ **Status: Implemented** (2026-02-19)

## What changed

- Added **Alembic** (`alembic.ini`, `migrations/`, initial revision `0001_initial`).
- Local stack now runs migrations via `docker-compose.yml` **`migrate`** service.
- Added Make targets:
  - `make db-migrate`
  - `make db-revision msg="..."`
- Added a production-safe **migration job** pattern for GCP:
  - Cloud Run Job: `edgewatch-migrate-<env>`
  - Make shortcut: `make migrate-gcp ENV=<env>`
- App startup supports `AUTO_MIGRATE=1` (dev convenience) with a Postgres advisory lock.

## Docs

- Runbook: `docs/RUNBOOKS/DB.md`

## Follow-ups (optional hardening)

- Add a DB creation module for Cloud SQL (Terraform) with private IP + connector.
- Add integration tests that spin up Postgres and validate migrations end-to-end.
