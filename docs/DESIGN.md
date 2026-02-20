# DESIGN.md

This document encodes **architecture, boundaries, and allowed dependencies**.
Agents should not invent new structure without updating this file (and usually an ADR).

## Architecture overview

**Components**

- **Edge agent (`agent/`)**
  - Reads sensors (or simulated sensors)
  - Buffers points locally (SQLite)
  - Flushes points to the API when online

- **API (`api/`)**
  - FastAPI service for ingestion + queries
  - Background scheduler for offline monitoring
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

- Ingest performs per-point upserts (`ON CONFLICT DO NOTHING`).
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
