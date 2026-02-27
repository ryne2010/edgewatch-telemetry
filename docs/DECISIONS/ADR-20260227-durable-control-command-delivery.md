# ADR: Durable Device Control Command Delivery

Date: 2026-02-27
Status: Accepted

## Context

Device control updates (mute/sleep/disable) must remain reliable for intermittently connected Raspberry Pi nodes.
Direct write-through to device state alone is insufficient because devices may be offline for long windows
(including seasonal sleep). We need eventual control delivery with bounded retention and idempotent device apply.

## Decision

Adopt a durable per-device command queue:

- Persist control snapshots in `device_control_commands`.
- Mark older pending commands as `superseded` when a newer command is enqueued.
- Default command TTL is 180 days (`control_command_ttl_s=15552000`).
- Include latest pending command in `GET /api/v1/device-policy`.
- Include pending-command state in policy ETag derivation.
- Devices apply each command once (tracked in durable local command state) and ack with:
  - `POST /api/v1/device-commands/{command_id}/ack`
- Support hybrid disable semantics via command payload fields:
  - `shutdown_requested` (default false)
  - `shutdown_grace_s` (default 30)
- Add admin-only enqueue API for shutdown intent:
  - `POST /api/v1/admin/devices/{device_id}/controls/shutdown`
  - command still sets `operation_mode=disabled`
  - OS shutdown executes only when device local guard `EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=1`

## Consequences

- Positive:
  - Reliable eventual delivery for offline/sleep devices.
  - Clear lifecycle visibility (`pending`, `superseded`, `expired`, `acknowledged`).
  - Backward-compatible additive API/device-policy change.
  - Safety posture preserved: remote power-off is explicit, role-gated, and device-opt-in.
- Tradeoffs:
  - New DB table and state transitions to maintain.
  - Additional agent-side local durability and retry behavior.
  - Shutdown behavior now depends on local runtime guard configuration discipline.
- Operational impact:
  - Operators can inspect pending counts/expiry in controls UI/API.
  - Device restart no longer loses command-apply/ack intent.
  - Admins can perform one-shot shutdown only for explicitly opted-in devices.

## Alternatives considered

- Policy-only immediate writes without command queue:
  - Rejected; no durable per-change lineage and weaker delayed-delivery guarantees.
- Realtime push channel (MQTT/WebSocket) only:
  - Rejected for v1 complexity and operational overhead in intermittent rural links.

## Rollout / migration plan

1. Apply DB migration (`0013_device_control_commands`).
2. Deploy API with queue enqueue + policy delivery + ack endpoint.
3. Deploy web updates for pending command visibility.
4. Deploy agent updates for apply-once + ack retry.
5. Monitor command queue depth and expiry rates during pilot.

Rollback:
- API can ignore pending-command payload without breaking existing agents.
- Queue writes can be disabled by reverting control route enqueue behavior.

## Validation

- Unit tests cover:
  - enqueue + supersede behavior
  - policy pending-command serialization and ETag variation
  - ack endpoint idempotency
  - agent apply-once persistence and ack retry logic
- Harness validation:
  - `python scripts/harness.py lint`
  - `python scripts/harness.py typecheck`
  - `python scripts/harness.py test`
