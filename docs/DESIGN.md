# DESIGN.md

This document encodes **architecture, boundaries, and allowed dependencies**.
Agents should not invent new structure without updating this file (and usually an ADR).

## Architecture overview

**Components**

- **Edge agent (`agent/`)**
  - Reads sensors, runs hardware-free, or uses simulated sensors
  - Evaluates power-management state (dual-mode hardware + battery-trend fallback)
  - Applies runtime power mode (`continuous|eco|deep_sleep`)
  - Buffers points locally (SQLite)
  - Flushes points to the configured exclusive transport when online:
    - EdgeWatch API (default)
    - Telegram Bot API JSON documents (optional, locally managed)

- **API (`api/`)**
  - FastAPI service for ingestion + queries
  - Background scheduler for offline monitoring
  - Ownership-aware read/control surfaces
  - Persists to Postgres

- **Database (Postgres)**
  - Devices, ingestion_batches, telemetry_points, alerts

- **Dashboard (`web/`)**
  - Read-only ops UI consuming the API

- **Telegram fleet controller (`telegram_controller/`)**
  - Optional API-free operator-control plane with one control-bot consumer
  - Authorizes numeric Telegram chat/user/topic IDs with viewer/operator/admin
    roles and fleet scopes
  - Persists update, confirmation, command, target, reply, audit, and OTA rollout
    state in local SQLite
  - Keeps Telegram update/reply handling separate from a supervised worker that
    claims leased work and dispatches typed envelopes in bounded waves over
    pinned direct SSH or Hologram Spacebridge to the device's forced helper
  - Keeps the control-bot token and controller SSH private key off devices

- **Low-power gateway runtime (`gateway_runtime/`, `agent/lorawan/`)**
  - Opens bounded hourly LTE windows and immediate alert/control/OTA windows
  - Treats electrical modem switching as a fixed systemd adapter contract
  - Bridges validated ChirpStack uplinks to a durable canonical telemetry outbox
  - Coordinates authenticated maintenance wakes without carrying bulk data over LoRaWAN

- **Camera satellite runtime (`agent/camera_satellite_runner.py`, `agent/inference/`)**
  - Captures bounded RTSP video/audio through FFmpeg without putting credentials on argv
  - Runs one-thread INT8 LiteRT inference and deterministic conservative fusion
  - Keeps event clips and daily stills in a bounded 30-day local ring
  - Commits the MCU handoff result before requesting a fixed clean shutdown

- **Infrastructure (`infra/gcp/`)**
  - Optional GCP Cloud Run demo deployment with observability-as-code
  - Optional Pub/Sub ingest lane and analytics export lane (BigQuery)

**Deployment/runtime model**

- Local-first: Docker Compose runs API + Postgres; the UI is built into the API image.
- Cloud-ready: Cloud Run + Secret Manager + observability Terraform module.

## Layering model

At a repo level:

```
[ web UI ]
   |
[ API routes ]
   |
[ services ]
   |
[ models + db ]
   |
[ Postgres ]

[ edge agent ] --> [ API ingest | Telegram channel ]

[ Telegram control bot ] --> [ fleet controller ]
                                  |
                           [ pinned SSH/Spacebridge ]
                                  |
                           [ forced device helper ]

[ camera satellites ] -- compact LoRaWAN --> [ SX1302/3 + ChirpStack gateway ]
        ^                                         |
        |-- authenticated wake + maintenance Wi-Fi|
                                                  v
                                      [ durable Telegram telemetry outbox ]

[ infra ] provisions runtime + security + observability
```

Within `api/app/`:

- `routes/` is the HTTP boundary.
- `services/` contains business logic.
- `models.py` and `db.py` are persistence.
- `schemas.py` are request/response contracts.

### Allowed dependencies

- `routes/*` may depend on:
  - `schemas`, `security`, `db_session`, and `services/*`
  - *Avoid* importing other routes.
- `services/*` may depend on:
  - `models`, `config`, pure helpers
  - *Avoid* importing FastAPI request/response objects.
