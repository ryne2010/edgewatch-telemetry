# AGENTS.md

## Start here

1) Read **`harness.toml`** to learn how to validate changes.

2) Read the durable source of truth (in order):
- `docs/DOMAIN.md` — what EdgeWatch is, vocabulary, invariants
- `docs/DESIGN.md` — architecture, layering, allowed dependencies
- `docs/CONTRACTS.md` — API + behavioral guarantees
- `docs/WORKFLOW.md` — the standard execution loop

3) Use the harness before finalizing work:

```bash
python scripts/harness.py lint
python scripts/harness.py typecheck
python scripts/harness.py test
```

4) For local ops + demos, use the Makefile:

```bash
make doctor
make up
make demo-device
make simulate
```

## Repo map

- `api/` — FastAPI service (ingest + device status + alerts + timeseries)
  - `api/app/routes/` — HTTP boundary (request/response validation)
  - `api/app/services/` — business logic (monitoring, alert logic)
  - `api/app/models.py` — persistence model (SQLAlchemy)
- `agent/` — edge agent (local buffering, sensor read loop, flush)
- `web/` — small dashboard UI (Vite + React)
- `infra/gcp/` — Terraform (Cloud Run demo, Secret Manager, observability-as-code)
- `docs/` — specs, runbooks, and decision records

## Non-negotiables (contracts)

- **Idempotent ingest:** duplicates must not create duplicate telemetry rows (dedupe by `(device_id, message_id)`).
- **UTC timestamps:** persisted timestamps are treated as UTC; normalize naive timestamps.
- **No plaintext device tokens at rest:** server stores only a strong hash (PBKDF2) + fingerprint for lookup.
- **No secrets in logs:** logs must not leak tokens, admin keys, or DATABASE_URL.
- **Local-first stays runnable:** the Docker Compose lane must remain the default dev path.

If you need to change any of these, write an ADR (`docs/DECISIONS/`) and update `docs/CONTRACTS.md`.

## Escalate to a human when

- Requirements conflict with the contracts above.
- A change affects public API behavior (compatibility) or auth/security model.
- A change modifies Terraform modules or security posture.
- Validation cannot be made green without weakening a gate.

## Output format

Use `agents/checklists/CHANGE_SUMMARY.md` to summarize:
- what changed
- why it changed
- how it was validated
- risks/rollout notes
- follow-ups / tech debt
