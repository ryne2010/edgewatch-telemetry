# Codex handoff guide

This repo is intentionally set up to be **Codex-friendly**:

- larger work is specced in `docs/TASKS/`
- repo-quality gates are centralized in `scripts/harness.py` + `harness.toml`
- agent roles/checklists live under `agents/`

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

## Where the task specs live

- **Task queue** (status + ordering): `docs/TASKS/README.md`
- **Roadmap** (milestones + why): `docs/ROADMAP.md`
- Durable sources of truth (read before doing architecture work):
  - `docs/DOMAIN.md`
  - `docs/DESIGN.md`
  - `docs/CONTRACTS.md`
  - `docs/WORKFLOW.md`

## Recommended execution order (remaining work)

If you want the fastest path to “real field node”:

1) Camera epic closeout
   - `docs/TASKS/12-camera-capture-upload.md`
   - Note: slices `12a`, `12b`, `12c` are already implemented; this is queue/status closeout.

If you want the fastest path to “enterprise operator posture”:

- Enterprise operator posture queue is complete (`19` and `20` implemented).

## Working agreements

- Keep `api/app/routes/*` thin; business logic in `api/app/services/*`.
- When changing public API behavior or a non-negotiable invariant, write an ADR under `docs/DECISIONS/`.
- Add unit tests for deterministic behavior (fixed timestamps, deterministic IDs).
- Never log secrets (device tokens, admin keys, DATABASE_URL, Secret Manager payloads).

## Suggested parallel workstreams

These can be developed in parallel if PRs are rebased/merged carefully:

- Stream A (sensors): `11a` → `11b` / `11c` → `11d`
- Stream B (media): `12a` (device) in parallel with `12b` (API) until the upload handshake needs integration
- Stream C (cellular): `13a` docs can be written anytime; `13b` agent + `13c` policy changes should be coordinated
- Stream D (platform): edge buffer hardening (`19`) + ingest perimeter hardening (`20`)

## Deployment lanes

- Cloud Run deploy: `docs/DEPLOY_GCP.md`
- Raspberry Pi deploy: `docs/DEPLOY_RPI.md`
- Multi-arch image publishing: `docs/MULTIARCH_IMAGES.md`

Safe deploy shortcut:

```bash
make deploy-gcp-safe ENV=dev
```
