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

1) Sensors framework + real sensors
   - `docs/TASKS/11a-agent-sensor-framework.md`
   - `docs/TASKS/11b-rpi-i2c-temp-humidity.md`
   - `docs/TASKS/11c-rpi-adc-pressures-levels.md`
   - `docs/TASKS/11d-derived-oil-life-reset.md`

2) Camera lane
   - `docs/TASKS/12a-agent-camera-capture-ring-buffer.md`
   - `docs/TASKS/12b-api-media-metadata-storage.md`
   - `docs/TASKS/12c-web-media-gallery.md`

3) Cellular + cost hygiene
   - `docs/TASKS/13a-cellular-runbook.md`
   - `docs/TASKS/13b-agent-cellular-metrics-watchdog.md`
   - `docs/TASKS/13c-cost-caps-policy.md`

4) UI/UX polish (ongoing)
   - `docs/TASKS/14-ui-ux-polish.md`

If you want the fastest path to “enterprise operator posture”:

- Ingest perimeter hardening
  - `docs/TASKS/20-edge-protection-cloud-armor.md`

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