- `models.py` depends on SQLAlchemy and `db.Base`.
- `agent/*` must not depend on server internals.
- `infra/*` is declarative and should not be imported by runtime code.

## Agent telemetry transport boundary

- `EDGEWATCH_TELEMETRY_TRANSPORT=api` preserves the canonical API ingest, cloud
  policy, control, procedure, OTA, media, and dashboard workflows.
- `EDGEWATCH_TELEMETRY_TRANSPORT=telegram` is a mutually exclusive field-testing
  lane. It does not contact the EdgeWatch API and uses local fallback policy only.
- SQLite remains the transport-neutral durable outbox. Routine Telegram
  delivery is oldest-first. A current urgent health/alert row may bypass routine
  backlog within its bounded reserve; it is durably enqueued before the request.
  Every delivery path deletes a row only after Telegram confirms `ok=true` (or
  after a durable local dead-letter handoff for a permanent payload failure).
- Device-protection limits remain authoritative: maximum age, point count, and
  SQLite disk quota may evict the oldest queued rows. Evictions are logged and
  observable through queue-depth/database-size metrics; quota evictions also
  increment `buffer_evictions_total`.
- Telegram receives complete envelopes either as one JSON document or as an
  ordered deterministic gzip JSONL batch. Delivery is at least once;
  `message_id` makes timeout-related duplicates identifiable.
- A point that cannot fit Telegram's 50 MB document limit is durably moved to the
  configured local dead-letter file before the outbox advances, preventing
  permanent head-of-line blocking without discarding the original payload.
- Telegram telemetry is not a replacement for server-side storage, alert
  lifecycle, dashboard queries, API procedure delivery, API OTA reporting, or
  media upload. A separate external Telegram fleet controller may provide the
  narrower typed control and signed application-bundle OTA lane defined below;
  those capabilities do not come from the telemetry bot or telemetry transport.
- Telegram does not independently alert on a missing heartbeat. Shared bot
  credentials authenticate the bot rather than the originating physical node,
  so per-device provenance requires separate trust boundaries or an external
  monitoring/ingest layer.

## Telegram fleet-control boundary

Controller topology:

- Exactly one supervised controller consumes a dedicated control bot's update
  stream. Devices keep only the separate outbound telemetry-bot credential.
- Configuration is a strict inventory and authorization boundary: numeric chat
  and user IDs, optional numeric topic IDs, role, fleet scope, enabled device,
  transport, capabilities, and pinned SSH aliases are declared explicitly.
- Authorized commands are durably queued without blocking Telegram polling or
  reply delivery. A separate supervised worker claims commands under exclusive
  expiring leases, dispatches bounded waves, and checks expiry/abort state
  between waves. Restart recovery reclaims expired leases and safely replays
  stable per-device command IDs.
- Every fleet command, including read-only work, freezes its target set and
  concurrency, attempt, timeout, backoff, and maximum-duration policy. Mutating
  fleet commands additionally require a durable hashed preview followed by a
  one-use actor/chat/topic-bound confirmation with a default two-minute expiry
  and authorization recheck before dispatch is queued.
- The preview is an immutable, canonical SQLite record of ordered targets,
  exclusions, OTA canaries, arguments, expiries, and bounded dispatch policy.
  Telegram rendering paginates that complete record without truncation. Each
  page has a persisted predecessor, so the confirmation cannot become eligible
  until every review page is durably sent. Confirmation dispatch uses the
  stored concurrency, attempt, timeout, and backoff policy rather than current
  inventory or recomputed policy.
- Alert mute accepts only an RFC3339 UTC expiry ending in `Z`. Admin deep sleep
  requires an explicit duration bounded from 60 seconds through 365 days.
- The controller persists received update IDs, commands, target rows,
  confirmations, deployments, audit records, and outbound replies in SQLite.
  Terminal command state and its deduplicated completion reply are committed in
  one transaction. Reply delivery is independently retried and cannot roll back
  accepted work.
