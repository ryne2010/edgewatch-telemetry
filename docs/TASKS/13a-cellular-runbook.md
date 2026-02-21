# Task 13a — Cellular runbook (LTE modem + SIM bring-up)

🟢 **Status: Implemented (2026-02-21)**

## Objective

Provide a **field-ready** runbook for connecting an RPi edge node via a data SIM.

This task is documentation-first and should be executable by a technician/operator.

## Scope

### In-scope

- Create/update:
  - `docs/RUNBOOKS/CELLULAR.md`
- Cover:
  - hardware options (USB modem vs HAT vs external router)
  - SIM + APN configuration
  - ModemManager / NetworkManager basics
  - troubleshooting checklist:
    - power
    - SIM detection
    - APN
    - registration
    - signal strength
    - DNS and egress

- Add a short “field checklist” section:
  - how to validate link before leaving site

### Out-of-scope

- Carrier-specific automation.

## Acceptance criteria

- A tech can follow the runbook to bring up LTE on a fresh Pi install.
- A "common failures" section exists with concrete commands and what outputs to expect.

## Deliverables

- `docs/RUNBOOKS/CELLULAR.md`
- Updates to `docs/HARDWARE.md` (LTE recommendations)

## Validation

- N/A (docs)
