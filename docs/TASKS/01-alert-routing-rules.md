# Task: Alert routing rules (quiet hours, dedupe, throttling)

## Intent

Add configurable alert routing rules so that alerts are actionable and do not spam operators.
This is part of the "ops-ready" story described in the portfolio materials.

## Non-goals

- Building a full notification SaaS.
- Multi-tenant rule management.

## Acceptance criteria

- A new routing layer exists that is applied to *all* alert creation paths.
- Rules support, at minimum:
  - **dedupe window** (do not re-notify the same alert type/device within N minutes)
  - **throttling** (max notifications per device per time window)
  - **quiet hours** (do not deliver notifications during configured window; still record the alert)
- Routing decisions are auditable (stored as structured data or logs without secrets).
- Unit tests cover core routing behavior (deterministic timestamps).

## Design notes

- Keep `api/app/routes/*` thin; routing logic belongs under `api/app/services/`.
- Consider a small interface:
  - `AlertRouter.should_notify(alert: AlertCandidate, now: datetime) -> RoutingDecision`
  - `NotificationService.deliver(decision, alert)`

### Data model

Option A (DB-backed):
- Add table `alert_policies` keyed by `device_id` (or global default).
- Add table `notification_events` storing delivery attempts + decisions.

Option B (config-backed):
- Store rules in env/config for demo simplicity.

Prefer A if demonstrating "auditability".

## Implementation sketch

1) Add `api/app/services/routing.py` with pure routing logic.
2) Add persistence model if choosing DB-backed approach.
3) Update existing alert creation call sites:
   - offline monitor
   - threshold alerts
4) Add one delivery adapter (log-only) as baseline.

## Validation

```bash
make lint
make typecheck
make test
```
