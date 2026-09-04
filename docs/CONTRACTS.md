# CONTRACTS.md

Contracts define **behavioral guarantees** and **compatibility rules**.
Treat these as non-negotiable unless explicitly changed via ADR.

## Public interfaces

### HTTP API (v1)

Base: `/api/v1`

- `POST /ingest` — device telemetry ingestion (Bearer token)
- `GET  /devices` — list devices + computed status
- `GET  /devices/summary` — fleet-friendly list (status + latest selected vitals)
- `GET  /fleets` — list accessible fleets
- `GET  /fleets/{fleet_id}/devices` — list accessible devices in a fleet
- `GET  /search` — unified operator search across devices, fleets, alerts, device events, procedure invocations, and deployments
- `GET  /event-stream` — server-sent operator event stream for alerts, device events, and procedure invocations
- `GET  /devices/{device_id}` — device detail + computed status
- `GET  /devices/{device_id}/telemetry` — raw telemetry points
- `GET  /devices/{device_id}/timeseries` — bucketed time series
- `GET  /devices/{device_id}/controls` — device operation + alert mute controls
- `GET  /devices/{device_id}/state` — latest reported device state/variables
- `GET  /devices/{device_id}/procedure-invocations` — recent procedure invocation history for a device
- `POST /devices/{device_id}/procedures/{definition_name}/invoke` — enqueue a typed remote procedure invocation
- `PATCH /devices/{device_id}/controls/operation` — set `active|sleep|disabled` + sleep interval + runtime power mode
- `PATCH /devices/{device_id}/controls/alerts` — set/clear alert notification mute window
- `POST /device-commands/{command_id}/ack` — device ack for durable control command delivery
- `POST /device-state/report` — device upsert of latest reported state/variables
- `POST /device-events` — device publish of append-only operational events
- `GET  /device-events` — list device events (fleet/device filtered)
- `POST /device-procedure-invocations/{invocation_id}/result` — device result callback for a pending procedure
- `POST /device-updates/{deployment_id}/report` — device update lifecycle report for OTA deployments
- `GET  /alerts` — recent alerts (`device_id`, `open_only`, `severity`, `alert_type`, `q` or legacy `search`, cursor, `limit`)
- `GET  /device-policy` — edge policy/config for devices (Bearer token; ETag cached)
- `GET  /contracts/telemetry` — active telemetry contract (public)
- `GET  /contracts/edge_policy` — active edge policy contract (public)
- `POST /media` — create media metadata + upload instructions (device auth)
- `PUT  /media/{media_id}/upload` — upload media bytes (device auth)
- `GET  /devices/{device_id}/media` — list recent uploaded media (device auth)
- `GET  /media/{media_id}` — media metadata detail (device auth)
- `GET  /media/{media_id}/download` — media bytes download (device auth; proxied or signed URL)
- `POST /admin/devices` — register device (admin surface; optional)
- `POST /admin/fleets` — create fleet (admin surface)
- `GET  /admin/fleets` — list fleets (admin surface)
- `PATCH /admin/fleets/{fleet_id}` — update fleet metadata/channel defaults (admin surface)
- `PUT  /admin/fleets/{fleet_id}/devices/{device_id}` — add device to fleet (admin surface)
- `DELETE /admin/fleets/{fleet_id}/devices/{device_id}` — remove device from fleet (admin surface)
- `GET  /admin/fleets/{fleet_id}/access` — list fleet access grants (admin surface)
- `PUT  /admin/fleets/{fleet_id}/access/{principal_email}` — create/update fleet access grant (admin surface)
- `DELETE /admin/fleets/{fleet_id}/access/{principal_email}` — remove fleet access grant (admin surface)
- `POST /admin/procedures/definitions` — create a typed device procedure definition (admin)
- `GET  /admin/procedures/definitions` — list device procedure definitions (admin)
- `PATCH /admin/procedures/definitions/{definition_id}` — update device procedure definitions (admin)
- `POST /admin/releases/manifests` — create signed release manifest metadata (admin)
- `GET  /admin/releases/manifests` — list release manifests (admin)
- `POST /admin/deployments` — create staged deployment (admin)
- `GET  /admin/deployments/{deployment_id}` — deployment detail (admin)
- `POST /admin/deployments/{deployment_id}/pause` — pause active deployment (admin)
- `POST /admin/deployments/{deployment_id}/resume` — resume paused deployment (admin)
- `POST /admin/deployments/{deployment_id}/abort` — abort deployment (admin)
- `POST /admin/devices/{device_id}/controls/shutdown` — admin-only one-shot shutdown intent enqueue
- `GET  /admin/devices/{device_id}/access` — list per-device access grants
- `PUT  /admin/devices/{device_id}/access/{principal_email}` — create/update per-device access grant
- `DELETE /admin/devices/{device_id}/access/{principal_email}` — remove per-device access grant
- `GET  /admin/ingestions` — ingestion lineage batches (admin surface; optional)
- `GET  /admin/drift-events` — drift audit events (admin surface; optional)
- `GET  /admin/notifications` — notification routing/delivery audit events (admin surface; optional)
- `GET  /admin/exports` — analytics export batch audit (admin surface; optional)
- `GET  /admin/events` — admin mutation audit events (actor attribution)
- `GET  /admin/notification-destinations` — list configured event delivery destinations (admin surface)
- `POST /admin/notification-destinations` — create event delivery destination (admin surface)
- `PATCH /admin/notification-destinations/{destination_id}` — update destination filters/config (admin surface)
- `DELETE /admin/notification-destinations/{destination_id}` — delete event delivery destination (admin surface)
- `GET  /admin/contracts/edge-policy/source` — active edge policy YAML source (admin surface)
- `PATCH /admin/contracts/edge-policy` — validate + persist active edge policy YAML (admin surface)


