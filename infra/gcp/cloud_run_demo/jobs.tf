# -----------------------------------------------------------------------------
# Production-safe scheduled jobs
#
# Why:
# - Cloud Run services can scale horizontally.
# - In-process schedulers (APScheduler) can duplicate work.
#
# Pattern:
# - Run offline-check as a Cloud Run Job.
# - Trigger it on a cron schedule via Cloud Scheduler.
# - Grant the scheduler SA *least privilege* permissions to execute the job.
# -----------------------------------------------------------------------------

data "google_project" "project" {
  project_id = var.project_id
}

locals {
  enable_any_scheduler             = var.enable_scheduled_jobs || var.enable_analytics_export || var.enable_simulation || var.enable_retention_job || var.enable_partition_manager_job
  offline_job_name                 = "edgewatch-offline-check-${var.env}"
  offline_scheduler_name           = "edgewatch-offline-check-${var.env}"
  migrate_job_name                 = "edgewatch-migrate-${var.env}"
  analytics_job_name               = "edgewatch-analytics-export-${var.env}"
  analytics_scheduler_name         = "edgewatch-analytics-export-${var.env}"
  simulation_job_name              = "edgewatch-simulate-telemetry-${var.env}"
  simulation_scheduler_name        = "edgewatch-simulate-telemetry-${var.env}"
  retention_job_name               = "edgewatch-retention-${var.env}"
  retention_scheduler_name         = "edgewatch-retention-${var.env}"
  partition_manager_job_name       = "edgewatch-partition-manager-${var.env}"
  partition_manager_scheduler_name = "edgewatch-partition-manager-${var.env}"
}

resource "google_service_account" "scheduler" {
  count = local.enable_any_scheduler ? 1 : 0

  project      = var.project_id
  account_id   = "sa-edgewatch-scheduler-${var.env}"
  display_name = "EdgeWatch Scheduler (${var.env})"
}

# Allow the Cloud Scheduler service agent to mint tokens for the scheduler SA.
resource "google_service_account_iam_member" "scheduler_token_creator" {
  count = local.enable_any_scheduler ? 1 : 0

  service_account_id = google_service_account.scheduler[0].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
}

module "offline_check_job" {
  count  = var.enable_scheduled_jobs ? 1 : 0
  source = "../modules/cloud_run_job"

  project_id            = var.project_id
  region                = var.region
  job_name              = local.offline_job_name
  image                 = var.image
  service_account_email = module.service_accounts.runtime_service_account_email

  command = ["python", "-m", "api.app.jobs.offline_check"]

  # Reuse the same env/secrets as the service so the job behaves consistently.
  env_vars = merge(local.job_env_vars, {
    # Jobs should never start an in-process scheduler.
    ENABLE_SCHEDULER = "false"

    # Avoid running migrations on every scheduled run.
    AUTO_MIGRATE = "false"

    # Jobs should not bootstrap demo devices.
    BOOTSTRAP_DEMO_DEVICE = "false"
  })

  secret_env = {
    DATABASE_URL  = module.secrets.secret_names["edgewatch-database-url"]
    ADMIN_API_KEY = module.secrets.secret_names["edgewatch-admin-api-key"]
  }

  cloud_sql_instances = local.cloud_sql_instances

  vpc_connector_id = var.enable_vpc_connector ? module.network[0].serverless_connector_id : null
  vpc_egress       = var.vpc_egress

  cpu    = var.job_cpu
  memory = var.job_memory

  labels = local.labels

  depends_on = [google_secret_manager_secret_version.database_url_cloudsql]
}

module "migrate_job" {
  count  = var.enable_migration_job ? 1 : 0
  source = "../modules/cloud_run_job"

  project_id            = var.project_id
  region                = var.region
  job_name              = local.migrate_job_name
  image                 = var.image
  service_account_email = module.service_accounts.runtime_service_account_email

  command = ["python", "-m", "api.app.jobs.migrate"]

  env_vars = merge(local.job_env_vars, {
    ENABLE_SCHEDULER      = "false"
    AUTO_MIGRATE          = "false"
    BOOTSTRAP_DEMO_DEVICE = "false"
  })

  secret_env = {
    DATABASE_URL  = module.secrets.secret_names["edgewatch-database-url"]
    ADMIN_API_KEY = module.secrets.secret_names["edgewatch-admin-api-key"]
  }

  cloud_sql_instances = local.cloud_sql_instances

