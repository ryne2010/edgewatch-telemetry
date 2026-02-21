from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


# -----------------------------
# Request context (request_id, trace)
# -----------------------------


request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
trace_id_ctx: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)
span_id_ctx: ContextVar[Optional[str]] = ContextVar("span_id", default=None)
trace_sampled_ctx: ContextVar[Optional[bool]] = ContextVar("trace_sampled", default=None)


@dataclass
class _OtelRuntime:
    http_requests_total: Any | None = None
    http_request_duration_ms: Any | None = None
    ingest_points_total: Any | None = None
    alert_transitions_total: Any | None = None
    monitor_loop_duration_ms: Any | None = None


_otel_runtime: _OtelRuntime | None = None


def _utc_iso(ts: float | None = None) -> str:
    dt = datetime.fromtimestamp(ts or time.time(), tz=timezone.utc)
    return dt.isoformat()


def get_request_id() -> Optional[str]:
    return request_id_ctx.get()


def get_trace_id() -> Optional[str]:
    return trace_id_ctx.get()


def get_span_id() -> Optional[str]:
    return span_id_ctx.get()


def get_trace_sampled() -> Optional[bool]:
    return trace_sampled_ctx.get()


def _extract_request_id(request: Request) -> str:
    # Common upstream headers
    rid = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID")
    if rid:
        return rid.strip()
    return uuid.uuid4().hex


def _parse_cloud_trace_context(raw: str) -> tuple[str | None, str | None, bool | None]:
    """Parse the Cloud Trace context header.

    Cloud Run/GFE header format:
      X-Cloud-Trace-Context: TRACE_ID/SPAN_ID;o=TRACE_TRUE

    Returns:
      (trace_id, span_id, sampled)

    Notes:
    - trace_id is a 32-character hex string
    - span_id is a decimal string (may be absent)
    - sampled is True/False when "o=" flag is present
    """

    v = (raw or "").strip()
    if not v:
        return None, None, None

    # Split options from trace/span.
    parts = v.split(";")
    head = parts[0].strip()

    sampled: bool | None = None
    for p in parts[1:]:
        pp = p.strip()
        if pp.startswith("o="):
            sampled = pp[2:] == "1"

    if "/" in head:
        trace_id, span_id = head.split("/", 1)
        trace_id = trace_id.strip() or None
        span_id = span_id.strip() or None
        return trace_id, span_id, sampled

    trace_id = head.strip() or None
    return trace_id, None, sampled