- Every target receives a bounded, versioned JSON envelope with stable command
  ID, device ID, issue/expiry timestamps, operation type, and typed arguments.
- Direct SSH is the home-network transport. Spacebridge opens a supervised
  loopback tunnel for field dispatch. Both paths require the controller's
  known-hosts file and `StrictHostKeyChecking=yes`.
- Spacebridge expiry calculations include tunnel connection, device command,
  four-second cleanup, retry backoff, and bounded-wave time.
- The controller SSH public key is installed separately from the operator key
  and constrained in `authorized_keys` to a root-owned helper. No arbitrary
  shell, PTY, forwarding, raw modem command, file/environment access, credential
  read, fleet shutdown, or user-provided OTA URL crosses this boundary.
- The helper keeps a durable applied-command ledger. An identical replay returns
  the recorded result; a command ID reused with different input is rejected.
- Sample/sync requests use a separate durable local request lifecycle:
  `pending -> claimed -> completed`. The helper returns `accepted` until agent
  work makes the result durable, stale/failed claims return to `pending`, and the
  controller keeps accepted targets resumable until `applied` or expiry.

This controller is an optional deployment, not an automatically active service.
Provisioning prepares the device-side key and trust anchor, but control is not
live until the controller configuration, credentials, pinned hosts, state,
catalog, and supervisor are installed and verified.

## Low-power camera sub-fleet boundary

- The topology is LoRaWAN star-of-stars, not peer mesh. A gateway may serve
  three to five pilot satellites, but satellites do not route one another's
  packets.
- The fixed-width v1 uplink carries only version/type, sequence, timestamp,
  equipment state, visual/audio scores, battery voltage, health flags, and an
  eight-byte model digest. A CRC detects corruption; LoRaWAN supplies link-layer
  confidentiality/integrity.
- The gateway maps a closed `(application_id, DevEUI)` inventory to one stable
  `device_id`, derives a deterministic message ID from the exact frame, and
  persists canonical telemetry before attempting Telegram delivery.
- The only v1 downlink is an HMAC-authenticated, nonce-bearing, expiring
  maintenance wake. Media, SSH, OTA bytes, shell text, and arbitrary commands
  are not defined by the radio protocol.
- Gateway radio readiness requires a reviewed executable pin plus a fresh
  instance-bound status proving both SX1302/SX1303 detection and the local
  ChirpStack bridge. The repository does not ship a vendor concentrator binary,
  so an unqualified radio adapter fails first boot rather than simulating health.
- Event/fault uplinks request an immediate LTE window. Routine outbox delivery,
  dead-man check-in, and control polling use the hourly window. Cross-process
  bounded holds prevent modem power-off during a live delivery or OTA download.
- `observe` power mode exercises scheduling only. Production electrical duty
  cycling requires the carrier-specific fixed on/off units and the 100-cycle
  attach/transfer/undervoltage qualification.

Camera/inference rules:

- Camera credentials are private files and are sent to FFmpeg through stdin;
  URLs containing userinfo are rejected.
- Captures, subprocess duration, output size, evidence age, and evidence bytes
  are bounded. Routine media never enters Telegram or LoRaWAN telemetry.
- Model bundles are signed separately from application code and contain exactly
  vision/audio `.tflite` files, labels, preprocessing, thresholds, and a
  known-answer vector. Compatibility binds hardware and minimum LiteRT version.
- Fusion prefers `unknown` for ambiguity, cross-modal conflict, or an
  uncorroborated fault. Live alerts additionally require signed/local promotion
  evidence for at least 95% precision and no more than one false alert per
  device-day; shadow is the default.
- Event/daily runs atomically commit their result, then request a fixed systemd
  poweroff. The MCU must wait for a separately qualified final-halt signal before
  cutting the Pi/camera rail. Readiness/model checks never request shutdown.

## Power-management flow (RPi solar/12V)

