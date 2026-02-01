/*
  Service-scoped logging bucket + Logs Router sink + log view.

  Why do this?
  - In "client observer" scenarios (consulting / government / regulated work), you often want
    to let stakeholders *observe* (Logs Explorer / dashboards) without granting broad project-wide logging access.
  - Cloud Logging supports "Log Views" which can be permissioned via IAM Conditions.

  Implementation pattern used here:
  1) Route *only this Cloud Run service's logs* into a dedicated log bucket via a Logs Router sink.
  2) Create a log view over that bucket.
  3) Grant the clients-observers group roles/logging.viewAccessor WITH an IAM condition pinned to that view.

  References:
  - Cloud Logging log views docs (IAM condition example): https://cloud.google.com/logging/docs/logs-views
*/

locals {
  logs_location  = "global"

  # NOTE: service_name should include env already (e.g., gkp-dev), so we do NOT suffix env again.
  logs_bucket_id = "${var.service_name}-logs"
  logs_view_id   = "${var.service_name}-view"
  logs_sink_name = "${var.service_name}-to-bucket"

  # Logs Router filter (Cloud Logging advanced filter syntax, '=' operator)
  # This is *not* the same syntax as Cloud Monitoring time series filters.
  service_logs_router_filter = join(" AND ", [
    "resource.type = \"cloud_run_revision\"",
    "resource.labels.service_name = \"${var.service_name}\"",
    "resource.labels.location = \"${var.region}\"",
  ])

  # Log view filters are intentionally restricted (SOURCE + resource.type + LOG_ID).
  # Because the bucket receives only this service's logs (via the sink), we can keep the view filter simple.
  service_log_view_filter = "SOURCE(\"projects/${var.project_id}\") AND resource.type = \"cloud_run_revision\""
}

resource "google_logging_project_bucket_config" "service_logs" {
  count = (var.enable_observability && var.enable_log_views) ? 1 : 0

  project        = var.project_id
  location       = local.logs_location
  bucket_id      = local.logs_bucket_id
  retention_days = var.log_retention_days
  description    = "Service-scoped logs for ${var.service_name} (${var.env})"

  # Analytics isn't required; we enable it to support faster queries & richer UX where available.
  enable_analytics = true
}

resource "google_logging_project_sink" "service_to_bucket" {
  count = (var.enable_observability && var.enable_log_views) ? 1 : 0

  project = var.project_id
  name    = local.logs_sink_name

  # Destination format for log buckets:
  # logging.googleapis.com/projects/<PROJECT_ID>/locations/<LOCATION>/buckets/<BUCKET_ID>
  destination = "logging.googleapis.com/${google_logging_project_bucket_config.service_logs[0].id}"

  filter                = local.service_logs_router_filter
  unique_writer_identity = true
}

# The sink uses a dedicated service account identity; grant it permission to write into buckets.
resource "google_project_iam_member" "sink_bucket_writer" {
  count = (var.enable_observability && var.enable_log_views) ? 1 : 0

  project = var.project_id
  role    = "roles/logging.bucketWriter"
  member  = google_logging_project_sink.service_to_bucket[0].writer_identity
}

resource "google_logging_log_view" "service_view" {
  count = (var.enable_observability && var.enable_log_views) ? 1 : 0

  bucket      = google_logging_project_bucket_config.service_logs[0].id
  name        = local.logs_view_id
  description = "Log view for ${var.service_name} (scoped bucket + least-privilege access)"
  filter      = local.service_log_view_filter
}

output "service_log_view_resource_name" {
  description = "Full resource name used in IAM Conditions for roles/logging.viewAccessor."
  value       = (var.enable_observability && var.enable_log_views) ? google_logging_log_view.service_view[0].id : null
}
