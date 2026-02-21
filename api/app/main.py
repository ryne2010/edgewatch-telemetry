from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .config import Settings, settings as global_settings
from .db import engine, db_session
from .migrations import maybe_run_startup_migrations
from .models import Device
from .security import hash_token, token_fingerprint
from .services.monitor import ensure_offline_alerts
from .routes.ingest import router as ingest_router
from .routes.devices import router as devices_router
from .routes.alerts import router as alerts_router
from .routes.admin import router as admin_router
from .routes.contracts import router as contracts_router
from .routes.device_policy import router as device_policy_router
from .routes.media import router as media_router
from .routes.pubsub_worker import router as pubsub_worker_router
from .observability import (
    RequestContextMiddleware,
    configure_logging,
    get_request_id,
    maybe_instrument_opentelemetry,
    record_monitor_loop_metric,
)
from .auth.rbac import require_viewer_role
from .version import __version__
from .demo_fleet import derive_nth as _derive_nth


logger = logging.getLogger("edgewatch")


def create_app(_settings: Settings | None = None) -> FastAPI:
    # Allow tests (and advanced deployments) to inject a Settings object
    # without reloading modules.
    settings = _settings or global_settings

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        _setup_logging(settings)
        _init_db()
        _bootstrap_demo_device(settings)
        if settings.enable_scheduler:
            _start_scheduler(settings)
        else:
            logger.info("Scheduler disabled (ENABLE_SCHEDULER=false)")
        yield
        _stop_scheduler()

    docs_url = "/docs" if settings.enable_docs else None
    redoc_url = "/redoc" if settings.enable_docs else None
    openapi_url = "/openapi.json" if settings.enable_docs else None

    app = FastAPI(
        title="EdgeWatch Telemetry API",
        version=__version__,
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Defense-in-depth: cap request body sizes for write endpoints.
    # Cloud-native edge limits are still recommended for internet exposure.
    if settings.max_request_body_bytes > 0:
        from .middleware.limits import BodySizeLimitMiddleware

        app.add_middleware(
            BodySizeLimitMiddleware,
            max_body_bytes=settings.max_request_body_bytes,
            paths=["/api/v1/ingest", "/api/v1/internal/pubsub/push", "/api/v1/admin"],
        )

    # Request IDs / structured HTTP logs
    app.add_middleware(RequestContextMiddleware)

    # Optional OpenTelemetry instrumentation (ENABLE_OTEL=1).
    # Best-effort; never blocks startup if deps are missing.
    maybe_instrument_opentelemetry(
        enabled=settings.enable_otel,
        app=app,
        sqlalchemy_engine=engine,
        service_name=os.getenv("OTEL_SERVICE_NAME") or "edgewatch-telemetry",
        service_version=__version__,
        environment=settings.app_env,
    )

    def _runtime_features() -> dict:
        return {
            "admin": {
                "enabled": bool(settings.enable_admin_routes),
                "auth_mode": str(settings.admin_auth_mode),
                "iap_auth_enabled": bool(settings.iap_auth_enabled),
            },
            "authz": {
                "enabled": bool(settings.authz_enabled),
                "iap_default_role": str(settings.authz_iap_default_role),
                "dev_principal_enabled": bool(settings.authz_dev_principal_enabled),
            },
            "docs": {"enabled": bool(settings.enable_docs)},
            "otel": {"enabled": bool(settings.enable_otel)},
            "ui": {"enabled": bool(settings.enable_ui)},
            "routes": {
                "ingest": bool(settings.enable_ingest_routes),
                "read": bool(settings.enable_read_routes),
            },
            "ingest": {"pipeline_mode": str(settings.ingest_pipeline_mode)},
            "analytics_export": {"enabled": bool(settings.analytics_export_enabled)},
            "media": {"storage_backend": str(settings.media_storage_backend)},
            "retention": {"enabled": bool(settings.retention_enabled)},
            "limits": {
                "max_request_body_bytes": int(settings.max_request_body_bytes),
                "max_points_per_request": int(settings.max_points_per_request),
                "rate_limit_enabled": bool(settings.rate_limit_enabled),
                "ingest_rate_limit_points_per_min": int(settings.ingest_rate_limit_points_per_min),
            },
        }

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"ok": True, "version": __version__, "env": settings.app_env, "features": _runtime_features()}

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException):
        rid = get_request_id() or "unknown"

        # SPA fallback: when the web UI is built into the container, serve index.html
        # for client-side routes (deep links) instead of returning a JSON 404.
        if settings.enable_ui and exc.status_code == 404:
            req_path = request.url.path
            is_api = (
                req_path.startswith("/api") or req_path.startswith("/openapi") or req_path.startswith("/docs")
            )
            looks_like_asset = "." in (req_path.rsplit("/", 1)[-1])
            if (not is_api) and (not looks_like_asset):
                root_dir = Path(__file__).resolve().parents[2]
                index_path = root_dir / "web" / "dist" / "index.html"
                if index_path.exists():
                    return FileResponse(index_path)

        # Preserve explicit error envelopes when callers supply them.
        payload: dict[str, Any]
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            payload = exc.detail
        else:
            payload = {"error": {"code": "HTTP_ERROR", "message": str(exc.detail)}}

        error_obj = payload.get("error")
        if isinstance(error_obj, dict):
            error_obj.setdefault("request_id", rid)

        headers = dict(exc.headers or {})
        headers.setdefault("X-Request-ID", rid)
        return JSONResponse(status_code=exc.status_code, content=payload, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(request: Request, exc: RequestValidationError):
        rid = get_request_id() or "unknown"
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "details": exc.errors(),
                    "request_id": rid,
                }
            },
            headers={"X-Request-ID": rid},
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        # Provide a stable request_id for support/debugging without leaking details.
        rid = get_request_id() or "unknown"
        logger.exception(
            "unhandled_exception",
            extra={"fields": {"path": str(request.url.path), "method": request.method}},
        )
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL", "message": "Internal server error", "request_id": rid}},
            headers={"X-Request-ID": rid},
        )

    # Baseline security headers (safe defaults).
    @app.middleware("http")
    async def _security_headers(request, call_next):
        resp = await call_next(request)

        # NOTE: Our default CSP is strict (no inline scripts). FastAPI's Swagger/Redoc
        # pages include small inline bootstrap scripts. We loosen CSP *only* on docs
        # routes so that:
        # - production UI/API stays hardened
        # - dev docs remain usable
        path = request.url.path or ""
        is_docs_route = path.startswith("/docs") or path.startswith("/redoc")

        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )

        if is_docs_route:
            # Swagger UI / Redoc rely on an inline bootstrap script and (depending on version)
            # may use eval() internally.
            resp.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
                "img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'; connect-src 'self'; form-action 'self'",
            )
        else:
            resp.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
                "img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
                "connect-src 'self'; form-action 'self'",
            )
        resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        resp.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        resp.headers.setdefault("X-DNS-Prefetch-Control", "off")
        resp.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")

        # HSTS only when served over HTTPS (Cloud Run). Local dev is usually HTTP.
        proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").lower()
        if proto == "https":
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

        return resp

    @app.get("/health", include_in_schema=False)
    def health_root():
        return {"ok": True, "env": settings.app_env, "version": app.version, "features": _runtime_features()}

    @app.get("/readyz", include_in_schema=False)
    def readyz():
        """Readiness probe.

        Checks:
        - DB connectivity
        - migrations applied (alembic_version table exists)
        """

        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"not ready: {type(e).__name__}")

        return {"ready": True}

    # Versioned health endpoint (used by the UI)
    @app.get("/api/v1/health")
    def health_api():
        return {"ok": True, "env": settings.app_env, "version": app.version, "features": _runtime_features()}

    # --- Route surface ---
    # Ingest surface (device agent / pubsub push)
    if settings.enable_ingest_routes:
        app.include_router(ingest_router)
        app.include_router(device_policy_router)
        app.include_router(media_router)
        app.include_router(pubsub_worker_router)
    else:
        logger.info("Ingest routes disabled (ENABLE_INGEST_ROUTES=false)")

    # Read surface (dashboard)
    if settings.enable_read_routes:
        app.include_router(devices_router, dependencies=[Depends(require_viewer_role)])
        app.include_router(alerts_router, dependencies=[Depends(require_viewer_role)])
        app.include_router(contracts_router, dependencies=[Depends(require_viewer_role)])
    else:
        logger.info("Read routes disabled (ENABLE_READ_ROUTES=false)")

    # Admin surface (provisioning/debug)
    if settings.enable_admin_routes:
        app.include_router(admin_router)

    # --- Optional React UI ---
    # The backend can serve a built UI from /web/dist when present.
    if settings.enable_ui:
        root_dir = Path(__file__).resolve().parents[2]
        dist_dir = (root_dir / "web" / "dist").resolve()
        assets_dir = dist_dir / "assets"

        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/", include_in_schema=False)
        def ui_index():
            index = dist_dir / "index.html"
            if index.exists():
                return FileResponse(str(index))
            return HTMLResponse(
                "<h1>EdgeWatch</h1><p>Frontend not built. See README for pnpm build instructions.</p>"
            )

        @app.get("/{path:path}", include_in_schema=False)
        def ui_fallback(path: str):
            if path.startswith(("api", "docs", "openapi", "redoc")):
                raise HTTPException(status_code=404)
            candidate = dist_dir / path
            if candidate.exists() and candidate.is_file():
                return FileResponse(str(candidate))
            index = dist_dir / "index.html"
            if index.exists():
                return FileResponse(str(index))
            raise HTTPException(status_code=404)
    else:
        logger.info("UI disabled (ENABLE_UI=false)")

    return app