Runtime path:
- Sensor backend reads (`rpi_power_i2c` for INA219/INA260 when available).
- `agent/power_management.py` evaluates:
  - input-voltage out-of-range
  - sustained unsustainable load (hardware watts window) or fallback battery-trend drop
- Agent enriches telemetry with:
  - `power_input_v|a|w`, `power_source`
  - `power_input_out_of_range`, `power_unsustainable`, `power_saver_active`
- In saver mode the agent degrades cadence/media behavior (`warn + degrade`, no auto-shutdown).
- API ingest runtime opens/resolves power alerts using those boolean telemetry flags.

Durability:
- Edge rolling-window state is persisted per device in `edgewatch_power_state_<device_id>.json`.

## Runtime low-power flow

- Raspberry Pi OS Lite remains the standard and documented OS target.
- Runtime power mode is layered on top of device operation mode:
  - `continuous`: current always-on behavior
  - `eco`: software-only low-power behavior
  - `deep_sleep`: optional true halt/power-off between samples
- `eco` behavior:
  - keeps Linux up
  - keeps microphone capture burst-based only
  - buffers routine telemetry locally
  - performs application-layer sends on startup, alert transitions, and heartbeat windows
  - disables Wi-Fi/Bluetooth/HDMI by default when cellular is the intended uplink
  - disables media capture/upload by default
  - leaves the LTE bearer attached by default; `network_duty_cycled` describes
    agent send scheduling, not modem suspension, so alert latency and carrier
    registration remain reliable
- `deep_sleep` behavior:
  - boot -> fetch/apply policy -> sample -> send or buffer -> schedule wake -> halt
  - commands and OTA apply on wake windows, not continuously
  - backend selection:
    - `pi5_rtc`: Raspberry Pi 5 onboard RTC wakealarm + low-power halt
    - `external_supervisor`: Raspberry Pi 4 external RTC/power-latch supervisor
    - unsupported backend selection falls back to `eco`
- Applied runtime telemetry adds:
  - `power_runtime_mode`
  - `power_sleep_backend`
  - `wake_reason`
  - `network_duty_cycled`

## Ownership + control flow

Runtime/API path:
- Admin assigns per-device grants in `device_access_grants`.
- Admin may also assign fleet-scoped grants in `fleet_access_grants`.
- Fleets are first-class governance entities with explicit device membership.
- Read routes (`/devices`, `/alerts`, telemetry endpoints) scope non-admin results to granted devices.
- Owner/operator control routes manage:
  - alert mute windows (`alerts_muted_until`, notifications-only suppression)
  - operation mode (`active|sleep|disabled`)
- Admin control route can enqueue one-shot shutdown intent:
  - `POST /api/v1/admin/devices/{device_id}/controls/shutdown`
  - payload sets `operation_mode=disabled` and `shutdown_requested=true`
- Each control write also enqueues a durable `device_control_commands` entry (default TTL 180 days).
- Device policy payload includes:
  - operation defaults + per-device operation state
  - latest pending control command snapshot (if any)
  - policy ETag includes pending-command state to trigger device refresh
- Devices ack applied commands via `/api/v1/device-commands/{command_id}/ack`.
- Admin manages pre-declared device procedure definitions.
- Operators enqueue typed procedure invocations against devices.
- Device policy may include:
  - latest pending control command
  - latest pending procedure invocation
  - latest pending OTA update command
- Devices report:
  - procedure results
  - latest reported state snapshots
  - append-only device events

Agent behavior:
- `sleep`: telemetry polling remains active at `sleep_poll_interval_s`; media capture/upload disabled.
- `disabled`: local runtime latches disabled and requires on-device service restart to resume.
- `runtime_power_mode=eco` keeps the board and LTE bearer on but batches normal
  application transmissions to heartbeat windows.
- `runtime_power_mode=deep_sleep` uses Pi 5 RTC or Pi 4 supervisor when available and otherwise falls back to `eco`.
- `shutdown_requested` command:
  - always applies logical disable
  - executes OS shutdown only when `EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=1`
  - otherwise logs guarded non-execution and remains disabled
