locals {
  labels = {
    app = "edgewatch-telemetry"
    env = var.env
  }

  env_vars = {
    APP_ENV   = var.env
    LOG_LEVEL = "INFO"

    # Demo bootstrap (optional)
    BOOTSTRAP_DEMO_DEVICE = "true"
    DEMO_DEVICE_ID        = "demo-well-001"
    DEMO_DEVICE_NAME      = "Demo Well 001"
    DEMO_DEVICE_TOKEN     = "demo-device-token-001"

    # CORS for a demo UI
    CORS_ALLOW_ORIGINS = "*"
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

  cpu           = "1"
  memory        = "512Mi"
  min_instances = var.min_instances
  max_instances = var.max_instances

  allow_unauthenticated = var.allow_unauthenticated
  env_vars              = local.env_vars
  labels                = local.labels

  secret_env = {
    DATABASE_URL  = module.secrets.secret_names["edgewatch-database-url"]
    ADMIN_API_KEY = module.secrets.secret_names["edgewatch-admin-api-key"]
  }

  vpc_connector_id = var.enable_vpc_connector ? module.network[0].serverless_connector_id : null
  vpc_egress       = var.vpc_egress
}