def _setup_logging(settings: Settings) -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    configure_logging(level=level, log_format=settings.log_format, gcp_project_id=settings.gcp_project_id)
    logger.info("Logging initialized (level=%s)", settings.log_level)


def _init_db() -> None:
    # Apply schema migrations when enabled (AUTO_MIGRATE).
    maybe_run_startup_migrations(engine=engine)
    logger.info("DB init complete")


def _bootstrap_demo_device(settings: Settings) -> None:
    if not settings.bootstrap_demo_device:
        return

    # Keep demo defaults aligned with the edge policy contract. This makes
    # the "battery/data optimization" story deterministic.
    from .edge_policy import load_edge_policy

    pol = load_edge_policy(settings.edge_policy_version)
    demo_heartbeat = int(pol.reporting.heartbeat_interval_s)
    demo_offline_after = max(3 * demo_heartbeat, 120)

    try:
        with db_session() as session:
            fleet_size = max(1, settings.demo_fleet_size)
            for n in range(1, fleet_size + 1):
                device_id = _derive_nth(settings.demo_device_id, n)
                display_name = _derive_nth(settings.demo_device_name, n)
                token = _derive_nth(settings.demo_device_token, n)
                desired_fp = token_fingerprint(token)

                existing = session.query(Device).filter(Device.device_id == device_id).one_or_none()
                if existing:
                    if existing.display_name != display_name:
                        existing.display_name = display_name
                    if existing.token_fingerprint != desired_fp:
                        existing.token_fingerprint = desired_fp
                    existing.token_hash = hash_token(token)
                    existing.heartbeat_interval_s = demo_heartbeat
                    existing.offline_after_s = demo_offline_after
                    existing.enabled = True
                else:
                    session.add(
                        Device(
                            device_id=device_id,
                            display_name=display_name,
                            token_hash=hash_token(token),
                            token_fingerprint=desired_fp,
                            heartbeat_interval_s=demo_heartbeat,
                            offline_after_s=demo_offline_after,
                            enabled=True,
                        )
                    )

            logger.info("Bootstrapped demo fleet (size=%s)", fleet_size)
    except SQLAlchemyError:
        # Cloud deploy lane runs migrations out-of-band (AUTO_MIGRATE=false).
        # If schema isn't ready yet, skip bootstrap so startup can succeed.
        logger.warning("Skipping demo bootstrap; database schema not ready")


_scheduler: BackgroundScheduler | None = None


def _start_scheduler(settings: Settings) -> None:
    global _scheduler
    scheduler = BackgroundScheduler(timezone="UTC")

    scheduler.add_job(
        func=_offline_job,
        trigger="interval",
        seconds=settings.offline_check_interval_s,
        id="offline_check",
        max_instances=1,
        replace_existing=True,
        coalesce=True,
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info("Scheduler started (offline_check_interval_s=%s)", settings.offline_check_interval_s)


def _stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")


def _offline_job() -> None:
    start = time.perf_counter()
    success = False
    try:
        with db_session() as session:
            ensure_offline_alerts(session)
        success = True
    except Exception:
        logger.exception("offline_check failed")
    finally:
        duration_ms = (time.perf_counter() - start) * 1000.0
        record_monitor_loop_metric(duration_ms=duration_ms, success=success)


# ASGI entrypoint
app = create_app()
