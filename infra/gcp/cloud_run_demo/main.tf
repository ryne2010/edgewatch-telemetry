locals {
  labels = {
    app = "edgewatch-telemetry"
    env = var.env
  }

  # Base env vars (safe for Cloud Run)
  base_env_vars = {
    APP_ENV    = var.env
    LOG_LEVEL  = "INFO"
    LOG_FORMAT = "json"

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

  # Only the *service* gets demo + CORS vars.
  # Jobs should stay minimal and must not inherit demo tokens.
  service_env_vars = merge(local.base_env_vars, local.demo_env_vars, local.cors_env_vars)
  job_env_vars     = local.base_env_vars
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

  runtime_roles = [
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/cloudtrace.agent",
    "roles/secretmanager.secretAccessor",
  ]
}

module "secrets" {
  source     = "../modules/secret_manager"
  project_id = var.project_id

  secrets = {
    "edgewatch-database-url"   = { labels = local.labels }
    "edgewatch-admin-api-key"  = { labels = local.labels }
  }
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
  env_vars              = local.service_env_vars
  labels                = local.labels

  secret_env = {
    DATABASE_URL  = module.secrets.secret_names["edgewatch-database-url"]
    ADMIN_API_KEY = module.secrets.secret_names["edgewatch-admin-api-key"]
  }

  vpc_connector_id = var.enable_vpc_connector ? module.network[0].serverless_connector_id : null
  vpc_egress       = var.vpc_egress
}