Admin surface controls:
- `ENABLE_ADMIN_ROUTES=0` removes `/api/v1/admin/*` entirely
- `ADMIN_AUTH_MODE=key|none` controls whether admin routes require `X-Admin-Key` or trust a perimeter
- Optional RBAC controls:
  - `AUTHZ_ENABLED=0|1`
  - `AUTHZ_*_EMAILS` role allowlists

Ownership controls:
- When `AUTHZ_ENABLED=1`, non-admin read/control endpoints require explicit per-device grants.
- Fleet-scoped grants can also authorize access to devices through fleet membership.
- Admin users bypass per-device grants for break-glass operations.

**Compatibility:**
- Endpoints under `/api/v1` are intended to be stable for the public demo.
- Breaking changes should:
  - require an ADR
  - bump the API version path (ex: `/api/v2`) or provide backward compatible behavior

### Infra endpoints

These are intentionally unversioned:
- `GET /health`
- `GET /readyz`

### Internal worker endpoint

- `POST /api/v1/internal/pubsub/push` — Pub/Sub push worker endpoint (enabled when `INGEST_PIPELINE_MODE=pubsub`)

### Device agent delivery modes

- `EDGEWATCH_TELEMETRY_TRANSPORT=api` is the default and preserves all canonical
  EdgeWatch API behavior.
- `EDGEWATCH_TELEMETRY_TRANSPORT=telegram` is exclusive: the agent must not call
  EdgeWatch policy, ingest, command, procedure, update, or media endpoints.
- Telegram mode uses local fallback-policy configuration and sends complete
  telemetry envelopes, including stable `message_id` values, either as one JSON
  document or as an ordered deterministic gzip JSONL batch.
- SQLite is the durable outbox for both modes. The Telegram delivery path removes
  included rows only after an HTTP success whose Bot API payload contains
  `ok=true`.
- Bounded-retention controls are independent safety limits. Maximum age, point
  count, and SQLite disk quota may evict the oldest undelivered rows; those
  evictions must remain observable through logs and queue-depth/database-size
  metrics, with quota evictions counted by `buffer_evictions_total`.
- Telegram delivery is at least once; consumers identify possible retry
  duplicates by `device_id` plus `message_id`.
