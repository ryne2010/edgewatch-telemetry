# Tutorial: Edge policy + device-side optimization

EdgeWatch is designed for **field devices** where bandwidth and battery matter.

The agent uses a policy endpoint (`/api/v1/device-policy`) to pull:

- send cadence (sampling, heartbeat, alert snapshots)
- delta thresholds
- alert thresholds
- buffering limits and backoff

## What the agent optimizes

The edge agent minimizes cost (data + energy) by:

- **Sampling at a steady interval** (`sample_interval_s`) when the device is healthy.
- **Only increasing sampling** for *critical* alerts (currently: low water pressure).
- **Only sending full snapshots when needed**:
  - once at startup (bootstrap)
  - on alert transitions (entry/exit)
  - periodically while in a critical alert state
- **Sending heartbeats** only after a period of silence (any point proves liveness).
- **Sending deltas** when metrics change beyond thresholds.
- **Buffering locally** when offline (sqlite queue), then flushing when connectivity returns.

## Alert state & hysteresis

The agent maintains a coarse `device_state` metric:

- `OK` — no active alerts
- `WARN` — one or more active alerts

Alerts are evaluated with **per-alert hysteresis**, meaning each alert has an independent
“enter” and “recover” threshold. This prevents a subtle bug where one active alert
(e.g., battery low) could incorrectly influence hysteresis for a different alert
(e.g., water pressure).

## When the agent sends telemetry

In priority order:

0. **Startup snapshot (once)**
   - On boot, the agent sends a full snapshot (`startup`) to establish a baseline.

1. **Alert transition (immediate)**
   - Any alert entering or exiting triggers an immediate full snapshot.
   - The log reason is `state_change` (OK↔WARN) or `alert_change` (WARN↔WARN but alert set changed).

2. **Alert snapshot (periodic, critical-only)**
   - While the *critical* alert is active (water pressure low), the agent sends a full snapshot every
     `alert_report_interval_s`.

3. **Heartbeat (silence-based)**
   - If the agent hasn’t recorded *any* point for `heartbeat_interval_s`, it sends a minimal heartbeat
     (battery/signal/water/pump) to prove liveness.

4. **Delta**
   - If any metric changes beyond its configured delta threshold, the agent sends only the changed keys.

## Where policy comes from

### Server-side

The API loads a YAML policy from `contracts/edge_policy/` and merges in per-device tuning fields
stored in the database (like `heartbeat_interval_s`).

### Device-side

The agent caches policy locally using:

- `ETag` and `If-None-Match`
- `Cache-Control: max-age=<seconds>`

If the policy endpoint is unreachable, the agent falls back to a conservative default policy.

## How to change policy

- Change the YAML file under `contracts/edge_policy/` (or add a new version file)
- Set `EDGE_POLICY_VERSION` in the API environment
- Restart the API

For local dev, see `docs/DEV_MAC.md`.
