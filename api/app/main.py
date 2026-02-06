from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import engine, db_session
from .models import Base, Device
from .security import hash_token, token_fingerprint
from .services.monitor import ensure_offline_alerts
from .routes.ingest import router as ingest_router
from .routes.devices import router as devices_router
from .routes.alerts import router as alerts_router
from .routes.admin import router as admin_router


logger = logging.getLogger("edgewatch")


def _split_suffix_3digits(s: str) -> tuple[str, int] | None:
    m = re.match(r"^(.*?)(\d{3})$", s)
    if not m:
        return None
    return m.group(1), int(m.group(2))


def _derive_nth(value: str, n: int) -> str:
    """Derive a stable demo fleet value for index `n` (1-based).

    If the value ends with 3 digits (e.g. `demo-well-001`), replace that suffix.
    Otherwise append `-NNN` for n > 1.
    """
    if n == 1:
        return value
    split = _split_suffix_3digits(value)
    if split:
        prefix, _ = split
        return f"{prefix}{n:03d}"
    return f"{value}-{n:03d}"


def create_app() -> FastAPI:
    app = FastAPI(title="EdgeWatch Telemetry API", version="0.2.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/health")
    def health():
        return {"ok": True, "env": settings.app_env}

    app.include_router(ingest_router)
    app.include_router(devices_router)
    app.include_router(alerts_router)
    app.include_router(admin_router)

    # --- Optional React UI ---
    # The backend serves a built UI from /web/dist when present.
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

    return app


app = create_app()


def _setup_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    logger.info("Logging initialized (level=%s)", settings.log_level)


def _init_db() -> None:
    Base.metadata.create_all(engine)
    logger.info("DB initialized")


def _bootstrap_demo_device() -> None:
    if not settings.bootstrap_demo_device:
        return

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
                existing.heartbeat_interval_s = 30
                existing.offline_after_s = 120
                existing.enabled = True
            else:
                session.add(
                    Device(
                        device_id=device_id,
                        display_name=display_name,
                        token_hash=hash_token(token),
                        token_fingerprint=desired_fp,
                        heartbeat_interval_s=30,
                        offline_after_s=120,
                        enabled=True,
                    )
                )

        logger.info("Bootstrapped demo fleet (size=%s)", fleet_size)


_scheduler: BackgroundScheduler | None = None


def _start_scheduler() -> None:
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC")

    _scheduler.add_job(
        func=_offline_job,
        trigger="interval",
        seconds=settings.offline_check_interval_s,
        id="offline_check",
        max_instances=1,
        replace_existing=True,
        coalesce=True,
    )

    _scheduler.start()
    logger.info("Scheduler started (offline_check_interval_s=%s)", settings.offline_check_interval_s)


def _offline_job() -> None:
    try:
        with db_session() as session:
            ensure_offline_alerts(session)
    except Exception:
        logger.exception("offline_check failed")


@app.on_event("startup")
def on_startup() -> None:
    _setup_logging()
    _init_db()
    _bootstrap_demo_device()
    _start_scheduler()


@app.on_event("shutdown")
def on_shutdown() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")