  vpc_connector_id = var.enable_vpc_connector ? module.network[0].serverless_connector_id : null
  vpc_egress       = var.vpc_egress

  cpu    = var.job_cpu
  memory = var.job_memory

  labels = local.labels

  depends_on = [google_secret_manager_secret_version.database_url_cloudsql]
}

module "analytics_export_job" {
  count  = var.enable_analytics_export ? 1 : 0
  source = "../modules/cloud_run_job"

  project_id            = var.project_id
  region                = var.region
  job_name              = local.analytics_job_name
  image                 = var.image
  service_account_email = module.service_accounts.runtime_service_account_email

  command = ["python", "-m", "api.app.jobs.analytics_export"]

  env_vars = merge(local.job_env_vars, {
    ENABLE_SCHEDULER         = "false"
    AUTO_MIGRATE             = "false"
    BOOTSTRAP_DEMO_DEVICE    = "false"
    ANALYTICS_EXPORT_ENABLED = "true"
    ANALYTICS_EXPORT_BUCKET  = local.analytics_export_bucket
  })

  secret_env = {
    DATABASE_URL  = module.secrets.secret_names["edgewatch-database-url"]
    ADMIN_API_KEY = module.secrets.secret_names["edgewatch-admin-api-key"]
  }

  cloud_sql_instances = local.cloud_sql_instances

  vpc_connector_id = var.enable_vpc_connector ? module.network[0].serverless_connector_id : null
  vpc_egress       = var.vpc_egress

  cpu    = var.job_cpu
  memory = var.job_memory

  labels = local.labels

  depends_on = [google_secret_manager_secret_version.database_url_cloudsql]
}


module "simulation_job" {
  count  = var.enable_simulation ? 1 : 0
  source = "../modules/cloud_run_job"

  project_id            = var.project_id
  region                = var.region
  job_name              = local.simulation_job_name
  image                 = var.image
  service_account_email = module.service_accounts.runtime_service_account_email

  command = ["python", "-m", "api.app.jobs.simulate_telemetry"]

  # NOTE: Simulation is a dev/stage convenience. We intentionally allow the job
  # to inherit demo env vars so it can bootstrap the demo fleet without
  # requiring a warm web request.
  env_vars = merge(local.job_env_vars, local.demo_env_vars, {
    ENABLE_SCHEDULER             = "false"
    AUTO_MIGRATE                 = "false"
    BOOTSTRAP_DEMO_DEVICE        = "false"
    SIMULATION_POINTS_PER_DEVICE = tostring(var.simulation_points_per_device)
    SIMULATION_ALLOW_IN_PROD     = tostring(var.simulation_allow_in_prod)
  })

  secret_env = {
    DATABASE_URL  = module.secrets.secret_names["edgewatch-database-url"]
    ADMIN_API_KEY = module.secrets.secret_names["edgewatch-admin-api-key"]
  }

  cloud_sql_instances = local.cloud_sql_instances

  vpc_connector_id = var.enable_vpc_connector ? module.network[0].serverless_connector_id : null
  vpc_egress       = var.vpc_egress

  cpu    = var.job_cpu
  memory = var.job_memory

  labels = local.labels

  depends_on = [google_secret_manager_secret_version.database_url_cloudsql]
}


module "retention_job" {
  count  = var.enable_retention_job ? 1 : 0
  source = "../modules/cloud_run_job"

  project_id            = var.project_id
  region                = var.region
  job_name              = local.retention_job_name
  image                 = var.image
  service_account_email = module.service_accounts.runtime_service_account_email

  command = ["python", "-m", "api.app.jobs.retention"]

  env_vars = merge(local.job_env_vars, {
    ENABLE_SCHEDULER      = "false"
    AUTO_MIGRATE          = "false"
    BOOTSTRAP_DEMO_DEVICE = "false"

    # Enable deletions (job-only).
    RETENTION_ENABLED = "true"

    TELEMETRY_RETENTION_DAYS  = tostring(var.telemetry_retention_days)
    QUARANTINE_RETENTION_DAYS = tostring(var.quarantine_retention_days)

    RETENTION_BATCH_SIZE  = tostring(var.retention_batch_size)
    RETENTION_MAX_BATCHES = tostring(var.retention_max_batches)

    TELEMETRY_PARTITIONING_ENABLED = "true"
    TELEMETRY_ROLLUPS_ENABLED      = tostring(var.telemetry_rollups_enabled)
  })

