locals {
  labels = {
    app = "edgewatch-telemetry"
    env = var.env
  }

  cloudsql_instance_name = coalesce(var.cloudsql_instance_name, "${var.service_name}-pg")

  analytics_export_bucket = coalesce(
    var.analytics_export_bucket_name,
    "${var.project_id}-${var.service_name}-analytics",
  )

  # Base env vars (safe for Cloud Run)
  base_env_vars = {
    APP_ENV    = var.env
    LOG_LEVEL  = "INFO"
    LOG_FORMAT = "json"
    GCP_PROJECT_ID = var.project_id

    # Safety limits (defense in depth)
    MAX_REQUEST_BODY_BYTES = tostring(var.max_request_body_bytes)
    MAX_POINTS_PER_REQUEST = tostring(var.max_points_per_request)
    RATE_LIMIT_ENABLED = var.rate_limit_enabled ? "true" : "false"
    INGEST_RATE_LIMIT_POINTS_PER_MIN = tostring(var.ingest_rate_limit_points_per_min)

    # Admin surface toggles (see docs/PRODUCTION_POSTURE.md)
    ENABLE_ADMIN_ROUTES = var.enable_admin_routes ? "true" : "false"
    ADMIN_AUTH_MODE     = var.admin_auth_mode

    # Route surface toggles (see docs/PRODUCTION_POSTURE.md)
    ENABLE_UI           = var.enable_ui ? "true" : "false"
    ENABLE_INGEST_ROUTES = var.enable_ingest_routes ? "true" : "false"
    ENABLE_READ_ROUTES   = var.enable_read_routes ? "true" : "false"


    # Production-safe: Cloud Run services should not rely on in-process schedulers.
    #
    # Why:
    # - Cloud Run can scale to zero; background threads won't run when the instance is idle.
    # - CPU is throttled when no requests are in-flight (unless you pay for always-on CPU).
    #
    # Pattern:
    # - Keep ENABLE_SCHEDULER=false
    # - Use Cloud Scheduler -> Cloud Run Jobs for offline checks (enable_scheduled_jobs).
    ENABLE_SCHEDULER = "false"

    # Migrations should be run as an explicit job (Cloud Run Job) instead of on every cold start.
    AUTO_MIGRATE = "false"

    # Telemetry contract (data quality + drift visibility)
    TELEMETRY_CONTRACT_VERSION       = "v1"
    TELEMETRY_CONTRACT_ENFORCE_TYPES = "true"

    # Edge policy contract (device-side optimization)
    EDGE_POLICY_VERSION = "v1"

    # Optional event-driven ingest lane
    INGEST_PIPELINE_MODE     = var.enable_pubsub_ingest ? "pubsub" : "direct"
    INGEST_PUBSUB_PROJECT_ID = var.project_id
    INGEST_PUBSUB_TOPIC      = var.pubsub_topic_name

    # Optional analytics export lane
    ANALYTICS_EXPORT_ENABLED    = var.enable_analytics_export ? "true" : "false"
    ANALYTICS_EXPORT_BUCKET     = local.analytics_export_bucket
    ANALYTICS_EXPORT_DATASET    = var.analytics_export_dataset
    ANALYTICS_EXPORT_TABLE      = var.analytics_export_table
    ANALYTICS_EXPORT_GCS_PREFIX = var.analytics_export_gcs_prefix

    # Demo bootstrap guardrails.
    BOOTSTRAP_DEMO_DEVICE = var.bootstrap_demo_device ? "true" : "false"
  }

  demo_env_vars = var.bootstrap_demo_device ? {
    DEMO_FLEET_SIZE   = tostring(var.demo_fleet_size)
    DEMO_DEVICE_ID    = var.demo_device_id
    DEMO_DEVICE_NAME  = var.demo_device_name
    DEMO_DEVICE_TOKEN = var.demo_device_token
  } : {}

  cors_env_vars = var.cors_allow_origins_csv == null ? {} : {
    CORS_ALLOW_ORIGINS = var.cors_allow_origins_csv
  }

  # Only the *primary* service gets demo + CORS vars.
  # Jobs should stay minimal and must not inherit demo tokens.
  # Secondary services (dashboard/admin) explicitly disable demo bootstrap.
  primary_service_env_vars = merge(local.base_env_vars, local.demo_env_vars, local.cors_env_vars)
  secondary_service_env_vars = merge(local.base_env_vars, local.cors_env_vars)
  job_env_vars              = local.base_env_vars

  cloud_sql_instances = var.enable_cloud_sql ? [module.cloud_sql_postgres[0].connection_name] : []

  cloudsql_user_password = coalesce(
    var.cloudsql_user_password,
    format("%s_Aa1", substr(sha256("${var.project_id}:${var.service_name}:${var.env}:edgewatch"), 0, 24)),
  )

  cloudsql_database_url = var.enable_cloud_sql ? format(
    "postgresql+psycopg://%s:%s@/%s?host=/cloudsql/%s",
    module.cloud_sql_postgres[0].user_name,
    urlencode(local.cloudsql_user_password),
    module.cloud_sql_postgres[0].database_name,
    module.cloud_sql_postgres[0].connection_name,
  ) : null

  runtime_roles = concat(
    [
      "roles/logging.logWriter",
      "roles/monitoring.metricWriter",
      "roles/cloudtrace.agent",
      "roles/secretmanager.secretAccessor",
    ],
    var.enable_cloud_sql ? ["roles/cloudsql.client"] : [],
  )

  # Shared secrets passed to Cloud Run services/jobs
  service_secret_env = {
    DATABASE_URL  = module.secrets.secret_names["edgewatch-database-url"]
    ADMIN_API_KEY = module.secrets.secret_names["edgewatch-admin-api-key"]
  }

}

