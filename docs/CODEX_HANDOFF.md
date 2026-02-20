# Codex handoff guide

This repo is intentionally set up to be **Codex-friendly**: larger work is specced in `docs/TASKS/`,
and repo-quality gates are centralized in `scripts/harness.py` + `harness.toml`.

## Quick start (local)

```bash
make doctor-dev
make db-up
make api-dev
make web-install
make web-dev
```

## Repo-quality gates (run before/after each task)

```bash
# Full gate (preferred)
make harness

# Faster inner-loop variants
python scripts/harness.py lint --only python
python scripts/harness.py test --only python
python scripts/harness.py lint --only node
```

## Task queue

- Planned / remaining: see `docs/TASKS/README.md`
- Each task spec includes: intent, non-goals, acceptance criteria, design notes, validation plan.

## Working agreements

- Keep `api/app/routes/*` thin; business logic in `api/app/services/*`.
- When changing public API behavior or a non-negotiable invariant, write an ADR under `docs/DECISIONS/`.
- Add unit tests for deterministic behavior (use fixed timestamps, deterministic IDs).
- Never log secrets (device tokens, admin keys, DATABASE_URL, Secret Manager payloads).

## Suggested parallel workstreams

These tasks can be developed in parallel if PRs are rebased/merged carefully.

- Stream A (alerts): `01-alert-routing-rules.md` + `02-notification-adapters.md`
- Stream B (contracts/lineage): finish `03-telemetry-contracts.md` + implement `04-lineage-artifacts.md`
- Stream C (pipelines): `07-replay-backfill.md` + `09-event-driven-ingest-pubsub.md` + `10-analytics-export-bigquery.md`

## CI/CD / GCP deploy lane

- GitHub Actions + Workload Identity Federation: `docs/WIF_GITHUB_ACTIONS.md`
- Cloud Run demo/prod Terraform: `infra/gcp/cloud_run_demo/`
- Safe deploy shortcut:

```bash
make deploy-gcp-safe ENV=dev
```