- A locally detected permanently undeliverable point (including a document over
  Telegram's 50 MB limit) must be durably written to `EDGEWATCH_DEADLETTER_PATH`
  before it is removed from the active outbox; later valid rows must remain
  deliverable.
- This exclusive telemetry setting disables EdgeWatch API calls from the agent,
  but does not prohibit the separate external Telegram fleet controller from
  delivering the narrower typed SSH control and signed local-OTA protocol below.
  The telemetry bot/transport itself never accepts control commands.

### Telegram fleet-control protocol

This is a local operator protocol, not a new HTTP API surface.

- One supervised controller is the sole consumer of a dedicated control bot.
  The control-bot token must never be installed on a device or reused as the
  outbound telemetry credential.
- Telegram authorization uses quoted numeric chat and user IDs, plus an optional
  numeric topic ID. Usernames and display names are never authorization keys.
- Roles are monotonic: `viewer < operator < admin`. Non-admin users require
  explicit fleet scope; every request is checked against chat, actor, fleet, and
  topic before acceptance and again before confirmed fleet dispatch.
- The only recognized operation families are `/device`, `/fleet`, and `/ota`.
  Allowed device operations are:
  - viewer: status, health, network, power, queue, version, OTA status;
  - operator: sample/sync now, active/sleep mode, continuous/eco power,
    alert mute/unmute, agent restart;
  - admin: reboot, bounded deep sleep with an explicit `60s..365d` duration,
    OTA stage/canary/promote/abort;
  - guarded: single-device shutdown only when controller and device guards are
    both enabled.
- Alert-mute expiry must be RFC3339 UTC ending in `Z`. Deep-sleep duration must
  use seconds, minutes, hours, or days and resolve to `60s..365d`.
- Fleet shutdown, arbitrary shell, raw modem commands, arbitrary file or
  environment access, credential display, user-provided artifact URLs, and
  destructive data operations are unsupported for every role.
- Every fleet operation, including read-only work, must persist its ordered
  targets and frozen concurrency, attempt, timeout, backoff, and maximum-duration
  policy before dispatch. Mutating fleet operations also persist an immutable
  review preview containing target IDs, exclusions, canaries, expiry, and hash.
  Confirmation is one-use, actor/chat/topic-bound, re-authorized before it
  queues dispatch, and expires after `120s` by default.
- The complete preview must remain reviewable even when it exceeds one Telegram
  message. Pages must stay within Telegram's message limit without truncating
  target/exclusion detail. Preview pages form a durable ordered reply chain;
  page `n+1`, including the confirmation page, is ineligible for delivery until
  page `n` is durably marked sent. Dispatch uses the persisted preview policy
  (worker bound, attempts, per-attempt timeout, backoff, and maximum duration),
  not a policy recomputed after confirmation.
- Controller updates, commands, per-target rows, confirmations, OTA deployment
  snapshots, audit records, and outbound replies are persisted in SQLite.
  Telegram update handling only persists/queues device work. A separate
  supervised worker claims commands under exclusive expiring leases and
  dispatches bounded waves, renewing its lease and checking expiry/abort state
  between waves. Expired leases are reclaimable after restart. Terminal command
  state and its deduplicated completion reply are committed atomically; Telegram
  reply retry state remains independent of device work state.
- Each device receives exactly one versioned typed envelope containing
  `version`, `command_id`, `device_id`, `issued_at`, `expires_at`, `type`, and
  `args`; unknown or missing fields fail closed.
- Commands expire before dispatch. The device helper persists an applied-command
  ledger and returns the original result for an identical replay. Reusing a
  command ID with different input is rejected.
- `sample_now` and `sync_now` are durably accepted local requests before they are
  applied. `accepted` means pending/claimed device work; only a durable sample or
  successful sync produces `applied`. Failed/stale claims return to pending,
  and the controller persists accepted target state for restart recovery.
- Direct and Spacebridge dispatch require pinned device host keys. Disabling
  host-key checking, requesting a PTY, forwarding an agent, or invoking a
  caller-selected remote program is not supported.
- The frozen Spacebridge maximum-duration/expiry budget includes the tunnel
  connection timeout, device command timeout, four-second tunnel cleanup
  allowance, retry backoff, and the number of bounded dispatch waves.
- The controller SSH key is distinct from the operator SSH key and is constrained
  by an OpenSSH forced command to the root-owned typed helper.

### Telegram OTA protocol

- Telegram supplies only a release alias found in the controller's local
  catalog. Generated catalogs use the exact Git tag as the release key and no
  alias; aliases require a separately reviewed catalog change. The resolved
  immutable manifest carries artifact type, absolute HTTPS URI, size, SHA-256,
  RSA/SHA-256 artifact signature, signature key ID, version identity, the
  mandatory canonical manifest signature, the mandatory top-level
  `runtime_dependency_sha256`, and compatibility metadata.
- OTA stage preview persists that complete signed manifest and its immutable
  identity in the confirmed command, and renders the version, Git tag, commit,
  artifact digest, dependency digest, and manifest identity for review. Later
  catalog or alias changes must not alter a confirmed deployment.
- Production artifact URIs are HTTPS-only. Local `file://` artifacts are
  permitted solely by an explicit test-only construction path.
- `manifest_signature` is mandatory and covers canonical ASCII JSON formed by
  removing only `manifest_signature` and serializing the remaining manifest
  with sorted keys and compact separators. The device verifies it before
  compatibility, download, extraction, or apply.
- `compatibility` is closed and contains exactly nine required fields:
  `schema_version`, `hardware_models`, `release_channel`,
  `minimum_python_version`, `minimum_runtime_schema`, `minimum_ota_schema`,
  `requires_stable_power`, `requires_apply_enabled`, and `minimum_free_bytes`.
  Missing or unknown fields fail closed.
- Unsigned releases, `none` signature schemes, unknown aliases, malformed
  manifests, missing trust anchors, incompatible releases, and digest/signature
  failures fail closed.
- The release builder must resolve the exact `refs/tags/<git_tag>^{commit}` and
  require that commit, the supplied `commit_sha`, and source worktree `HEAD` to
  match. This applies to annotated and lightweight tags and direct builder use.
- For an application bundle, signed `runtime_dependency_sha256` is the SHA-256
  of `agent/requirements.txt` and must match the installed runtime dependency
  baseline. Application OTA is code-only; dependency changes require a new
  base/system image. The current system-image OTA path remains unqualified.
- `stage` verifies and prepares every frozen target without activation. All
  frozen targets must stage successfully before `canary`.
- Fleet OTA `status` reads the durable controller snapshot and does not fan out
  a read to every target.
- `canary` applies exactly the fleet's configured canary IDs. `promote` advances
  exactly one configured rollout tranche after its health/failure/defer gates
  pass. `abort` stops undispatched work but does not claim to roll back devices
  that already applied a release.
- Application-bundle activation atomically changes the stable current symlink,
  restarts the agent, and requires a fresh stable agent-owned readiness receipt.
  A durable apply journal records the original and intended targets plus the
  activation phase before the symlink changes, so restart recovery preserves
  the original rollback target until active state and command outcome are
  committed. Failed readiness restores and restarts the previous release.
  Before the staging rename, extracted files and directories are fsynced; the
  parent directory is fsynced before and after the atomic rename.
- A Pi release requiring stable power must have a fresh, healthy durable power
  evaluation. When its evidence is `none`, a successful
  `vcgencmd get_throttled` result of exactly `throttled=0x0` is also required.
  Missing, stale, malformed, or unhealthy evidence fails closed.
- Apply is disabled by default (`EDGEWATCH_ENABLE_OTA_APPLY=0`) for every
  Telegram update type. Staging may succeed while activation remains rejected.
- Explicit transient OTA failures are retried under the persisted bounded
  dispatch policy with the same stable command ID and are not committed to the
  device replay ledgers. Trust, validation, compatibility, digest, and signature
  failures are terminal.
- System-image application is unqualified for production and remains disabled
  until real-device reboot, boot-health, and bad-release rollback validation is
  complete. Application-bundle qualification does not qualify system-image OTA.

### Device agent payload contract

A telemetry point includes:
- `message_id` (string) — unique per device per point (idempotency key)
- `ts` (datetime) — measurement timestamp
- `metrics` (object) — key/value measurements (numbers/strings)

Minimal Raspberry Pi microphone profile (current default path):
- `metrics.microphone_level_db` (number) — relative microphone amplitude level in dB.
- Additional metrics remain supported and are additive for future hardware profiles.

Power-management telemetry (additive):
- `metrics.power_input_v` (number, volts)
- `metrics.power_input_a` (number, amps)
- `metrics.power_input_w` (number, watts)
- `metrics.power_source` (`solar|battery|unknown`)
- `metrics.power_input_out_of_range` (boolean)
- `metrics.power_unsustainable` (boolean)
- `metrics.power_saver_active` (boolean)
- `metrics.power_runtime_mode` (`continuous|eco|deep_sleep`)
- `metrics.power_sleep_backend` (`none|pi5_rtc|external_supervisor`)
- `metrics.wake_reason` (`scheduled|manual|cold_boot|unknown`)
- `metrics.network_duty_cycled` (boolean)

`network_duty_cycled=true` means routine application transmissions are buffered
between sync windows. It does not assert that the cellular modem or bearer was
powered down or disconnected.

Gateway-reconstructed camera-satellite telemetry is additive and includes:

- `lorawan_message_type` (`telemetry|health|event`)
- `lorawan_sequence` (unsigned v1 frame sequence)
- `lorawan_dev_eui` (lowercase 16-hex closed-inventory identity)
- `equipment_state` (`running|stopped|fault|unknown`)
- `visual_confidence`, `audio_anomaly_score` (numbers within `0..1`)
- `battery_v` and boolean power/health flags
- `model_version_digest` (16 lowercase hex characters on ordinary frames)
- `maintenance_command_token` (16 lowercase hex characters only on a
  `maintenance_ready` receipt; it replaces the model digest in that frame)

The LoRaWAN v1 frame is exact-size/versioned and rejects unknown enums/flag
bits, invalid ranges, CRC mismatch, truncation, and extension. The gateway
derives `message_id` from the exact `(DevEUI, frame bytes)` so ChirpStack replay
and MQTT redelivery preserve idempotency.

The v1 radio downlink defines only `maintenance` wake. It carries a stable
command-token digest, expiry, nonce, bounded readiness timeout, and truncated
HMAC-SHA256 under the per-device wake key. A readiness uplink echoes the exact
command-token digest, so a stale/replayed readiness frame cannot unlock a newer
maintenance request. Expired, overlong-future, wrong-key, wrong-port, and
unknown-operation downlinks fail closed in the shipped decoder. The satellite
MCU must durably reject a previously accepted `(command-token, nonce)` before
energizing the maintenance rail; MCU/radio firmware is a pilot qualification
input and is not shipped by this repository. LoRaWAN does not carry media, SSH,
OTA artifacts, or arbitrary device-control payloads.

A request includes:
- `points: TelemetryPoint[]`

## Functional invariants (must always hold)

1) **Idempotent ingest**
- Inserting a telemetry point with a previously-seen `(device_id, message_id)` must not create a new row.
- API response reports `duplicates` count.

