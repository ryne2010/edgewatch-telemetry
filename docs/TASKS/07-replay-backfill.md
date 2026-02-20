# Task: Replay / backfill tooling (agent-side + server-side)

## Intent

Add a repeatable way to **replay** historical telemetry into EdgeWatch to support:

- correctness fixes (reprocessing after a bug)
- demos (load a realistic history)
- operational recovery (edge devices that were offline for long periods)

This aligns with the portfolio theme: *idempotency + recoverability + operational runbooks*.

## Non-goals

- Building a full ETL system.
- Real-time stream processing.
- Large-scale bulk backfills (BigQuery is a better fit for that).

## Acceptance criteria

- There is a documented workflow to backfill telemetry for a device/time range.
- Replay is **idempotent**:
  - repeated replays do not create duplicate telemetry points
  - existing `message_id` de-dupe semantics remain the primary mechanism
- At least one replay entrypoint exists:
  - **Agent-side**: CLI to resend buffered history from local SQLite
  - **Server-side** (optional): admin-only endpoint to import a JSONL/CSV dump
- Replay events are visible in the lineage/audit trail (see `04-lineage-artifacts.md`).

## Design notes

### Agent-side replay

Add a simulator/agent CLI that can:

- select points from local buffer by time range
- batch them into `POST /api/v1/ingest` requests
- include stable `message_id` values so de-dupe works

Suggested interface:

```bash
uv run python -m agent.replay \
  --device-id dev-001 \
  --since 2026-01-01T00:00:00Z \
  --until 2026-01-02T00:00:00Z
```

### Server-side replay (optional)

- Add an admin-only endpoint:
  - `POST /api/v1/admin/replay`
- Input:
  - NDJSON or JSON array
  - device_id + points

### Guardrails

- Enforce max rows per replay request.
- Require admin auth.
- Make replay explicitly opt-in (do not expose it publicly).

## Validation

```bash
make lint
make typecheck
make test
```
