from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Literal


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


def _get_optional_str(name: str) -> str | None:
    v = os.getenv(name)
    if v is None:
        return None
    vv = v.strip()
    return vv or None


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
    telemetry_contract_unknown_keys_mode: Literal["allow", "flag"]
    telemetry_contract_type_mismatch_mode: Literal["reject", "quarantine"]

    # Edge policy contract (device-side optimization story)
    edge_policy_version: str

    # Alert routing + notifications
    alert_dedupe_window_s: int
    alert_throttle_window_s: int
    alert_throttle_max_notifications: int
    alert_quiet_hours_start: str
    alert_quiet_hours_end: str
    alert_quiet_hours_tz: str
    alert_webhook_url: str | None
    alert_webhook_kind: Literal["generic", "slack"]
    alert_webhook_timeout_s: float

    # Optional event-driven ingest
    ingest_pipeline_mode: Literal["direct", "pubsub"]
    ingest_pubsub_project_id: str | None
    ingest_pubsub_topic: str
    ingest_pubsub_push_shared_token: str | None

    # Optional analytics export lane
    analytics_export_enabled: bool
    analytics_export_bucket: str | None
    analytics_export_dataset: str
    analytics_export_table: str
    analytics_export_gcs_prefix: str
    analytics_export_max_rows: int


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

    unknown_keys_mode = os.getenv("TELEMETRY_CONTRACT_UNKNOWN_KEYS_MODE", "allow").strip().lower() or "allow"
    if unknown_keys_mode not in {"allow", "flag"}:
        raise RuntimeError("TELEMETRY_CONTRACT_UNKNOWN_KEYS_MODE must be one of: allow, flag")

    type_mismatch_mode_raw = _get_optional_str("TELEMETRY_CONTRACT_TYPE_MISMATCH_MODE")
    if type_mismatch_mode_raw is None:
        # Backward-compatible behavior: old boolean controls reject/quarantine.
        type_mismatch_mode_raw = (
            "reject" if _get_bool("TELEMETRY_CONTRACT_ENFORCE_TYPES", True) else "quarantine"
        )
    type_mismatch_mode = type_mismatch_mode_raw.strip().lower()
    if type_mismatch_mode not in {"reject", "quarantine"}:
        raise RuntimeError("TELEMETRY_CONTRACT_TYPE_MISMATCH_MODE must be one of: reject, quarantine")

    webhook_kind = os.getenv("ALERT_WEBHOOK_KIND", "generic").strip().lower() or "generic"
    if webhook_kind not in {"generic", "slack"}:
        raise RuntimeError("ALERT_WEBHOOK_KIND must be one of: generic, slack")

    ingest_pipeline_mode = os.getenv("INGEST_PIPELINE_MODE", "direct").strip().lower() or "direct"
    if ingest_pipeline_mode not in {"direct", "pubsub"}:
        raise RuntimeError("INGEST_PIPELINE_MODE must be one of: direct, pubsub")

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
        telemetry_contract_unknown_keys_mode=unknown_keys_mode,  # type: ignore[arg-type]
        telemetry_contract_type_mismatch_mode=type_mismatch_mode,  # type: ignore[arg-type]
        edge_policy_version=(os.getenv("EDGE_POLICY_VERSION", "v1").strip() or "v1"),
        alert_dedupe_window_s=_get_int("ALERT_DEDUPE_WINDOW_S", 900),
        alert_throttle_window_s=_get_int("ALERT_THROTTLE_WINDOW_S", 3600),
        alert_throttle_max_notifications=_get_int("ALERT_THROTTLE_MAX_NOTIFICATIONS", 20),
        alert_quiet_hours_start=(os.getenv("ALERT_QUIET_HOURS_START", "22:00").strip() or "22:00"),
        alert_quiet_hours_end=(os.getenv("ALERT_QUIET_HOURS_END", "06:00").strip() or "06:00"),
        alert_quiet_hours_tz=(os.getenv("ALERT_QUIET_HOURS_TZ", "UTC").strip() or "UTC"),
        alert_webhook_url=_get_optional_str("ALERT_WEBHOOK_URL"),
        alert_webhook_kind=webhook_kind,  # type: ignore[arg-type]
        alert_webhook_timeout_s=_get_float("ALERT_WEBHOOK_TIMEOUT_S", 5.0),
        ingest_pipeline_mode=ingest_pipeline_mode,  # type: ignore[arg-type]
        ingest_pubsub_project_id=_get_optional_str("INGEST_PUBSUB_PROJECT_ID")
        or _get_optional_str("GCP_PROJECT_ID"),
        ingest_pubsub_topic=(
            os.getenv("INGEST_PUBSUB_TOPIC", "edgewatch-telemetry-raw").strip() or "edgewatch-telemetry-raw"
        ),
        ingest_pubsub_push_shared_token=_get_optional_str("INGEST_PUBSUB_PUSH_SHARED_TOKEN"),
        analytics_export_enabled=_get_bool("ANALYTICS_EXPORT_ENABLED", False),
        analytics_export_bucket=_get_optional_str("ANALYTICS_EXPORT_BUCKET"),
        analytics_export_dataset=(
            os.getenv("ANALYTICS_EXPORT_DATASET", "edgewatch_analytics").strip() or "edgewatch_analytics"
        ),
        analytics_export_table=(
            os.getenv("ANALYTICS_EXPORT_TABLE", "telemetry_points").strip() or "telemetry_points"
        ),
        analytics_export_gcs_prefix=(
            os.getenv("ANALYTICS_EXPORT_GCS_PREFIX", "telemetry").strip() or "telemetry"
        ),
        analytics_export_max_rows=_get_int("ANALYTICS_EXPORT_MAX_ROWS", 50000),
    )


settings = load_settings()