2) **Monotonic `last_seen_at`**
- `devices.last_seen_at` should only move forward based on the newest observed point timestamp.

2b) **Contract-aware ingest (type safety + drift visibility)**
- The active telemetry contract lives at `contracts/telemetry/<version>.yaml`.
- Unknown metric keys are accepted (additive drift) and always recorded in the ingestion batch.
- Unknown keys can also emit drift audit events when `TELEMETRY_CONTRACT_UNKNOWN_KEYS_MODE=flag`.
- Known metric keys are handled by `TELEMETRY_CONTRACT_TYPE_MISMATCH_MODE`:
  - `reject`: request fails with validation error details
  - `quarantine`: invalid points are moved to `quarantined_telemetry`
- Each ingest returns a `batch_id` that can be used to inspect the ingestion lineage.

2c) **Lineage completeness**
- Every ingest call writes an `ingestion_batches` artifact with contract hash + drift summary.
- Replay, pubsub, and simulation paths are tagged for auditability (`source`, `pipeline_mode`).

3) **Token handling**
- Plaintext device tokens are never stored.
- Authentication uses:
  - fingerprint lookup (SHA-256)
  - PBKDF2 hash verification

4) **Offline alert lifecycle**
- A `DEVICE_OFFLINE` alert is opened at most once while the device remains offline.
- When the device returns online, offline alerts resolve and an optional `DEVICE_ONLINE` alert is created.
- When device operation mode is `sleep` or `disabled`, offline lifecycle is suppressed/resolved.