- pending procedure invocation:
  - is delivered through the same cached device policy loop
  - can be executed by a device-local typed runner hook
  - reports success/failure with optional structured result payload
- Offline monitor suppresses `DEVICE_OFFLINE` lifecycle while in `sleep` or `disabled`.

Canonical device-cloud separation:
- telemetry points: time-series measurements
- reported state: latest device snapshot/variables
- device events: append-only operational facts
- durable commands/procedures: operator-initiated work with ack/result lifecycle
- fleets: governance and release scope, not tenant/customer abstraction
- operator tools: read-only search and live event stream surfaces over the canonical models above
- event delivery: a single destination/filter/audit pipeline for alerts and non-alert platform events

## OTA deployment flow (RPi fleet)

Runtime/API path:
- Admin publishes signed release metadata in `release_manifests`.
- Release manifests are artifact-aware and carry:
  - `update_type` (`application_bundle|asset_bundle|system_image`)
  - artifact location/hash/signature metadata
  - compatibility hints (hardware/channel/updater expectations)
- Admin starts a deployment in `deployments` with:
  - staged rollout percentages (`1/10/50/100` default)
  - target selector (`all|cohort|labels|explicit_ids|channel`)
  - halt thresholds + command TTL
- Per-device rows in `deployment_targets` track rollout stage assignment and state transitions.
- Deployment lifecycle/audit events are recorded in `deployment_events`.
- Device policy includes optional `pending_update_command` when:
  - deployment is active
  - target stage is currently enabled
  - deployment command TTL is not expired

Agent behavior:
- Reports update transitions through `POST /api/v1/device-updates/{deployment_id}/report`.
- Downloads release artifacts from the manifest URI into a persistent OTA cache.
- Verifies artifact hash before apply and optionally verifies artifact signatures on-device.
- Applies power guard before update execution:
  - defer when `power_input_out_of_range` or `power_unsustainable` is active and command requires guard
- Applies update path with safe default:
  - `application_bundle`: native bundle extract + symlink swap
  - `asset_bundle`: extract to managed assets path or hand off to an asset apply hook
  - `system_image`: hand off to an external updater command for staged system/image apply
  - default is dry-run report mode (`EDGEWATCH_ENABLE_OTA_APPLY=0`)
- Auto rollback report path is attempted when apply fails and `rollback_to_tag` is provided.
- `system_image` updates use a hybrid model:
  - EdgeWatch remains the rollout/orchestration control plane
  - an external updater owns image install / reboot / rollback semantics
  - boot-health confirmation is persisted in agent update state and reported on the next process start

Deployment controller behavior:
- Advances rollout stage when all currently-enabled stage targets reach terminal states.
- Halts deployment when observed failure rate breaches threshold.
- Can also halt on excessive defer rate, no-quorum timeout, or stage timeout.
- Pause/resume/abort are explicit operator actions via admin APIs.

Telegram/API-free path:

- The external controller resolves a Telegram-supplied alias against its local
  immutable release catalog. Telegram cannot supply an artifact URL, digest,
  signature, key ID, or command.
- A manifest includes version, git tag/commit, artifact type, absolute HTTPS
  URI, declared size, SHA-256, RSA/SHA-256 artifact signature, key ID, mandatory
  canonical manifest signature, mandatory `runtime_dependency_sha256`, and
  compatibility constraints. The manifest signature covers sorted compact
  ASCII JSON after removing only its own field. Unsigned artifacts/manifests and
  `none` signatures are rejected.
- Compatibility is a closed nine-field schema: `schema_version`,
  `hardware_models`, `release_channel`, `minimum_python_version`,
  `minimum_runtime_schema`, `minimum_ota_schema`, `requires_stable_power`,
  `requires_apply_enabled`, and `minimum_free_bytes`. Missing or extra fields
  fail closed. Production artifact transport is HTTPS-only; local files exist
  only behind an explicit test construction path.