def _extract_trace_context(request: Request) -> tuple[str | None, str | None, bool | None]:
    raw = request.headers.get("X-Cloud-Trace-Context")
    if not raw:
        return None, None, None
    return _parse_cloud_trace_context(raw)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request_id (and cloud trace IDs when present) to each request.

    The request_id is:
    - accepted from upstream (X-Request-ID / X-Correlation-ID), or
    - generated if missing.

    Values are:
    - stored in ContextVars so logs can include them
    - returned in the response header as X-Request-ID

    This middleware also emits a structured request log record ("edgewatch.http").
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        rid = _extract_request_id(request)
        trace_id, span_id, sampled = _extract_trace_context(request)

        token_rid = request_id_ctx.set(rid)
        token_trace = trace_id_ctx.set(trace_id)
        token_span = span_id_ctx.set(span_id)
        token_sampled = trace_sampled_ctx.set(sampled)

        start = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:
                duration_ms = int((time.perf_counter() - start) * 1000)
                logging.getLogger("edgewatch.http").exception(
                    "request_error",
                    extra={
                        "httpRequest": _http_request_payload(request, status=500, duration_ms=duration_ms),
                        "fields": {"duration_ms": duration_ms},
                    },
                )
                record_http_request_metric(
                    method=request.method,
                    route=_route_template(request),
                    status_code=500,
                    duration_ms=duration_ms,
                )
                raise

            response.headers["X-Request-ID"] = rid

            duration_ms = int((time.perf_counter() - start) * 1000)
            logging.getLogger("edgewatch.http").info(
                "request",
                extra={
                    "httpRequest": _http_request_payload(
                        request, status=response.status_code, duration_ms=duration_ms
                    ),
                    "fields": {"duration_ms": duration_ms},
                },
            )
            record_http_request_metric(
                method=request.method,
                route=_route_template(request),
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            return response
        finally:
            # Reset context vars so background tasks don't accidentally inherit.
            request_id_ctx.reset(token_rid)
            trace_id_ctx.reset(token_trace)
            span_id_ctx.reset(token_span)
            trace_sampled_ctx.reset(token_sampled)


def _http_request_payload(request: Request, *, status: int, duration_ms: int) -> dict[str, Any]:
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    payload: dict[str, Any] = {
        "requestMethod": request.method,
        "requestUrl": request.url.path,
        "status": status,
        "latency": f"{duration_ms / 1000:.3f}s",
    }
    if client_ip:
        payload["remoteIp"] = client_ip
    if user_agent:
        payload["userAgent"] = user_agent
    referer = request.headers.get("referer")
    if referer:
        payload["referer"] = referer
    return payload


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return request.url.path


def record_http_request_metric(*, method: str, route: str, status_code: int, duration_ms: float) -> None:
    runtime = _otel_runtime
    if runtime is None:
        return

    attrs = {
        "http.method": method.upper(),
        "http.route": route or "/",
        "http.status_code": int(status_code),
    }
    if runtime.http_requests_total is not None:
        runtime.http_requests_total.add(1, attributes=attrs)
    if runtime.http_request_duration_ms is not None:
        runtime.http_request_duration_ms.record(float(duration_ms), attributes=attrs)


def record_ingest_points_metric(
    *,
    accepted: int,
    rejected: int,
    source: str,
    pipeline_mode: str,
) -> None:
    runtime = _otel_runtime
    if runtime is None or runtime.ingest_points_total is None:
        return

    attrs_base = {
        "source": source or "device",
        "pipeline_mode": pipeline_mode or "direct",
    }
    if accepted > 0:
        runtime.ingest_points_total.add(int(accepted), attributes={**attrs_base, "outcome": "accepted"})
    if rejected > 0:
        runtime.ingest_points_total.add(int(rejected), attributes={**attrs_base, "outcome": "rejected"})


def record_alert_transition_metric(*, state: str, alert_type: str, severity: str) -> None:
    runtime = _otel_runtime
    if runtime is None or runtime.alert_transitions_total is None:
        return

    runtime.alert_transitions_total.add(
        1,
        attributes={
            "state": state,
            "alert_type": alert_type,
            "severity": severity or "unknown",
        },
    )


def record_monitor_loop_metric(*, duration_ms: float, success: bool) -> None:
    runtime = _otel_runtime
    if runtime is None or runtime.monitor_loop_duration_ms is None:
        return

    runtime.monitor_loop_duration_ms.record(
        float(duration_ms),
        attributes={
            "success": bool(success),
        },
    )


# -----------------------------
# Logging
# -----------------------------


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover
        record.request_id = get_request_id()
        record.trace_id = get_trace_id()
        record.span_id = get_span_id()
        record.trace_sampled = get_trace_sampled()
        return True


@dataclass
class JsonLogConfig:
    service_name: str = "edgewatch"
    gcp_project_id: str | None = None


class JsonFormatter(logging.Formatter):
    """JSON formatter compatible with Cloud Logging structured logs.

    - Adds request_id
    - Adds Cloud Trace correlation keys when trace_id is available

    See: https://cloud.google.com/logging/docs/structured-logging
    """

    def __init__(self, config: JsonLogConfig) -> None:
        super().__init__()
        self.config = config

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": _utc_iso(record.created),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.config.service_name,
        }

        rid = getattr(record, "request_id", None)
        if rid:
            payload["request_id"] = rid

        # Cloud Trace correlation.
        trace_id = getattr(record, "trace_id", None)
        span_id = getattr(record, "span_id", None)
        sampled = getattr(record, "trace_sampled", None)
        project_id = self.config.gcp_project_id
        if trace_id and project_id:
            payload["logging.googleapis.com/trace"] = f"projects/{project_id}/traces/{trace_id}"
            if span_id:
                payload["logging.googleapis.com/spanId"] = str(span_id)
            if sampled is not None:
                payload["logging.googleapis.com/trace_sampled"] = bool(sampled)
        elif trace_id:
            payload["trace_id"] = trace_id
            if span_id:
                payload["span_id"] = span_id

        # Attach any explicit structured extra payload under "fields".
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload["fields"] = fields

        http_request = getattr(record, "httpRequest", None)
        if isinstance(http_request, dict):
            payload["httpRequest"] = http_request
        else:
            # Back-compat for older call sites.
            http_legacy = getattr(record, "http", None)
            if isinstance(http_legacy, dict):
                payload["http"] = http_legacy

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _detect_gcp_project_id(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    # Common env vars in GCP runtimes.
    for name in (
        "GCP_PROJECT_ID",
        "GOOGLE_CLOUD_PROJECT",
        "GCLOUD_PROJECT",
        "PROJECT_ID",
    ):
        v = os.getenv(name)
        if v and v.strip():
            return v.strip()
    return None


def configure_logging(*, level: int, log_format: str, gcp_project_id: str | None = None) -> None:
    """Configure app logging.

    - log_format="json": structured JSON for Cloud Logging
    - log_format="text": standard human-readable

    When JSON logging is enabled and a GCP project id is provided/detected, logs
    include Cloud Trace correlation keys so traces and logs link in the console.
    """

    root = logging.getLogger()
    root.setLevel(level)

    # Replace handlers to avoid duplicate logs when called multiple times.
    root.handlers.clear()

    handler = logging.StreamHandler()
    handler.addFilter(ContextFilter())
    if log_format.strip().lower() == "json":
        handler.setFormatter(
            JsonFormatter(JsonLogConfig(gcp_project_id=_detect_gcp_project_id(gcp_project_id)))
        )
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))

    root.addHandler(handler)


