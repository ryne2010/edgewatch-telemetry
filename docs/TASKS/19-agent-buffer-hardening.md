# Task 19 — Agent buffer hardening (WAL mode, disk quota, corruption recovery)

✅ **Status: Implemented**

## Objective

Make the edge agent’s store-and-forward buffer robust under real field conditions:

- frequent power loss
- intermittent connectivity
- constrained disk

This task strengthens the sqlite spool so the device can run unattended.

## Scope

### In-scope

- Enable sqlite WAL mode + sane pragmas (configurable):
  - `journal_mode=WAL`
  - `synchronous=NORMAL`
  - `temp_store=MEMORY`

- Add buffer disk quota enforcement:
  - max DB size in bytes
  - eviction policy: drop oldest buffered telemetry first
  - emit audit metric/log when evicting

- Add corruption recovery:
  - on sqlite errors indicating corruption:
    - move the DB aside with timestamp
    - recreate schema
    - continue operating (best effort)

- Add metrics:
  - `buffer_db_bytes`
  - `buffer_queue_depth`
  - `buffer_evictions_total`

### Out-of-scope

- Cross-device fleet OTA updates.

## Design notes

- Eviction should be explicit and observable (operators need to know data was dropped).
- Prefer small, testable helpers.

## Acceptance criteria

- Agent can run with a max buffer size and does not exceed it.
- Simulated “disk full” conditions degrade gracefully.
- Corruption recovery path is tested.

## Deliverables

- `agent/buffer.py` enhancements + tests
- `docs/RUNBOOKS/OFFLINE_CHECKS.md` updated with new diagnostics

## Validation

```bash
make fmt
make lint
make typecheck
make test
```
