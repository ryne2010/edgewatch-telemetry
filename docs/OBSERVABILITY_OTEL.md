# OpenTelemetry tracing (optional)

EdgeWatch ships with **structured JSON logs** (Cloud Logging friendly) and request correlation (request_id + Cloud Trace IDs when present).

If you want full distributed tracing (request spans, latency breakdowns, exporting to an OTEL backend), you can enable **best-effort OpenTelemetry instrumentation**.

## What this enables

When enabled, EdgeWatch will:

- Instrument FastAPI requests with spans (via `opentelemetry-instrumentation-fastapi`).
- Export spans via OTLP when `OTEL_EXPORTER_OTLP_ENDPOINT` is configured.
- Fall back to `ConsoleSpanExporter` in **dev** when no exporter endpoint is set.

This is **best-effort**:

- If the optional dependencies are not installed, EdgeWatch logs a warning and continues without tracing.
- Tracing must never prevent the API from starting.

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

If you do **not** configure an OTLP exporter endpoint, you should see spans printed to the console in `dev`.

## Production

In production you typically export spans to an OTLP collector or vendor backend.

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

## Cloud Run considerations

Cloud Run deployments can export OTLP traces in multiple ways:

- Export to an external OTLP collector (private network / VPC connector).
- Run an OpenTelemetry Collector (multi-container Cloud Run) as a sidecar.

Because collector topologies and vendors vary, EdgeWatch does not hard-code an exporter backend.

### Terraform

This repo does not yet automatically provision an OTEL collector.

If you want it, add a task under `docs/TASKS/` to:

- deploy an OTEL collector (Cloud Run multi-container or GKE),
- lock it down (IAM + networking),
- configure `OTEL_EXPORTER_OTLP_ENDPOINT` on services.
