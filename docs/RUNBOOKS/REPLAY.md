# Replay / Backfill Runbook

## Purpose

Replay historical telemetry from the edge buffer without creating duplicate telemetry rows.

Idempotency remains enforced by the server-side dedupe key `(device_id, message_id)` (`telemetry_ingest_dedupe`).

## Prerequisites

- Local buffer SQLite exists (default: `./edgewatch_buffer.sqlite`)
- Device token still valid
- API reachable

## Dry-run

```bash
uv run python -m agent.replay \
  --since 2026-01-01T00:00:00Z \
  --until 2026-01-02T00:00:00Z \
  --dry-run
```

## Replay execution

```bash
uv run python -m agent.replay \
  --since 2026-01-01T00:00:00Z \
  --until 2026-01-02T00:00:00Z \
  --batch-size 100 \
  --rate-limit-rps 2
```

## Verification

- Confirm ingest lineage entries exist:

```bash
curl -s -H "X-Admin-Key: dev-admin-key" \
  http://localhost:8082/api/v1/admin/ingestions | jq
```

Replay batches are tagged with `source="replay"`.

- Confirm duplicates are non-destructive by replaying the same range again.

## Operational guardrails

- Prefer lower `--rate-limit-rps` when DB is under load.
- Use narrow time windows for incremental backfill.
- Keep replay authenticated with the original device token (no admin override path by default).
