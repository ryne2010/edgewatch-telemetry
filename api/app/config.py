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


AdminAuthMode = Literal["key", "none"]
AuthzRole = Literal["viewer", "operator", "admin"]


@dataclass(frozen=True)
class Settings:
    app_env: str
    log_level: str
    log_format: str
    enable_otel: bool
    gcp_project_id: str | None

    # Secrets / external deps
    database_url: str
    admin_api_key: str

    # DB bootstrap
    auto_migrate: bool

    # Background jobs
    enable_scheduler: bool

    # API surface toggles
    enable_docs: bool
    enable_admin_routes: bool

    # Route surface toggles
    enable_ui: bool
    enable_ingest_routes: bool
    enable_read_routes: bool

    # Auth posture
    admin_auth_mode: AdminAuthMode
    iap_auth_enabled: bool
    authz_enabled: bool
    authz_iap_default_role: AuthzRole
    authz_viewer_emails: List[str]
    authz_operator_emails: List[str]
    authz_admin_emails: List[str]
    authz_dev_principal_enabled: bool
    authz_dev_principal_email: str
    authz_dev_principal_role: AuthzRole

    # Crypto / auth
    token_pbkdf2_iterations: int

    # Monitoring
    offline_check_interval_s: int

    # Threshold overrides (prefer contracts/edge_policy)
    default_water_pressure_low_psi: float | None
    default_battery_low_v: float | None
    default_signal_low_rssi_dbm: float | None

    # CORS
    cors_allow_origins: List[str]

    # Safety limits (abuse / DoS hardening)
    max_request_body_bytes: int
    max_points_per_request: int
    rate_limit_enabled: bool
    ingest_rate_limit_points_per_min: int

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

    # Media storage lane (camera snapshots/clips)
    media_storage_backend: Literal["local", "gcs"]
    media_local_root: str
    media_gcs_bucket: str | None
    media_gcs_prefix: str
    media_max_upload_bytes: int

    # Data retention / compaction (usually run via Cloud Run Job)
    retention_enabled: bool
    telemetry_retention_days: int
    quarantine_retention_days: int
    retention_batch_size: int
    retention_max_batches: int

    # Postgres scale path (time partitions + optional rollups)
    telemetry_partitioning_enabled: bool
    telemetry_partition_lookback_months: int
    telemetry_partition_prewarm_months: int
    telemetry_rollups_enabled: bool
    telemetry_rollup_backfill_hours: int


