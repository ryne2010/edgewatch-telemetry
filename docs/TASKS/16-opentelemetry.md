# Task 16 — OpenTelemetry (SQLAlchemy + metrics + ops docs)

✅ **Status: Implemented (2026-02-21)**

## What’s already implemented

- Optional FastAPI + SQLAlchemy tracing instrumentation behind `ENABLE_OTEL=1`.
- OTLP trace and metric export (if configured via standard `OTEL_*` env vars).
- Console trace + metric exporter fallback in dev.
- OTEL metrics for:
  - request rate/latency per endpoint
  - ingest points accepted/rejected
  - alert opens/closes
  - monitor loop duration

Docs: `docs/OBSERVABILITY_OTEL.md`

## Objective

Round out the observability posture so EdgeWatch is genuinely “incident-friendly”:

- DB spans (SQLAlchemy)
- basic metrics
- clear deployment/runbook guidance

## Scope

### In-scope

1) **SQLAlchemy instrumentation**

- Add `opentelemetry-instrumentation-sqlalchemy` wiring.
- Ensure DB spans include:
  - query timing
  - database name
  - request_id correlation

2) **Core metrics**

Emit a small set of useful metrics (OTEL metrics):

- request rate / latency per endpoint
- ingest points accepted/rejected
- alert opens/closes
- monitor loop duration

3) **Ops guidance**

- Update `docs/OBSERVABILITY.md` with:
  - where traces/metrics land
  - how to use them during incidents

### Out-of-scope

- Agent instrumentation (separate future task).

## Acceptance criteria

- When enabled, traces include both HTTP and DB spans.
- When disabled, overhead is minimal.
- CI passes with deps pinned.

## Deliverables

- API tracing + metrics wiring
- Updated docs/runbooks
- Optional Terraform additions (collector) if needed

## Validation

```bash
make fmt
make lint
make typecheck
make test
```