- Generated catalogs key releases by the exact Git tag and contain no alias.
  Adding an alias is a separately reviewed catalog change. The builder resolves
  the exact annotated or lightweight tag commit and requires it, the supplied
  commit, and source worktree `HEAD` to match, including in direct invocations.
- `stage` freezes targets and downloads/verifies/extracts without activation.
  All frozen targets must stage successfully before canary apply.
- `canary` applies exactly the configured canary IDs. `promote` advances one
  configured tranche after failure/defer gates pass. `abort` prevents
  undispatched targets from starting and does not claim to undo applied targets.
- Application bundles are code-only updates: the signed SHA-256 of
  `agent/requirements.txt` must match the installed dependency baseline;
  dependency changes require a new base/system image, while the current
  system-image OTA path remains unqualified. Extracted files and directories are
  fsynced before the atomic staging rename, with the parent directory fsynced on
  both sides of the rename. Apply atomically switches `/opt/edgewatch/current`,
  restarts the agent, and requires a fresh stable readiness receipt. Failure
  restores the prior symlink and restarts the prior release.
- A stable-power requirement on a Pi uses fresh durable evaluation state. With
  no sensor evidence, it also requires `vcgencmd get_throttled` to succeed with
  `throttled=0x0`; missing, stale, malformed, or unhealthy evidence fails closed.
- Apply is guarded off by default for application, asset, and system-image
  updates. A successful stage does not imply activation is enabled.
- Explicit transient OTA errors bypass both device replay ledgers so the
  controller can retry the same command ID under the immutable bounded dispatch
  policy. Validation, compatibility, digest, and signature failures are
  terminal.
- System-image apply is unqualified for production and remains guarded off until
  real-device reboot, boot-health, and bad-release rollback qualification is
  complete; application-bundle qualification is not transferable.

## Simulation environment guard

- Simulator remains available in dev/stage by default.
- Default simulation profile is `rpi_microphone_power_v1` (microphone + power keys).
- Legacy full-metric simulation is opt-in via `SIMULATION_PROFILE=legacy_full`.
- Production simulation requires explicit opt-in:
  - runtime env: `SIMULATION_ALLOW_IN_PROD=1`
  - Terraform acknowledgement: `simulation_allow_in_prod=true`
- This keeps synthetic telemetry disabled in prod unless intentionally enabled.

## Boundaries and ownership

- **`api/app/routes/`**
  - Purpose: request validation, auth, response formatting
  - Must not: contain complex business logic

- **`api/app/services/`**
  - Purpose: alert logic, monitoring logic, domain computations
  - Must not: use FastAPI/Starlette request/response types

- **`api/app/models.py`**
  - Purpose: persistence schema
  - Must not: embed business rules beyond constraints/indexes

- **`agent/`**
  - Purpose: local buffering and device-side behavior
  - Must not: assume always-online connectivity

## Error handling policy

- **Routes** translate errors into HTTP responses:
  - 400 for invalid payloads
  - 401/403 for auth
  - 500 for internal errors (do not leak secrets)
- **Services** should:
  - prefer deterministic behavior
  - avoid swallowing exceptions silently (log with context, no secrets)

## Concurrency and performance notes

- Ingest reserves idempotency keys in `telemetry_ingest_dedupe` (`ON CONFLICT DO NOTHING`), then inserts accepted points.
- Optional pipeline mode:
  - `INGEST_PIPELINE_MODE=direct` (default): API persists immediately.
  - `INGEST_PIPELINE_MODE=pubsub`: API publishes a batch; internal worker persists asynchronously.
- Ingest is contract-aware:
  - unknown metric keys are accepted (additive drift)
  - known metric key type mismatches are either rejected or quarantined (configurable)
- Offline monitor runs on an interval and must be safe to run concurrently.
  - Scheduler is configured with `max_instances=1`.

## Change policy

If a change impacts a boundary, public API, or an invariant:

1) Write an ADR in `docs/DECISIONS/`.
2) Update `docs/CONTRACTS.md` and this file.
3) Add a mechanical gate (test/lint/typecheck) where feasible.