  secret_env = {
    DATABASE_URL  = module.secrets.secret_names["edgewatch-database-url"]
    ADMIN_API_KEY = module.secrets.secret_names["edgewatch-admin-api-key"]
  }

  cloud_sql_instances = local.cloud_sql_instances

  vpc_connector_id = var.enable_vpc_connector ? module.network[0].serverless_connector_id : null
  vpc_egress       = var.vpc_egress

  cpu    = var.job_cpu
  memory = var.job_memory

  labels = local.labels

  depends_on = [google_secret_manager_secret_version.database_url_cloudsql]
}


module "partition_manager_job" {
  count  = var.enable_partition_manager_job ? 1 : 0
  source = "../modules/cloud_run_job"

  project_id            = var.project_id
  region                = var.region
  job_name              = local.partition_manager_job_name
  image                 = var.image
  service_account_email = module.service_accounts.runtime_service_account_email

  command = ["python", "-m", "api.app.jobs.partition_manager"]

  env_vars = merge(local.job_env_vars, {
    ENABLE_SCHEDULER      = "false"
    AUTO_MIGRATE          = "false"
    BOOTSTRAP_DEMO_DEVICE = "false"

    TELEMETRY_PARTITIONING_ENABLED      = "true"
    TELEMETRY_PARTITION_LOOKBACK_MONTHS = tostring(var.telemetry_partition_lookback_months)
    TELEMETRY_PARTITION_PREWARM_MONTHS  = tostring(var.telemetry_partition_prewarm_months)
    TELEMETRY_ROLLUPS_ENABLED           = tostring(var.telemetry_rollups_enabled)
    TELEMETRY_ROLLUP_BACKFILL_HOURS     = tostring(var.telemetry_rollup_backfill_hours)
  })

  secret_env = {
    DATABASE_URL  = module.secrets.secret_names["edgewatch-database-url"]
    ADMIN_API_KEY = module.secrets.secret_names["edgewatch-admin-api-key"]
  }

  cloud_sql_instances = local.cloud_sql_instances

  vpc_connector_id = var.enable_vpc_connector ? module.network[0].serverless_connector_id : null
  vpc_egress       = var.vpc_egress

  cpu    = var.job_cpu
  memory = var.job_memory

  labels = local.labels

  depends_on = [google_secret_manager_secret_version.database_url_cloudsql]
}


# -----------------------------------------------------------------------------
# Least-privilege permissions for the scheduler SA
#
# To execute Cloud Run Jobs, the caller needs:
# - roles/run.invoker on the job
# - roles/iam.serviceAccountUser on the job's execution service account
# - roles/artifactregistry.reader on the repo containing the job image
# -----------------------------------------------------------------------------

resource "google_cloud_run_v2_job_iam_member" "scheduler_offline_invoker" {
  count = var.enable_scheduled_jobs ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = module.offline_check_job[0].job_name

  role   = "roles/run.invoker"
  member = "serviceAccount:${google_service_account.scheduler[0].email}"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_analytics_invoker" {
  count = var.enable_analytics_export ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = module.analytics_export_job[0].job_name

  role   = "roles/run.invoker"
  member = "serviceAccount:${google_service_account.scheduler[0].email}"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_simulation_invoker" {
  count = var.enable_simulation ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = module.simulation_job[0].job_name

  role   = "roles/run.invoker"
  member = "serviceAccount:${google_service_account.scheduler[0].email}"
}


resource "google_cloud_run_v2_job_iam_member" "scheduler_retention_invoker" {
  count = var.enable_retention_job ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = module.retention_job[0].job_name

  role   = "roles/run.invoker"
  member = "serviceAccount:${google_service_account.scheduler[0].email}"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_partition_manager_invoker" {
  count = var.enable_partition_manager_job ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = module.partition_manager_job[0].job_name

  role   = "roles/run.invoker"
  member = "serviceAccount:${google_service_account.scheduler[0].email}"
}

resource "google_service_account_iam_member" "scheduler_actas_runtime" {
  count = local.enable_any_scheduler ? 1 : 0

  service_account_id = module.service_accounts.runtime_service_account_name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.scheduler[0].email}"
}

resource "google_artifact_registry_repository_iam_member" "scheduler_artifact_reader" {
  count = local.enable_any_scheduler ? 1 : 0

  project    = var.project_id
  location   = var.region
  repository = module.artifact_registry.repository_name

  role   = "roles/artifactregistry.reader"
  member = "serviceAccount:${google_service_account.scheduler[0].email}"
}

