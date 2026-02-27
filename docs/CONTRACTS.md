# CONTRACTS.md

Contracts define **behavioral guarantees** and **compatibility rules**.
Treat these as non-negotiable unless explicitly changed via ADR.

## Public interfaces

### HTTP API (v1)

Base: `/api/v1`

- `POST /ingest` — device telemetry ingestion (Bearer token)
- `GET  /devices` — list devices + computed status
- `GET  /devices/summary` — fleet-friendly list (status + latest selected vitals)
- `GET  /devices/{device_id}` — device detail + computed status
- `GET  /devices/{device_id}/telemetry` — raw telemetry points
- `GET  /devices/{device_id}/timeseries` — bucketed time series
- `GET  /devices/{device_id}/controls` — device operation + alert mute controls
- `PATCH /devices/{device_id}/controls/operation` — set `active|sleep|disabled` + sleep interval
- `PATCH /devices/{device_id}/controls/alerts` — set/clear alert notification mute window
- `POST /device-commands/{command_id}/ack` — device ack for durable control command delivery
- `GET  /alerts` — recent alerts
- `GET  /device-policy` — edge policy/config for devices (Bearer token; ETag cached)
- `GET  /contracts/telemetry` — active telemetry contract (public)
- `GET  /contracts/edge_policy` — active edge policy contract (public)
- `POST /media` — create media metadata + upload instructions (device auth)
- `PUT  /media/{media_id}/upload` — upload media bytes (device auth)
- `GET  /devices/{device_id}/media` — list recent uploaded media (device auth)
- `GET  /media/{media_id}` — media metadata detail (device auth)
- `GET  /media/{media_id}/download` — media bytes download (device auth; proxied or signed URL)
- `POST /admin/devices` — register device (admin surface; optional)
- `POST /admin/devices/{device_id}/controls/shutdown` — admin-only one-shot shutdown intent enqueue
- `GET  /admin/devices/{device_id}/access` — list per-device access grants
- `PUT  /admin/devices/{device_id}/access/{principal_email}` — create/update per-device access grant
- `DELETE /admin/devices/{device_id}/access/{principal_email}` — remove per-device access grant
- `GET  /admin/ingestions` — ingestion lineage batches (admin surface; optional)
- `GET  /admin/drift-events` — drift audit events (admin surface; optional)
- `GET  /admin/notifications` — notification routing/delivery audit events (admin surface; optional)
- `GET  /admin/exports` — analytics export batch audit (admin surface; optional)
- `GET  /admin/events` — admin mutation audit events (actor attribution)
- `GET  /admin/notification-destinations` — list configured alert webhook destinations (admin surface)
- `POST /admin/notification-destinations` — create alert webhook destination (admin surface)
- `PATCH /admin/notification-destinations/{destination_id}` — update alert webhook destination (admin surface)
- `DELETE /admin/notification-destinations/{destination_id}` — delete alert webhook destination (admin surface)
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
- Agents must persist UTC-day counters across restarts and emit audit metrics:
  - `cost_cap_active`
  - `bytes_sent_today`
  - `media_uploads_today`

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
  - `disable_requires_manual_restart` (default `true`)
  - `admin_remote_shutdown_enabled` (default `true`)
  - `shutdown_grace_s_default` (default `30`)
  - optional `pending_control_command` snapshot for durable control delivery
- Sleep mode keeps telemetry polling active with long cadence.
- Disabled mode requires local restart to resume agent telemetry.

6f) **Durable control command delivery**
- Owner/operator control writes enqueue a per-device durable command with default TTL `15552000s` (180 days).
- Pending commands are delivered via `GET /api/v1/device-policy` and included in policy ETag state.
- Pending command payload may include shutdown intent metadata:
  - `shutdown_requested` (default `false`)
  - `shutdown_grace_s` (default `30`)
- Devices ack command application with `POST /api/v1/device-commands/{command_id}/ack`.
- Older pending commands are superseded when a newer control command is enqueued.

6e) **Ownership and mute semantics**
- Per-device access grants enforce minimum role (`viewer|operator|owner`) for non-admin users.
- Alert mute suppresses outbound notifications only; alert open/resolve rows continue to persist.

6g) **Hybrid disable semantics**
- Owner/operator disable remains logical-latch only (no remote OS shutdown intent).
- Admin shutdown endpoint enqueues `disabled + shutdown_requested` command payload.
- Device-side OS shutdown is guarded by `EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=1`.
- If the guard is unset/false, command still applies logical disable and is acknowledged.

5) **No secret leakage**
- Logs and error messages must not include device tokens, admin keys, or database URLs.

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