module "core_services" {
  source     = "../modules/core_services"
  project_id = var.project_id
}

module "artifact_registry" {
  source        = "../modules/artifact_registry"
  project_id    = var.project_id
  location      = var.region
  repository_id = var.artifact_repo_name
  description   = "Images for EdgeWatch Cloud Run demo"

  # Cost hygiene: keep demo repositories from growing forever.
  cleanup_policy_dry_run = true
  cleanup_policies = [
    {
      id     = "delete-untagged-old"
      action = "DELETE"
      condition = {
        tag_state  = "UNTAGGED"
        older_than = "1209600s" # 14d
      }
    },
    {
      id     = "keep-latest-tag"
      action = "KEEP"
      condition = {
        tag_state    = "TAGGED"
        tag_prefixes = ["latest"]
      }
    }
  ]
}

module "service_accounts" {
  source     = "../modules/service_accounts"
  project_id = var.project_id

  runtime_account_id   = "sa-edgewatch-runtime-${var.env}"
  runtime_display_name = "EdgeWatch Runtime (${var.env})"

  runtime_roles = local.runtime_roles
}

module "secrets" {
  source     = "../modules/secret_manager"
  project_id = var.project_id

  secrets = {
    "edgewatch-database-url"  = { labels = local.labels }
    "edgewatch-admin-api-key" = { labels = local.labels }
  }
}

module "cloud_sql_postgres" {
  count  = var.enable_cloud_sql ? 1 : 0
  source = "../modules/cloud_sql_postgres"

  project_id          = var.project_id
  region              = var.region
  instance_name       = local.cloudsql_instance_name
  database_version    = var.cloudsql_database_version
  database_name       = var.cloudsql_database_name
  user_name           = var.cloudsql_user_name
  user_password       = local.cloudsql_user_password
  tier                = var.cloudsql_tier
  disk_size_gb        = var.cloudsql_disk_size_gb
  disk_type           = var.cloudsql_disk_type
  availability_type   = var.cloudsql_availability_type
  backup_enabled      = var.cloudsql_backup_enabled
  backup_start_time   = var.cloudsql_backup_start_time
  require_ssl         = var.cloudsql_require_ssl
  deletion_protection = var.cloudsql_deletion_protection
  labels              = local.labels
}

resource "google_secret_manager_secret_version" "database_url_cloudsql" {
  count = var.enable_cloud_sql ? 1 : 0

  secret      = module.secrets.secret_names["edgewatch-database-url"]
  secret_data = local.cloudsql_database_url
}

module "network" {
  count  = var.enable_vpc_connector ? 1 : 0
  source = "../modules/network"

  project_id   = var.project_id
  network_name = "edgewatch-${var.env}-vpc"

  subnets = {
    "edgewatch-${var.env}-subnet" = {
      region = var.region
      cidr   = "10.30.0.0/24"
    }
  }