resource "google_cloud_scheduler_job" "offline_check" {
  count = var.enable_scheduled_jobs ? 1 : 0

  project   = var.project_id
  region    = var.region
  name      = local.offline_scheduler_name
  schedule  = var.offline_job_schedule
  time_zone = var.scheduler_time_zone

  http_target {
    http_method = "POST"

    # Cloud Run Jobs "run" API
    uri = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${local.offline_job_name}:run"

    headers = {
      "Content-Type" = "application/json"
    }

    # Cloud Scheduler expects a base64-encoded body.
    body = base64encode("{}")

    oauth_token {
      service_account_email = google_service_account.scheduler[0].email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [
    module.offline_check_job,
    google_service_account_iam_member.scheduler_token_creator,
    google_cloud_run_v2_job_iam_member.scheduler_offline_invoker,
    google_service_account_iam_member.scheduler_actas_runtime,
    google_artifact_registry_repository_iam_member.scheduler_artifact_reader,
  ]
}

resource "google_cloud_scheduler_job" "analytics_export" {
  count = var.enable_analytics_export ? 1 : 0

  project   = var.project_id
  region    = var.region
  name      = local.analytics_scheduler_name
  schedule  = var.analytics_export_schedule
  time_zone = var.scheduler_time_zone

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${local.analytics_job_name}:run"

    headers = {
      "Content-Type" = "application/json"
    }

    body = base64encode("{}")

    oauth_token {
      service_account_email = google_service_account.scheduler[0].email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [
    module.analytics_export_job,
    google_service_account_iam_member.scheduler_token_creator,
    google_cloud_run_v2_job_iam_member.scheduler_analytics_invoker,
    google_service_account_iam_member.scheduler_actas_runtime,
    google_artifact_registry_repository_iam_member.scheduler_artifact_reader,
  ]
}

resource "google_cloud_scheduler_job" "simulation" {
  count = var.enable_simulation ? 1 : 0

  project   = var.project_id
  region    = var.region
  name      = local.simulation_scheduler_name
  schedule  = var.simulation_schedule
  time_zone = var.scheduler_time_zone

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${local.simulation_job_name}:run"

    headers = {
      "Content-Type" = "application/json"
    }

    body = base64encode("{}")

    oauth_token {
      service_account_email = google_service_account.scheduler[0].email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [
    module.simulation_job,
    google_service_account_iam_member.scheduler_token_creator,
    google_cloud_run_v2_job_iam_member.scheduler_simulation_invoker,
    google_service_account_iam_member.scheduler_actas_runtime,
    google_artifact_registry_repository_iam_member.scheduler_artifact_reader,
  ]
}


resource "google_cloud_scheduler_job" "retention" {
  count = var.enable_retention_job ? 1 : 0

  project   = var.project_id
  region    = var.region
  name      = local.retention_scheduler_name
  schedule  = var.retention_job_schedule
  time_zone = var.scheduler_time_zone

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${local.retention_job_name}:run"

    headers = {
      "Content-Type" = "application/json"
    }

    body = base64encode("{}")

    oauth_token {
      service_account_email = google_service_account.scheduler[0].email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [
    module.retention_job,
    google_service_account_iam_member.scheduler_token_creator,
    google_cloud_run_v2_job_iam_member.scheduler_retention_invoker,
    google_service_account_iam_member.scheduler_actas_runtime,
    google_artifact_registry_repository_iam_member.scheduler_artifact_reader,
  ]
}

resource "google_cloud_scheduler_job" "partition_manager" {
  count = var.enable_partition_manager_job ? 1 : 0

  project   = var.project_id
  region    = var.region
  name      = local.partition_manager_scheduler_name
  schedule  = var.partition_manager_job_schedule
  time_zone = var.scheduler_time_zone

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${local.partition_manager_job_name}:run"

    headers = {
      "Content-Type" = "application/json"
    }

    body = base64encode("{}")

    oauth_token {
      service_account_email = google_service_account.scheduler[0].email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [
    module.partition_manager_job,
    google_service_account_iam_member.scheduler_token_creator,
    google_cloud_run_v2_job_iam_member.scheduler_partition_manager_invoker,
    google_service_account_iam_member.scheduler_actas_runtime,
    google_artifact_registry_repository_iam_member.scheduler_artifact_reader,
  ]
}
