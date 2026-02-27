# DESIGN.md

This document encodes **architecture, boundaries, and allowed dependencies**.
Agents should not invent new structure without updating this file (and usually an ADR).

## Architecture overview

**Components**

- **Edge agent (`agent/`)**
  - Reads sensors (or simulated sensors)
  - Evaluates power-management state (dual-mode hardware + battery-trend fallback)
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
- `shutdown_requested` command:
  - always applies logical disable
  - executes OS shutdown only when `EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=1`
  - otherwise logs guarded non-execution and remains disabled
- Offline monitor suppresses `DEVICE_OFFLINE` lifecycle while in `sleep` or `disabled`.

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
