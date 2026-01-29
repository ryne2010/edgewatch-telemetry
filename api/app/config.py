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
    database_url: str
    admin_api_key: str

    offline_check_interval_s: int
    default_water_pressure_low_psi: float

    cors_allow_origins: List[str]

    bootstrap_demo_device: bool
    demo_device_id: str
    demo_device_name: str
    demo_device_token: str


def load_settings() -> Settings:
    return Settings(
        app_env=os.getenv("APP_ENV", "dev"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://edgewatch:edgewatch@localhost:5435/edgewatch",
        ),
        admin_api_key=os.getenv("ADMIN_API_KEY", "dev-admin-key"),
        offline_check_interval_s=_get_int("OFFLINE_CHECK_INTERVAL_S", 30),
        default_water_pressure_low_psi=_get_float("DEFAULT_WATER_PRESSURE_LOW_PSI", 30.0),
        cors_allow_origins=_get_list("CORS_ALLOW_ORIGINS", ["*"]),
        bootstrap_demo_device=_get_bool("BOOTSTRAP_DEMO_DEVICE", False),
        demo_device_id=os.getenv("DEMO_DEVICE_ID", "demo-well-001"),
        demo_device_name=os.getenv("DEMO_DEVICE_NAME", "Demo Well 001"),
        demo_device_token=os.getenv("DEMO_DEVICE_TOKEN", "dev-device-token-001"),
    )


settings = load_settings()
