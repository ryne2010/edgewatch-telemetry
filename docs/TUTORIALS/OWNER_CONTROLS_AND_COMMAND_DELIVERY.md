# Tutorial: Owner Controls and Durable Command Delivery

This tutorial explains how mute/sleep/disable controls propagate reliably to intermittently connected devices.

## Control semantics

- `PATCH /api/v1/devices/{device_id}/controls/alerts`
  - mutes notifications only; alerts still open/resolve.
- `PATCH /api/v1/devices/{device_id}/controls/operation`
  - `active`: normal cadence
  - `sleep`: long cadence (default 7 days)
  - `disabled`: logical latch requiring local restart (owner/operator path)
- `POST /api/v1/admin/devices/{device_id}/controls/shutdown` (admin only)
  - queues one-shot `disabled + shutdown_requested`
  - device executes OS shutdown only when `EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=1`

## Durable command queue behavior

1. Every control write updates `devices` state and enqueues a `device_control_commands` row.
2. Older pending commands are marked `superseded`.
3. Commands have a default TTL of 180 days.
4. `GET /api/v1/device-policy` includes the latest pending command (if unexpired).
5. Device applies command once and calls:
   - `POST /api/v1/device-commands/{command_id}/ack`
6. Pending command payload may include:
   - `shutdown_requested`
   - `shutdown_grace_s`

## Operational checks

1. Use `GET /api/v1/devices/{device_id}/controls` and confirm:
   - `pending_command_count`
   - `latest_pending_command_expires_at`
   - `latest_pending_shutdown_requested` (for admin shutdown flow)
2. Confirm policy ETag changes when a new command is queued.
3. Confirm pending count returns to zero after device ack.

## Failure modes

- Device offline: command remains pending until next policy fetch.
- Ack fails: agent keeps local pending-ack state and retries.
- Command expires: server marks it expired; device ignores stale command payloads.
- Shutdown guard off: shutdown intent degrades to logical disable and is still acknowledged.
