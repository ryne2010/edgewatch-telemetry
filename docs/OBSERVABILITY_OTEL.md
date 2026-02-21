# OpenTelemetry tracing + metrics (optional)

EdgeWatch ships with **structured JSON logs** (Cloud Logging friendly) and request correlation (request_id + Cloud Trace IDs when present).

If you want full distributed tracing and OTEL metrics export, you can enable **best-effort OpenTelemetry instrumentation**.

## What this enables

When enabled, EdgeWatch will:

- Instrument FastAPI requests with spans (via `opentelemetry-instrumentation-fastapi`).
- Instrument SQLAlchemy DB calls with spans (via `opentelemetry-instrumentation-sqlalchemy`).
- Attach request correlation attributes (`edgewatch.request_id`) on HTTP and DB spans.
- Export traces/metrics via OTLP when `OTEL_EXPORTER_OTLP_ENDPOINT` (or signal-specific OTLP endpoints) is configured.
- Fall back to console exporters in **dev** when no exporter endpoint is set.

This is **best-effort**:

- If the optional dependencies are not installed, EdgeWatch logs a warning and continues without OTEL.
- Tracing must never prevent the API from starting.

## Metrics emitted

When OTEL is enabled, EdgeWatch emits:

- `edgewatch.http.server.requests` (counter) by method/route/status
- `edgewatch.http.server.duration` (histogram, ms) by method/route/status
- `edgewatch.ingest.points` (counter) by outcome (`accepted`/`rejected`), source, pipeline mode
- `edgewatch.alert.transitions` (counter) by state (`open`/`close`), alert type, severity
- `edgewatch.monitor.loop.duration` (histogram, ms) by success

## Local development

1) Install the optional dependency group:

```bash
uv sync --group dev --group otel
```

2) Enable tracing:

```bash
export ENABLE_OTEL=1
```

3) Run the API (any of the usual ways):

```bash
make dev
```

If you do **not** configure an OTLP exporter endpoint, you should see spans and metrics printed to the console in `dev`.

## Production

In production you typically export traces and metrics to an OTLP collector or vendor backend.

Minimum env vars:

```bash
ENABLE_OTEL=1
OTEL_EXPORTER_OTLP_ENDPOINT=https://<your-collector-host>:4318
```

Notes:

- The OTLP exporter reads standard `OTEL_*` environment variables.
- EdgeWatch sets the OTEL resource attributes:
  - `service.name` (defaults to `edgewatch-telemetry`, override with `OTEL_SERVICE_NAME`)
  - `service.version` (EdgeWatch app version)
  - `deployment.environment` (`APP_ENV`)

## Incident usage

During incidents, use OTEL data to quickly answer:

- Is impact endpoint-specific? (`edgewatch.http.server.requests` + `edgewatch.http.server.duration`)
- Is ingest dropping points? (`edgewatch.ingest.points` rejected outcome)
- Are failures alert-driven or noisy transitions? (`edgewatch.alert.transitions`)
- Is scheduler health degrading? (`edgewatch.monitor.loop.duration`)
- Are DB operations the bottleneck? (SQL spans under request spans)

## Cloud Run considerations

Cloud Run deployments can export OTLP signals in multiple ways:

- Export to an external OTLP collector (private network / VPC connector).
- Run an OpenTelemetry Collector (multi-container Cloud Run) as a sidecar.

Because collector topologies and vendors vary, EdgeWatch does not hard-code an exporter backend.

### Terraform

This repo does not yet automatically provision an OTEL collector.

If you want it, add a task under `docs/TASKS/` to:

- deploy an OTEL collector (Cloud Run multi-container or GKE),
- lock it down (IAM + networking),
- configure `OTEL_EXPORTER_OTLP_ENDPOINT` on services.
