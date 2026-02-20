from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List


def _get_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return float(v)


def _get_optional_float(name: str) -> float | None:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return None
    return float(v)


def _get_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return int(v)


def _get_list(name: str, default: List[str]) -> List[str]:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return [s.strip() for s in v.split(",") if s.strip()]


@dataclass(frozen=True)
class Settings:
    app_env: str
    log_level: str
    log_format: str

    # Secrets / external deps
    database_url: str
    admin_api_key: str

    # DB bootstrap
    auto_migrate: bool

    # Background jobs
    enable_scheduler: bool

    # API surface toggles
    enable_docs: bool

    # Crypto / auth
    token_pbkdf2_iterations: int

    # Monitoring
    offline_check_interval_s: int

    # Threshold overrides (prefer contracts/edge_policy)
    default_water_pressure_low_psi: float | None

    # CORS
    cors_allow_origins: List[str]

    # Demo bootstrap (dev-only by default)
    bootstrap_demo_device: bool
    demo_fleet_size: int
    demo_device_id: str
    demo_device_name: str
    demo_device_token: str

    # Telemetry contracts (data architect story)
    telemetry_contract_version: str
    telemetry_contract_enforce_types: bool

    # Edge policy contract (device-side optimization story)
    edge_policy_version: str


def load_settings() -> Settings:
    app_env = (os.getenv("APP_ENV", "dev").strip() or "dev").lower()

    # --- Required secrets in non-dev ---
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        if app_env == "dev":
            database_url = "postgresql+psycopg://edgewatch:edgewatch@localhost:5435/edgewatch"
        else:
            raise RuntimeError("DATABASE_URL must be set when APP_ENV is not 'dev'")

    admin_api_key = os.getenv("ADMIN_API_KEY")
    if not admin_api_key:
        if app_env == "dev":
            admin_api_key = "dev-admin-key"
        else:
            raise RuntimeError("ADMIN_API_KEY must be set when APP_ENV is not 'dev'")

    # --- Safer defaults ---
    cors_default = ["*"] if app_env == "dev" else []
    bootstrap_demo_default = app_env == "dev"

    return Settings(
        app_env=app_env,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        log_format=os.getenv("LOG_FORMAT", "text"),
        database_url=database_url,
        admin_api_key=admin_api_key,
        auto_migrate=_get_bool("AUTO_MIGRATE", app_env == "dev"),
        enable_scheduler=_get_bool("ENABLE_SCHEDULER", app_env == "dev"),
        enable_docs=_get_bool("ENABLE_DOCS", app_env == "dev"),
        token_pbkdf2_iterations=_get_int("TOKEN_PBKDF2_ITERATIONS", 210_000),
        offline_check_interval_s=_get_int("OFFLINE_CHECK_INTERVAL_S", 30),
        # Deprecated: prefer contracts/edge_policy/* for thresholds.
        default_water_pressure_low_psi=_get_optional_float("DEFAULT_WATER_PRESSURE_LOW_PSI"),
        cors_allow_origins=_get_list("CORS_ALLOW_ORIGINS", cors_default),
        bootstrap_demo_device=_get_bool("BOOTSTRAP_DEMO_DEVICE", bootstrap_demo_default),
        demo_fleet_size=_get_int("DEMO_FLEET_SIZE", 1),
        demo_device_id=os.getenv("DEMO_DEVICE_ID", "demo-well-001"),
        demo_device_name=os.getenv("DEMO_DEVICE_NAME", "Demo Well 001"),
        demo_device_token=os.getenv("DEMO_DEVICE_TOKEN", "dev-device-token-001"),
        telemetry_contract_version=(os.getenv("TELEMETRY_CONTRACT_VERSION", "v1").strip() or "v1"),
        telemetry_contract_enforce_types=_get_bool("TELEMETRY_CONTRACT_ENFORCE_TYPES", True),
        edge_policy_version=(os.getenv("EDGE_POLICY_VERSION", "v1").strip() or "v1"),
    )


settings = load_settings()
