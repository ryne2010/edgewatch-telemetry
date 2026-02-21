# Task 13b — Agent cellular metrics + link watchdog

✅ **Status: Implemented (2026-02-21)**

## Objective

Add cellular link observability to the edge agent so operations can diagnose field issues.

## Scope

### In-scope

- Add optional cellular metrics collection behind `CELLULAR_METRICS_ENABLED=true`:
  - RSSI (already exists)
  - optionally: RSRP/RSRQ/SINR (if available)
  - network registration state
  - daily bytes sent/received (best effort)

- Add a lightweight link watchdog:
  - periodically perform a cheap connectivity check (DNS + HTTP HEAD)
  - emit `link_ok` boolean and `link_last_ok_at`
  - do **not** aggressively restart networking (observe/alert first)

### Out-of-scope

- Owning NetworkManager configuration.

## Design notes

- Prefer reading metrics via ModemManager (`mmcli`) or DBus.
- Keep imports optional so CI/dev doesn’t require modem tooling.

## Acceptance criteria

- On non-Pi machines, agent still runs.
- When enabled on a Pi with ModemManager:
  - metrics appear in telemetry
  - watchdog reports link status

## Deliverables

- `agent/cellular.py` or `agent/metrics/cellular.py`
- docs updates:
  - `docs/RUNBOOKS/CELLULAR.md` includes how to verify telemetry is reporting cellular metrics

## Validation

```bash
make fmt
make lint
make typecheck
make test
```