def load_settings() -> Settings:
    app_env = (os.getenv("APP_ENV", "dev").strip() or "dev").lower()

    # ------------------------------------------------------------------
    # Auth + route toggles
    #
    # Design goal:
    # - Keep a simple admin-key mode for local development.
    # - Allow a production posture where admin routes exist but are protected
    #   by an infrastructure perimeter (Cloud Run IAM/IAP/etc), so no shared
    #   secret is stored in browsers.
    # - Allow a "public ingest" service to disable admin routes entirely.
    # ------------------------------------------------------------------

    enable_admin_routes = _get_bool("ENABLE_ADMIN_ROUTES", True)

    # Route surface toggles
    #
    # These let you deploy the same container image as multiple Cloud Run services
    # with different responsibilities:
    # - public ingest: ingest only (no UI, no read endpoints, no admin)
    # - private dashboard: UI + read endpoints
    # - private admin: UI + admin endpoints
    enable_ui = _get_bool("ENABLE_UI", True)
    enable_ingest_routes = _get_bool("ENABLE_INGEST_ROUTES", True)
    enable_read_routes = _get_bool("ENABLE_READ_ROUTES", True)

    admin_auth_mode_raw = os.getenv("ADMIN_AUTH_MODE", "key").strip().lower() or "key"
    if admin_auth_mode_raw not in {"key", "none"}:
        raise RuntimeError("ADMIN_AUTH_MODE must be one of: key, none")
    admin_auth_mode: AdminAuthMode = admin_auth_mode_raw  # type: ignore[assignment]

    # If admin routes are disabled, auth mode is irrelevant.
    if not enable_admin_routes:
        admin_auth_mode = "none"

    # --- Required secrets in non-dev ---
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        if app_env == "dev":
            database_url = "postgresql+psycopg://edgewatch:edgewatch@localhost:5435/edgewatch"
        else:
            raise RuntimeError("DATABASE_URL must be set when APP_ENV is not 'dev'")

    admin_api_key = os.getenv("ADMIN_API_KEY")
    if enable_admin_routes and admin_auth_mode == "key":
        if not admin_api_key:
            if app_env == "dev":
                admin_api_key = "dev-admin-key"
            else:
                raise RuntimeError("ADMIN_API_KEY must be set when ADMIN_AUTH_MODE=key")
    else:
        # In perimeter-protected mode, this is unused.
        admin_api_key = admin_api_key or ""

    authz_iap_default_role_raw = os.getenv("AUTHZ_IAP_DEFAULT_ROLE", "viewer").strip().lower() or "viewer"
    if authz_iap_default_role_raw not in {"viewer", "operator", "admin"}:
        raise RuntimeError("AUTHZ_IAP_DEFAULT_ROLE must be one of: viewer, operator, admin")
    authz_iap_default_role: AuthzRole = authz_iap_default_role_raw  # type: ignore[assignment]

    authz_dev_principal_role_raw = os.getenv("AUTHZ_DEV_PRINCIPAL_ROLE", "admin").strip().lower() or "admin"
    if authz_dev_principal_role_raw not in {"viewer", "operator", "admin"}:
        raise RuntimeError("AUTHZ_DEV_PRINCIPAL_ROLE must be one of: viewer, operator, admin")
    authz_dev_principal_role: AuthzRole = authz_dev_principal_role_raw  # type: ignore[assignment]

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

    media_storage_backend_raw = os.getenv("MEDIA_STORAGE_BACKEND", "local").strip().lower() or "local"
    if media_storage_backend_raw not in {"local", "gcs"}:
        raise RuntimeError("MEDIA_STORAGE_BACKEND must be one of: local, gcs")
    media_storage_backend: Literal["local", "gcs"] = media_storage_backend_raw  # type: ignore[assignment]

    media_local_root = os.getenv("MEDIA_LOCAL_ROOT", "./data/media").strip() or "./data/media"
    media_gcs_bucket = _get_optional_str("MEDIA_GCS_BUCKET")
    media_gcs_prefix = os.getenv("MEDIA_GCS_PREFIX", "media").strip() or "media"
    media_max_upload_bytes = _get_int("MEDIA_MAX_UPLOAD_BYTES", 20_000_000)
    if media_storage_backend == "gcs" and not media_gcs_bucket:
        raise RuntimeError("MEDIA_GCS_BUCKET is required when MEDIA_STORAGE_BACKEND=gcs")

    # Project id is used for log/trace correlation in Cloud Logging.
    # Prefer explicit env vars, fall back to the Pub/Sub project when set.
    ingest_pubsub_project_id = (
        _get_optional_str("INGEST_PUBSUB_PROJECT_ID")
        or _get_optional_str("GCP_PROJECT_ID")
        or _get_optional_str("GOOGLE_CLOUD_PROJECT")
        or _get_optional_str("GCLOUD_PROJECT")
        or _get_optional_str("PROJECT_ID")
    )
    gcp_project_id = (
        _get_optional_str("GCP_PROJECT_ID")
        or _get_optional_str("GOOGLE_CLOUD_PROJECT")
        or _get_optional_str("GCLOUD_PROJECT")
        or _get_optional_str("PROJECT_ID")
        or ingest_pubsub_project_id
    )

    # Retention defaults: keep staging/dev small; keep prod longer.
    default_retention_days = 30 if app_env == "prod" else 7
    telemetry_retention_days = _get_int("TELEMETRY_RETENTION_DAYS", default_retention_days)
    quarantine_retention_days = _get_int("QUARANTINE_RETENTION_DAYS", telemetry_retention_days)
    retention_enabled = _get_bool("RETENTION_ENABLED", False)
    retention_batch_size = _get_int("RETENTION_BATCH_SIZE", 5000)
    retention_max_batches = _get_int("RETENTION_MAX_BATCHES", 50)
    telemetry_partitioning_enabled = _get_bool("TELEMETRY_PARTITIONING_ENABLED", False)
    telemetry_partition_lookback_months = max(0, _get_int("TELEMETRY_PARTITION_LOOKBACK_MONTHS", 1))
    telemetry_partition_prewarm_months = max(0, _get_int("TELEMETRY_PARTITION_PREWARM_MONTHS", 2))
    telemetry_rollups_enabled = _get_bool("TELEMETRY_ROLLUPS_ENABLED", False)
    telemetry_rollup_backfill_hours = max(1, _get_int("TELEMETRY_ROLLUP_BACKFILL_HOURS", 24 * 7))

    return Settings(
        app_env=app_env,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        log_format=os.getenv("LOG_FORMAT", "text"),
        enable_otel=_get_bool("ENABLE_OTEL", False),
        gcp_project_id=gcp_project_id,
        database_url=database_url,
        admin_api_key=admin_api_key,
        auto_migrate=_get_bool("AUTO_MIGRATE", app_env == "dev"),
        enable_scheduler=_get_bool("ENABLE_SCHEDULER", app_env == "dev"),
        enable_docs=_get_bool("ENABLE_DOCS", app_env == "dev"),
        enable_admin_routes=enable_admin_routes,
        enable_ui=enable_ui,
        enable_ingest_routes=enable_ingest_routes,
        enable_read_routes=enable_read_routes,
        admin_auth_mode=admin_auth_mode,
        iap_auth_enabled=_get_bool("IAP_AUTH_ENABLED", False),
        authz_enabled=_get_bool("AUTHZ_ENABLED", app_env != "dev"),
        authz_iap_default_role=authz_iap_default_role,
        authz_viewer_emails=[s.lower() for s in _get_list("AUTHZ_VIEWER_EMAILS", [])],
        authz_operator_emails=[s.lower() for s in _get_list("AUTHZ_OPERATOR_EMAILS", [])],
        authz_admin_emails=[s.lower() for s in _get_list("AUTHZ_ADMIN_EMAILS", [])],
        authz_dev_principal_enabled=_get_bool("AUTHZ_DEV_PRINCIPAL_ENABLED", app_env == "dev"),
        authz_dev_principal_email=(
            os.getenv("AUTHZ_DEV_PRINCIPAL_EMAIL", "dev-admin@local.edgewatch").strip().lower()
            or "dev-admin@local.edgewatch"
        ),
        authz_dev_principal_role=authz_dev_principal_role,
        token_pbkdf2_iterations=_get_int("TOKEN_PBKDF2_ITERATIONS", 210_000),
        offline_check_interval_s=_get_int("OFFLINE_CHECK_INTERVAL_S", 30),
        # Deprecated: prefer contracts/edge_policy/* for thresholds.
        default_water_pressure_low_psi=_get_optional_float("DEFAULT_WATER_PRESSURE_LOW_PSI"),
        default_battery_low_v=_get_optional_float("DEFAULT_BATTERY_LOW_V"),
        default_signal_low_rssi_dbm=_get_optional_float("DEFAULT_SIGNAL_LOW_RSSI_DBM"),
        cors_allow_origins=_get_list("CORS_ALLOW_ORIGINS", cors_default),
        max_request_body_bytes=_get_int("MAX_REQUEST_BODY_BYTES", 1_000_000),
        max_points_per_request=_get_int("MAX_POINTS_PER_REQUEST", 5000),
        rate_limit_enabled=_get_bool("RATE_LIMIT_ENABLED", True),
        ingest_rate_limit_points_per_min=_get_int("INGEST_RATE_LIMIT_POINTS_PER_MIN", 25_000),
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
        ingest_pubsub_project_id=ingest_pubsub_project_id,
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
        media_storage_backend=media_storage_backend,
        media_local_root=media_local_root,
        media_gcs_bucket=media_gcs_bucket,
        media_gcs_prefix=media_gcs_prefix,
        media_max_upload_bytes=media_max_upload_bytes,
        retention_enabled=retention_enabled,
        telemetry_retention_days=telemetry_retention_days,
        quarantine_retention_days=quarantine_retention_days,
        retention_batch_size=retention_batch_size,
        retention_max_batches=retention_max_batches,
        telemetry_partitioning_enabled=telemetry_partitioning_enabled,
        telemetry_partition_lookback_months=telemetry_partition_lookback_months,
        telemetry_partition_prewarm_months=telemetry_partition_prewarm_months,
        telemetry_rollups_enabled=telemetry_rollups_enabled,
        telemetry_rollup_backfill_hours=telemetry_rollup_backfill_hours,
    )


settings = load_settings()
