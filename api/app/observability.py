from __future__ import annotations

import json
import logging
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
trace_ctx: ContextVar[Optional[str]] = ContextVar("trace", default=None)


def _utc_iso(ts: float | None = None) -> str:
    dt = datetime.fromtimestamp(ts or time.time(), tz=timezone.utc)
    return dt.isoformat()


def get_request_id() -> Optional[str]:
    return request_id_ctx.get()


def get_trace() -> Optional[str]:
    return trace_ctx.get()


def _extract_request_id(request: Request) -> str:
    # Common upstream headers
    rid = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID")
    if rid:
        return rid.strip()
    return uuid.uuid4().hex


def _extract_trace_header(request: Request) -> Optional[str]:
    # Cloud Run / GFE header: TRACE_ID/SPAN_ID;o=TRACE_TRUE
    # We keep it raw to avoid needing PROJECT_ID in the app.
    v = request.headers.get("X-Cloud-Trace-Context")
    if not v:
        return None
    return v.strip()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request_id (and trace header when present) to each request.

    The request_id is:
    - accepted from upstream (X-Request-ID / X-Correlation-ID), or
    - generated if missing.

    The value is:
    - stored in a ContextVar so logs can include it
    - returned in the response header as X-Request-ID
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        rid = _extract_request_id(request)
        token_rid = request_id_ctx.set(rid)
        token_trace = trace_ctx.set(_extract_trace_header(request))

        start = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:
                duration_ms = int((time.perf_counter() - start) * 1000)
                logging.getLogger("edgewatch.http").exception(
                    "request_error",
                    extra={
                        "http": {
                            "method": request.method,
                            "path": request.url.path,
                            "status": 500,
                            "duration_ms": duration_ms,
                        }
                    },
                )
                raise

            response.headers["X-Request-ID"] = rid

            duration_ms = int((time.perf_counter() - start) * 1000)
            logging.getLogger("edgewatch.http").info(
                "request",
                extra={
                    "http": {
                        "method": request.method,
                        "path": request.url.path,
                        "status": response.status_code,
                        "duration_ms": duration_ms,
                    }
                },
            )
            return response
        finally:
            # Reset context vars so background tasks don't accidentally inherit.
            request_id_ctx.reset(token_rid)
            trace_ctx.reset(token_trace)


# -----------------------------
# Logging
# -----------------------------


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover
        record.request_id = get_request_id()
        record.trace = get_trace()
        return True


@dataclass
class JsonLogConfig:
    service_name: str = "edgewatch"


class JsonFormatter(logging.Formatter):
    """JSON formatter compatible with Cloud Logging structured logs."""

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

        trace = getattr(record, "trace", None)
        if trace:
            payload["trace"] = trace

        # Attach any explicit structured extra payload under "fields".
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload["fields"] = fields

        http = getattr(record, "http", None)
        if isinstance(http, dict):
            payload["http"] = http

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def configure_logging(*, level: int, log_format: str) -> None:
    """Configure app logging.

    - log_format="json": structured JSON for Cloud Logging
    - log_format="text": standard human-readable
    """

    root = logging.getLogger()
    root.setLevel(level)

    # Replace handlers to avoid duplicate logs when called multiple times.
    root.handlers.clear()

    handler = logging.StreamHandler()
    handler.addFilter(ContextFilter())
    if log_format.strip().lower() == "json":
        handler.setFormatter(JsonFormatter(JsonLogConfig()))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))

    root.addHandler(handler)
