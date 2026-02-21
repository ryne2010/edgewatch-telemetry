# Task 14 — UI/UX polish (production-grade operator dashboard)

🟡 **Status: In progress (core UX shipped; only IAP posture polish remains after Task 18)**

## Intent

Upgrade the web UI from "minimal demo" to a **production-grade** operator dashboard with:

- fast at-a-glance status
- easy metric exploration (contract-driven)
- clear alert timelines + routing visibility
- clean empty states, loading states, and error recovery

This task is intentionally ongoing: the UI is the first thing users judge.

## Non-goals

- Replacing the backend stack.
- Pixel-perfect polish ahead of information architecture.

## What is already implemented

### App shell + navigation

- Desktop sidebar + mobile drawer
- Theme toggle
- Consistent layout + page titles

### Capability-aware UI

The UI reads `/api/v1/health` feature flags and:

- hides Admin navigation when admin routes are disabled
- hides Docs navigation when docs are disabled
- adapts when `ADMIN_AUTH_MODE=none`

### Core pages

- Dashboard (fleet status)
- Devices list + device detail
- Alerts list with pagination
- Contracts view (telemetry + edge policy)
- Settings (theme + optional admin key)
- System/meta page

### Device detail

- Overview tab (heartbeat + latest telemetry)
- Telemetry explorer tab (metric picker + chart)
- Admin/audit lanes when enabled

## Remaining work (next iteration)

### Devices list

- ✅ clearer status explanations (offline vs stale vs weak signal)
- ✅ better empty state guidance
- ✅ quick filters:
  - online/offline
  - open alerts only

### Device detail

- ✅ Multi-metric “small multiples” view for key metrics.
- ✅ Oil life gauge (after Task 11d ships).

### Alerts

- ✅ Timeline grouping and filters by:
  - device
  - type
  - severity
- ✅ Show routing decisions (dedupe/throttle/quiet hours) as an audit trail.

### Media

- This work is tracked separately:
  - `docs/TASKS/12c-web-media-gallery.md`

### IAP operator posture

- Once IAP lands (Task 18), improve the UX for operator login flows.

## Design notes

- Keep UI dependency surface area small.
- Avoid CDNs; keep the repo self-contained.
- Prefer “one request per view” patterns (batching) for responsiveness.

## Validation plan

```bash
pnpm -r --if-present build
pnpm -C web typecheck
make lint
make test
```