  create_serverless_connector         = true
  serverless_connector_name           = "edgewatch-${var.env}-connector"
  serverless_connector_region         = var.region
  serverless_connector_cidr           = "10.38.0.0/28"
  serverless_connector_min_throughput = 200
  serverless_connector_max_throughput = 300
}

module "cloud_run" {
  source = "../modules/cloud_run_service"

  project_id            = var.project_id
  region                = var.region
  service_name          = var.service_name
  image                 = var.image
  service_account_email = module.service_accounts.runtime_service_account_email

  cpu           = var.service_cpu
  memory        = var.service_memory
  min_instances = var.min_instances
  max_instances = var.max_instances

  allow_unauthenticated = var.allow_unauthenticated
  env_vars              = local.primary_service_env_vars
  labels                = local.labels

  secret_env = {
    DATABASE_URL  = module.secrets.secret_names["edgewatch-database-url"]
    ADMIN_API_KEY = module.secrets.secret_names["edgewatch-admin-api-key"]
  }

  cloud_sql_instances = local.cloud_sql_instances

  vpc_connector_id = var.enable_vpc_connector ? module.network[0].serverless_connector_id : null
  vpc_egress       = var.vpc_egress

  depends_on = [google_secret_manager_secret_version.database_url_cloudsql]
}

# Optional: separate private admin service (recommended for production IoT posture)
module "cloud_run_admin" {
  count  = var.enable_admin_service ? 1 : 0
  source = "../modules/cloud_run_service"

  project_id            = var.project_id
  region                = var.region
  service_name          = coalesce(var.admin_service_name, "${var.service_name}-admin")
  image                 = var.image
  service_account_email = module.service_accounts.runtime_service_account_email

  allow_unauthenticated = var.admin_allow_unauthenticated
  min_instances         = var.min_instances
  max_instances         = var.max_instances
  cpu                   = var.service_cpu
  memory                = var.service_memory

  # Admin service is meant to be operator-only; disable docs in non-dev by default via APP_ENV.
  env_vars = merge(local.secondary_service_env_vars, {
    # Ensure admin surface is present
    ENABLE_ADMIN_ROUTES = "true"
    ADMIN_AUTH_MODE     = var.admin_service_admin_auth_mode

    # Admin UI should be reachable on this service
    ENABLE_UI           = "true"
    ENABLE_READ_ROUTES  = "true"
    ENABLE_INGEST_ROUTES = "false"

    # Avoid demo-token env propagation in secondary services
    BOOTSTRAP_DEMO_DEVICE = "false"
  })

  secret_env = local.service_secret_env

  cloud_sql_instances = local.cloud_sql_instances
  vpc_connector_id    = var.enable_vpc_connector ? module.network[0].serverless_connector_id : null
  vpc_egress          = var.vpc_egress

  labels = merge(local.labels, { service = "admin" })


  depends_on = [google_secret_manager_secret_version.database_url_cloudsql]
}


# Optional: separate private dashboard service (read-only UI)
module "cloud_run_dashboard" {
  count  = var.enable_dashboard_service ? 1 : 0
  source = "../modules/cloud_run_service"

  project_id            = var.project_id
  region                = var.region
  service_name          = coalesce(var.dashboard_service_name, "${var.service_name}-dashboard")
  image                 = var.image
  service_account_email = module.service_accounts.runtime_service_account_email

  allow_unauthenticated = var.dashboard_allow_unauthenticated
  min_instances         = var.min_instances
  max_instances         = var.max_instances
  cpu                   = var.service_cpu
  memory                = var.service_memory

  # Dashboard service: UI + read endpoints only (no ingest, no admin).
  env_vars = merge(local.secondary_service_env_vars, {
    ENABLE_ADMIN_ROUTES  = "false"
    ADMIN_AUTH_MODE      = "none"
    ENABLE_UI            = "true"
    ENABLE_READ_ROUTES   = "true"
    ENABLE_INGEST_ROUTES = "false"

    # Avoid demo-token env propagation in secondary services
    BOOTSTRAP_DEMO_DEVICE = "false"
  })

  secret_env = local.service_secret_env

  cloud_sql_instances = local.cloud_sql_instances
  vpc_connector_id    = var.enable_vpc_connector ? module.network[0].serverless_connector_id : null
  vpc_egress          = var.vpc_egress

  labels = merge(local.labels, { service = "dashboard" })

  depends_on = [google_secret_manager_secret_version.database_url_cloudsql]
}