4b) **Microphone offline lifecycle**
- A `MICROPHONE_OFFLINE` alert is opened after `microphone_level_db` stays below threshold for
  `microphone_offline_open_consecutive_samples` (default `2`).

4c) **Camera satellite alert promotion**
- Shadow mode cannot emit a live inference alert.
- Live promotion requires evidence at or above `0.95` held-out alert precision
  and at or below one false alert per device-day.
- `unknown` is preferred over an ambiguous, conflicting, or uncorroborated
  equipment-state guess.
- Event/daily evidence is local-only, bounded by 30 days and configured bytes;
  readiness checks create no evidence and request no shutdown.

4d) **Gateway power/radio qualification**
- `observe` LTE scheduling is never reported as electrical energy savings.
- Production LTE power mode requires fixed root-owned on/off units, a bound
  cellular data-path probe, and 100 successful cycles with Pi throttle flags
  exactly `0x0`.
- A production radio gateway is healthy only when the configured adapter digest
  matches and a fresh status for the current supervised instance proves both
  concentrator detection and bridge connectivity.
- Battery/solar sizing uses measured P95 daily energy. The no-camera P95 average
  must be at most `5 W`; seven-day nameplate energy divides by `0.8` depth of
  discharge, cold derating, and conversion efficiency, while minimum daily
  solar generation is at least `1.5x` the P95 daily load.
