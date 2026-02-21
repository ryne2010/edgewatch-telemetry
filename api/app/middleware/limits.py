from __future__ import annotations

"""Request size / safety limits.

These are *defense-in-depth* controls to reduce accidental abuse (or intentional
DoS) when the service is exposed to the internet.

Notes
- Cloud-native rate limiting is usually handled at the edge (API Gateway,
  Cloud Armor, load balancer). These in-app limits are a portable baseline.
- For ingest specifically, we already constrain `points` to <= 500 per request.
  This middleware focuses on total request body size.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..observability import get_request_id


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests with bodies larger than `max_body_bytes`.

    This is applied to POST/PUT/PATCH requests only.

    Why implement this in-app?
    - Cloud Run does not provide an application-level JSON payload size limiter.
    - A single oversized JSON payload can cause CPU/memory spikes.

    IMPORTANT:
    - This is not a perfect streaming limiter because Starlette reads the whole
      body for JSON parsing.
    - It is still valuable as a guardrail for the common case.
    """

    def __init__(self, app, *, max_body_bytes: int, paths: list[str] | None = None) -> None:
        super().__init__(app)
        self.max_body_bytes = int(max_body_bytes)
        self.paths = paths or []

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method.upper() not in {"POST", "PUT", "PATCH"}:
            return await call_next(request)

        if self.paths and not any(request.url.path.startswith(p) for p in self.paths):
            return await call_next(request)

        if self.max_body_bytes <= 0:
            return await call_next(request)

        # Fast-path check using Content-Length when present.
        cl = request.headers.get("content-length")
        if cl:
            try:
                if int(cl) > self.max_body_bytes:
                    return _payload_too_large(max_bytes=self.max_body_bytes)
            except Exception:
                # Ignore malformed header and fall back to reading.
                pass

        # Defensive: read the body once here so downstream can still parse.
        body = await request.body()
        if len(body) > self.max_body_bytes:
            return _payload_too_large(max_bytes=self.max_body_bytes)

        # Starlette caches request.body() internally; ensure body is preserved.
        request._body = body  # type: ignore[attr-defined]
        return await call_next(request)


def _payload_too_large(*, max_bytes: int) -> JSONResponse:
    rid = get_request_id() or "unknown"
    return JSONResponse(
        status_code=413,
        content={
            "error": {
                "code": "PAYLOAD_TOO_LARGE",
                "message": "Request body exceeds configured limit.",
                "max_request_body_bytes": max_bytes,
                "request_id": rid,
            }
        },
        headers={"Retry-After": "0", "X-Request-ID": rid},
    )
