# Task 13c — Cost caps in edge policy (bytes/day, snapshots/day)

✅ **Status: Implemented (2026-02-21)**

## Objective

Make cellular usage predictable and safe by enforcing **cost caps** from the edge policy contract.

This task spans:

- edge policy contract extension
- agent enforcement + audit telemetry

## Scope

### In-scope

- Extend `contracts/edge_policy/v1.yaml` with a `cost_caps` section, e.g.:

```yaml
cost_caps:
  max_bytes_per_day: 50000000
  max_snapshots_per_day: 48
  max_media_uploads_per_day: 48
```

- Add agent enforcement:
  - maintain a local daily counter file (UTC day) for bytes + uploads
  - when cap exceeded:
    - skip media uploads
    - optionally reduce telemetry cadence to heartbeat-only
  - emit audit metrics/logs:
    - `cost_cap_active=true`
    - `bytes_sent_today`, `media_uploads_today`

- Update policy endpoint and caching behavior if needed.

### Out-of-scope

- Carrier billing integration.

## Design notes

- Ensure counters are durable and not reset by reboot.
- Keep the enforcement behavior simple and explicit.

## Acceptance criteria

- Caps can be configured via edge policy.
- Agent enforces caps consistently across restarts.
- When caps are hit:
  - uploads are skipped
  - a clear audit trail exists in telemetry/logs

## Deliverables

- Contract update + tests
- Agent cost cap module + tests
- Docs:
  - `docs/COST_HYGIENE.md` updated
  - `docs/RUNBOOKS/CELLULAR.md` updated

## Validation

```bash
make fmt
make lint
make typecheck
make test
```