- When `microphone_level_db` recovers to or above threshold for
  `microphone_offline_resolve_consecutive_samples` (default `1`), the alert resolves and
  `MICROPHONE_ONLINE` is emitted.

4c) **Power alert lifecycle**
- A `POWER_INPUT_OUT_OF_RANGE` alert is opened when `power_input_out_of_range=true`.
- When `power_input_out_of_range=false`, the alert resolves and `POWER_INPUT_OK` is emitted.
- A `POWER_UNSUSTAINABLE` alert is opened when `power_unsustainable=true`.
- When `power_unsustainable=false`, the alert resolves and `POWER_SUSTAINABLE` is emitted.

6) **Device policy caching**
- `GET /api/v1/device-policy` must support `ETag` + `If-None-Match`.
- Devices should be able to run for long periods without re-downloading policy.

6b) **Device policy cost caps**
- Edge policy contract includes `cost_caps`:
  - `max_bytes_per_day`
  - `max_snapshots_per_day`
  - `max_media_uploads_per_day`
- `max_bytes_per_day` is the routine telemetry budget. A device-local,
  separately bounded urgent reserve may carry startup, heartbeat, state/alert
  transition, and alert snapshot telemetry after routine traffic stops.
- Telegram delivery must enforce the applicable remaining budget with a
  conservative estimate before every request/batch. A request that does not fit
  stays in the durable outbox. Every attempted request, including a failed
  attempt, consumes at least its conservative estimate from the daily counter.
- Current urgent Telegram telemetry must be deliverable without draining older
  routine rows. Any heartbeat-triggered backlog recovery is independently
  bounded and may not consume the urgent reserve.
- Agents must persist UTC-day counters across restarts and emit audit metrics:
  - `cost_cap_active`
  - `bytes_sent_today`
  - `media_uploads_today`
  - `urgent_reserve_bytes`
  - `urgent_bytes_remaining`
- This is an application-level send budget. Delayed kernel-counter
  reconciliation cannot provide a hard physical SIM ceiling; deployments that
  require one must also use a carrier-enforced quota.

6c) **Device policy power management defaults**
- Edge policy contract includes a `power_management` block for dual solar/12V operation.
- If `power_management` is missing in a payload, API + agent parsers inject safe defaults.
- Saver mode behavior is `warn + degrade` (no automatic shutdown).
- Default fields:
  - `enabled=true`
  - `mode=dual`
  - `input_warn_min_v=11.8`
  - `input_warn_max_v=14.8`
  - `input_critical_min_v=11.4`
  - `input_critical_max_v=15.2`
  - `sustainable_input_w=15.0`
  - `unsustainable_window_s=900`
  - `battery_trend_window_s=1800`
  - `battery_drop_warn_v=0.25`
  - `saver_sample_interval_s=1200`
  - `saver_heartbeat_interval_s=1800`
  - `media_disabled_in_saver=true`

