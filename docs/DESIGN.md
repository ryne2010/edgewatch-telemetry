# DESIGN.md

This document encodes **architecture, boundaries, and allowed dependencies**.
Agents should not invent new structure without updating this file (and usually an ADR).

## Architecture overview

**Components**

- **Edge agent (`agent/`)**
  - Reads sensors (or simulated sensors)
  - Evaluates power-management state (dual-mode hardware + battery-trend fallback)
  - Applies runtime power mode (`continuous|eco|deep_sleep`)
  - Buffers points locally (SQLite)
  - Flushes points to the API when online

- **API (`api/`)**
  - FastAPI service for ingestion + queries
  - Background scheduler for offline monitoring
  - Ownership-aware read/control surfaces
  - Persists to Postgres

- **Database (Postgres)**
  - Devices, ingestion_batches, telemetry_points, alerts

- **Dashboard (`web/`)**
  - Read-only ops UI consuming the API

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

[ edge agent ] --> [ API ingest ]

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
  - reconnects on startup, alert transitions, and heartbeat windows
  - disables Wi-Fi/Bluetooth/HDMI by default when cellular is the intended uplink
  - disables media capture/upload by default
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

Agent behavior:
- `sleep`: telemetry polling remains active at `sleep_poll_interval_s`; media capture/upload disabled.
- `disabled`: local runtime latches disabled and requires on-device service restart to resume.
- `runtime_power_mode=eco` keeps the board on but batches normal network activity to heartbeat windows.
- `runtime_power_mode=deep_sleep` uses Pi 5 RTC or Pi 4 supervisor when available and otherwise falls back to `eco`.
- `shutdown_requested` command:
  - always applies logical disable
  - executes OS shutdown only when `EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=1`
  - otherwise logs guarded non-execution and remains disabled
- Offline monitor suppresses `DEVICE_OFFLINE` lifecycle while in `sleep` or `disabled`.

## OTA deployment flow (RPi fleet)

Runtime/API path:
- Admin publishes signed release metadata in `release_manifests`.
- Admin starts a deployment in `deployments` with:
  - staged rollout percentages (`1/10/50/100` default)
  - target selector (`all|cohort|labels|explicit_ids`)
  - halt thresholds + command TTL
- Per-device rows in `deployment_targets` track rollout stage assignment and state transitions.
- Deployment lifecycle/audit events are recorded in `deployment_events`.
- Device policy includes optional `pending_update_command` when:
  - deployment is active
  - target stage is currently enabled
  - deployment command TTL is not expired

Agent behavior:
- Reports update transitions through `POST /api/v1/device-updates/{deployment_id}/report`.
- Applies power guard before update execution:
  - defer when `power_input_out_of_range` or `power_unsustainable` is active and command requires guard
- Verifies `git_tag -> commit_sha` mapping before apply.
- Applies update path with safe default:
  - default is dry-run report mode (`EDGEWATCH_ENABLE_OTA_APPLY=0`)
  - file/symlink switch only when explicitly enabled
- Auto rollback report path is attempted when apply fails and `rollback_to_tag` is provided.

Deployment controller behavior:
- Advances rollout stage when all currently-enabled stage targets reach terminal states.
- Halts deployment when observed failure rate breaches threshold.
- Pause/resume/abort are explicit operator actions via admin APIs.

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