# -----------------------------
# OpenTelemetry (optional)
# -----------------------------


def maybe_instrument_opentelemetry(
    *,
    enabled: bool,
    app,
    sqlalchemy_engine,
    service_name: str,
    service_version: str,
    environment: str,
) -> None:
    """Optionally instrument FastAPI with OpenTelemetry.

    This is **best-effort** and must never prevent the API from starting.

    - Enabled via ENABLE_OTEL=1
    - Exporter configured via standard OTEL_* env vars

    Notes:
    - Dependencies are optional. If they're not installed, we log a warning and continue.
    - In dev, when no exporter endpoint is configured, we fall back to ConsoleSpanExporter.
    """

    global _otel_runtime

    if not enabled:
        _otel_runtime = None
        return

    log = logging.getLogger("edgewatch.otel")

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
        from sqlalchemy import event as sqlalchemy_event
    except Exception:  # pragma: no cover
        log.warning(
            "OpenTelemetry is enabled (ENABLE_OTEL=1) but dependencies are not installed. "
            "Install the optional 'otel' dependency group.",
            extra={"fields": {"hint": "uv sync --group otel"}},
        )
        return

    # Resource attributes are important for grouping in your backend.
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            "deployment.environment": environment,
        }
    )

    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)

    # Prefer OTLP exporter when configured; fall back to console exporter in dev.
    traces_endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    if traces_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter()
            provider.add_span_processor(BatchSpanProcessor(exporter))
            log.info(
                "OpenTelemetry trace exporter enabled",
                extra={"fields": {"endpoint": traces_endpoint}},
            )
        except Exception:  # pragma: no cover
            log.exception("Failed to configure OTLP exporter; traces will be dropped")
    else:
        if environment == "dev":
            try:
                from opentelemetry.sdk.trace.export import ConsoleSpanExporter

                provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
                log.info("OpenTelemetry console exporter enabled (dev)")
            except Exception:  # pragma: no cover
                log.exception("Failed to configure console exporter; traces will be dropped")
        else:
            log.warning(
                "ENABLE_OTEL=1 but no OTEL exporter endpoint is configured; traces will be dropped",
                extra={"fields": {"hint": "Set OTEL_EXPORTER_OTLP_ENDPOINT"}},
            )

    # Configure metrics provider/exporter.
    metric_readers: list[Any] = []
    metrics_endpoint = os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT") or os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    if metrics_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

            metric_readers.append(PeriodicExportingMetricReader(OTLPMetricExporter()))
            log.info(
                "OpenTelemetry metric exporter enabled",
                extra={"fields": {"endpoint": metrics_endpoint}},
            )
        except Exception:  # pragma: no cover
            log.exception("Failed to configure OTLP metric exporter; metrics will be dropped")
    elif environment == "dev":
        try:
            from opentelemetry.sdk.metrics.export import ConsoleMetricExporter

            metric_readers.append(PeriodicExportingMetricReader(ConsoleMetricExporter()))
            log.info("OpenTelemetry console metric exporter enabled (dev)")
        except Exception:  # pragma: no cover
            log.exception("Failed to configure console metric exporter; metrics will be dropped")
    else:
        log.warning(
            "ENABLE_OTEL=1 but no OTEL metric exporter endpoint is configured; metrics will be dropped",
            extra={
                "fields": {"hint": "Set OTEL_EXPORTER_OTLP_ENDPOINT or OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"}
            },
        )

    try:
        metric_provider = MeterProvider(resource=resource, metric_readers=metric_readers)
        metrics.set_meter_provider(metric_provider)
    except Exception:  # pragma: no cover
        log.exception("Failed to initialize OpenTelemetry metrics provider")
        metric_provider = None

    meter = metrics.get_meter(service_name, service_version) if metric_provider is not None else None
    if meter is not None:
        _otel_runtime = _OtelRuntime(
            http_requests_total=meter.create_counter(
                "edgewatch.http.server.requests",
                unit="{request}",
                description="HTTP request count by route/method/status.",
            ),
            http_request_duration_ms=meter.create_histogram(
                "edgewatch.http.server.duration",
                unit="ms",
                description="HTTP request latency by route/method/status.",
            ),
            ingest_points_total=meter.create_counter(
                "edgewatch.ingest.points",
                unit="{point}",
                description="Ingested points by accepted/rejected outcome.",
            ),
            alert_transitions_total=meter.create_counter(
                "edgewatch.alert.transitions",
                unit="{event}",
                description="Alert lifecycle transitions (open/close).",
            ),
            monitor_loop_duration_ms=meter.create_histogram(
                "edgewatch.monitor.loop.duration",
                unit="ms",
                description="Offline monitor job duration.",
            ),
        )
    else:
        _otel_runtime = None

    # SQLAlchemy spans (query timing + db metadata).
    try:
        SQLAlchemyInstrumentor().instrument(engine=sqlalchemy_engine, tracer_provider=provider)
    except Exception:  # pragma: no cover
        log.exception("Failed to instrument SQLAlchemy with OpenTelemetry")
    else:
        marker = "_edgewatch_otel_sql_request_id_hook"
        db_name = str(getattr(sqlalchemy_engine.url, "database", "") or "")
        if not sqlalchemy_engine.info.get(marker):
            sqlalchemy_engine.info[marker] = True

            @sqlalchemy_event.listens_for(sqlalchemy_engine, "before_cursor_execute")
            def _edgewatch_sql_before_cursor_execute(
                conn,
                cursor,
                statement,
                parameters,
                context,
                executemany,
            ):  # pragma: no cover - callback execution is integration-driven
                span = trace.get_current_span()
                if span is None or not span.is_recording():
                    return
                rid = get_request_id()
                if rid:
                    span.set_attribute("edgewatch.request_id", rid)
                if db_name:
                    span.set_attribute("db.name", db_name)

    def _request_hook(span, scope) -> None:
        if span is None or not span.is_recording():
            return
        rid = get_request_id()
        if rid:
            span.set_attribute("edgewatch.request_id", rid)

    try:
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=provider,
            server_request_hook=_request_hook,
        )
    except Exception:  # pragma: no cover
        log.exception("Failed to instrument FastAPI with OpenTelemetry")