6d) **Device policy operation defaults**
- Device policy includes:
  - `operation_mode` (`active|sleep|disabled`)
  - `sleep_poll_interval_s` (default `604800`)
  - `runtime_power_mode` (`continuous|eco|deep_sleep`, default `continuous`)
  - `deep_sleep_backend` (`auto|pi5_rtc|external_supervisor|none`, default `auto`)
  - `disable_requires_manual_restart` (default `true`)
  - `admin_remote_shutdown_enabled` (default `true`)
  - `shutdown_grace_s_default` (default `30`)
  - optional `pending_control_command` snapshot for durable control delivery
- Sleep mode keeps telemetry polling active with long cadence.
- Disabled mode requires local restart to resume agent telemetry.

6da) **Runtime power semantics**
- `continuous` preserves current always-on behavior.
- `eco` is software-only and requires no extra hardware.
- `deep_sleep` is optional:
  - Raspberry Pi 5 may use onboard RTC wakealarm (`pi5_rtc`)
  - Raspberry Pi 4 requires optional external supervisor hardware (`external_supervisor`)
- If `deep_sleep` is selected but no backend is available, the agent falls back to `eco`.
- In `eco` and `deep_sleep`, routine network reconnects are limited to startup, alert transitions, and heartbeat windows.

6f) **Durable control command delivery**
- Owner/operator control writes enqueue a per-device durable command with default TTL `15552000s` (180 days).
- Pending commands are delivered via `GET /api/v1/device-policy` and included in policy ETag state.
- Pending command payload may include shutdown intent metadata:
  - `shutdown_requested` (default `false`)
  - `shutdown_grace_s` (default `30`)
- Pending command payload may also include:
  - `runtime_power_mode`
  - `deep_sleep_backend`
- Devices ack command application with `POST /api/v1/device-commands/{command_id}/ack`.
- Older pending commands are superseded when a newer control command is enqueued.

6fa) **Typed procedure delivery**
- Pre-declared procedure definitions are admin-managed and versioned by name/schema.
- Procedure invocation payloads are queued durably per device and surfaced in device policy as `pending_procedure_invocation`.
- Devices complete invocations through `POST /api/v1/device-procedure-invocations/{invocation_id}/result`.
- Procedure invocations are never arbitrary shell requests at the API boundary; they are named, typed, and auditable.

6fb) **Reported state and device events**
- Devices may upsert latest reported state/variables through `POST /api/v1/device-state/report`.
- Reported state is snapshot-oriented and queryable through `GET /api/v1/devices/{device_id}/state`.
- Devices may publish append-only operational events through `POST /api/v1/device-events`.
- Device events are queryable through `GET /api/v1/device-events` and are distinct from telemetry points and admin audit events.

6fc) **Generalized event delivery**
- Notification destinations may filter by source kind and event type.
- Delivery history is recorded for alerts and non-alert platform events such as device events, procedure invocations, and deployment events.
- Filtered-out events are auditable via `notification_events` with a suppressed decision rather than being silently dropped.

6e) **Ownership and mute semantics**
- Per-device access grants enforce minimum role (`viewer|operator|owner`) for non-admin users.
- Alert mute suppresses outbound notifications only; alert open/resolve rows continue to persist.

6g) **Hybrid disable semantics**
- Owner/operator disable remains logical-latch only (no remote OS shutdown intent).
- Admin shutdown endpoint enqueues `disabled + shutdown_requested` command payload.
- Device-side OS shutdown is guarded by `EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=1`.
- If the guard is unset/false, command still applies logical disable and is acknowledged.

6h) **Device update command delivery**
- `GET /api/v1/device-policy` may include optional `pending_update_command` with:
  - `deployment_id`, `manifest_id`, `git_tag`, `commit_sha`
  - `update_type`
  - `artifact_uri`, `artifact_size`, `artifact_sha256`
  - `artifact_signature`, `artifact_signature_scheme`
  - optional `compatibility` metadata
  - `issued_at`, `expires_at`
  - `signature`, `signature_key_id`
  - `rollback_to_tag`, `health_timeout_s`, `power_guard_required`
