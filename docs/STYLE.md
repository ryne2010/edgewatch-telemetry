# STYLE.md

This repo prefers **boring, legible engineering** with mechanical validation.

## General

- Prefer small files and cohesive diffs.
- Encode decisions in `docs/` (not chat).
- Do not log secrets (tokens, admin keys, DATABASE_URL).

## Python

- Formatting/linting: **ruff** (`python scripts/harness.py lint`)
- Typechecking: **pyright** (`python scripts/harness.py typecheck`)
- Testing: **pytest** (`python scripts/harness.py test`)

Guidelines:
- Use timezone-aware datetimes in persisted models.
- Keep routes thin; put logic in `services/`.
- Prefer explicit names over cleverness.
- When adding new config, extend `api/app/config.py` and document it.

## TypeScript / UI

- Keep UI read-only and ops-focused.
- Prefer explicit query state handling (TanStack Query).
- Keep the UI build green; add `typecheck` and run it in CI.

## Terraform

- Keep changes modular; reuse `infra/gcp/modules/*`.
- Never commit service account keys; prefer WIF.
- Run `make tf-check` before merging infra changes.

## Documentation

- If behavior changes, update:
  - `README.md` (if user-facing)
  - `docs/*` (contracts/design)
  - runbooks (if operational)

## Git hygiene

- Commit messages should explain **what** and **why**.
- Prefer PRs that can be reviewed in <15 minutes.
