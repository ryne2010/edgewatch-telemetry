# Task 13 (Epic) — LTE data SIM connectivity + cost hygiene

🟡 **Status: Planned (decomposed into smaller Codex tasks)**

## Intent

Make EdgeWatch "field realistic" by supporting internet connectivity via a **data SIM**.

This includes:

- recommended modem hardware options (HAT vs USB vs external router)
- Raspberry Pi OS setup guidance
- a simple network watchdog and telemetry for link quality
- cost-aware policies for media + telemetry

## Implementation plan (Codex-friendly slices)

1) Docs + bring-up steps → `13a-cellular-runbook.md`
2) Agent cellular metrics + link watchdog → `13b-agent-cellular-metrics-watchdog.md` (implemented)
3) Edge policy cost caps + enforcement → `13c-cost-caps-policy.md`

## Non-goals

- Carrier-specific automation beyond basic APN setup.
- VPN overlay networks (nice-to-have; out of scope).

## Acceptance criteria (epic-level)

### Docs

- `docs/HARDWARE.md` includes LTE modem recommendations.
- Runbook exists: `docs/RUNBOOKS/CELLULAR.md` covering:
  - SIM/APN configuration
  - ModemManager basics
  - troubleshooting "no network" in the field
  - verifying signal metrics

### Telemetry

- Agent continues to report `signal_rssi_dbm`.
- Optional additional metrics supported:
  - RSRP/RSRQ/SINR
  - daily bytes sent/received

### Cost hygiene

- Edge policy can cap:
  - snapshot frequency
  - max media uploads per day
  - max bytes per day
- Agent enforces caps and emits an audit trail.

## Validation plan

```bash
make fmt
make lint
make typecheck
make test
```