- `pending_update_command` must only be surfaced for active deployments where:
  - the device is selected and in a rollout stage that is currently enabled
  - deployment command TTL has not expired
- Device update reports are idempotent by `(deployment_id, device_id, state transition)` and update the latest
  target status.
- Device policy also exposes OTA readiness:
  - `updates_enabled`
  - `updates_pending`
  - optional `busy_reason`
- `GET /api/v1/device-policy` may also include optional `pending_procedure_invocation` with:
  - `id`, `definition_id`, `definition_name`
  - typed request payload
  - `issued_at`, `expires_at`, `timeout_s`

6i) **Deployment controller behavior**
- Stage progression uses ordered rollout percentages (default `1/10/50/100`).
- A deployment halts when observed stage failure rate exceeds configured threshold.
- A deployment may also halt on:
  - excessive defer rate
  - no-quorum timeout
  - stage timeout
- `pause`, `resume`, and `abort` mutate deployment status and emit deployment events for audit.

6j) **Telegram controller availability and separation**
- Provisioning a device does not make Telegram control live. An
  operator-controlled host must separately install the controller
  configuration, dedicated control-bot token, controller SSH private key,
  known-hosts file, inventory, catalog, SQLite state path, and supervisor.
- When the controller is offline, outbound Telegram telemetry remains available;
  control and OTA do not. A second controller must not concurrently consume the
  same bot update stream.
- Telegram telemetry does not independently alert on missing heartbeats.

5) **No secret leakage**
- Logs and error messages must not include device tokens, bot tokens, admin
  keys, SSH/Spacebridge private keys, OTA signing keys, or database URLs.

7) **Media metadata idempotency**
- Creating media metadata with a previously-seen `(device_id, message_id, camera_id)` must not create duplicates.
- Object paths are deterministic: `<device_id>/<camera_id>/<YYYY-MM-DD>/<message_id>.<ext>`.

8) **Admin mutation attribution**
- Admin device mutations are recorded in `admin_events`.
- Each event includes acting principal (`actor_email`, optional `actor_subject`) and request correlation (`request_id`).

## Compatibility policy

- **Backwards compatible changes:**
  - add new metrics keys
  - add new response fields (non-breaking)
  - add new alert types
- **Breaking changes require:**
  - ADR (`docs/DECISIONS/`)
  - explicit versioning plan
  - migration notes in runbooks

## Data contracts

- Postgres schema is the source of truth for persisted telemetry + alerts.
- Schema evolution is tracked via **Alembic migrations** (`migrations/`).
- Local dev applies migrations via the `migrate` service in `docker-compose.yml` (or `AUTO_MIGRATE=1`).
- Production guidance: run migrations as a separate step/job (Cloud Run Job: `edgewatch-migrate-<env>`).

### Contract artifacts

- **Telemetry contract**: `contracts/telemetry/v1.yaml`
- **Edge policy contract**: `contracts/edge_policy/v1.yaml`
- **Camera-satellite telemetry profile**: `camera_satellite_lorawan_v1` in
  `contracts/telemetry/v1.yaml`
- **LoRaWAN binary protocol**: `agent/lorawan/protocol.py`
- **Signed model-bundle contract**: `agent/inference/bundle.py`
- **Ingestion batches**: persisted in Postgres (`ingestion_batches`) and queryable via:
  - `GET /api/v1/admin/ingestions` (admin surface; optional)
- **Drift events**: persisted in Postgres (`drift_events`) and queryable via:
  - `GET /api/v1/admin/drift-events` (admin surface; optional)
- **Notification events**: persisted in Postgres (`notification_events`) and queryable via:
  - `GET /api/v1/admin/notifications` (admin surface; optional)
- **Export batches**: persisted in Postgres (`export_batches`) and queryable via:
  - `GET /api/v1/admin/exports` (admin surface; optional)

## Testing contract

Minimum expectations for changes:
- Unit tests for non-trivial logic (idempotency helpers, status logic, security helpers).
- Regression tests for bug fixes.
- Prefer deterministic tests (avoid wall clock; inject timestamps).

## Observability contract

- **Structured logs** (no secrets)
- **Request correlation** via `X-Request-ID`
- **Infra observability-as-code** lives in `infra/gcp/cloud_run_demo/*`.
