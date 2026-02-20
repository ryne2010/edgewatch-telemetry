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
  offline_job_name        = "edgewatch-offline-check-${var.env}"
  offline_scheduler_name  = "edgewatch-offline-check-${var.env}"
  migrate_job_name        = "edgewatch-migrate-${var.env}"
}

resource "google_service_account" "scheduler" {
  count = var.enable_scheduled_jobs ? 1 : 0

  project      = var.project_id
  account_id   = "sa-edgewatch-scheduler-${var.env}"
  display_name = "EdgeWatch Scheduler (${var.env})"
}

# Allow the Cloud Scheduler service agent to mint tokens for the scheduler SA.
resource "google_service_account_iam_member" "scheduler_token_creator" {
  count = var.enable_scheduled_jobs ? 1 : 0

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

  vpc_connector_id = var.enable_vpc_connector ? module.network[0].serverless_connector_id : null
  vpc_egress       = var.vpc_egress

  cpu    = var.job_cpu
  memory = var.job_memory

  labels = local.labels
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

  vpc_connector_id = var.enable_vpc_connector ? module.network[0].serverless_connector_id : null
  vpc_egress       = var.vpc_egress

  cpu    = var.job_cpu
  memory = var.job_memory

  labels = local.labels
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

resource "google_service_account_iam_member" "scheduler_actas_runtime" {
  count = var.enable_scheduled_jobs ? 1 : 0

  service_account_id = module.service_accounts.runtime_service_account_name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.scheduler[0].email}"
}

resource "google_artifact_registry_repository_iam_member" "scheduler_artifact_reader" {
  count = var.enable_scheduled_jobs ? 1 : 0

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
