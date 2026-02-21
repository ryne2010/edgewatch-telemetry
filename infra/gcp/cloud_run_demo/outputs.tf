output "service_url" {
  description = "Cloud Run service URL."
  value       = module.cloud_run.service_url
}

output "admin_service_url" {
  description = "Cloud Run admin service URL (if enable_admin_service=true)."
  value       = try(module.cloud_run_admin[0].service_url, null)
}

output "dashboard_service_url" {
  description = "Cloud Run dashboard service URL (if enable_dashboard_service=true)."
  value       = try(module.cloud_run_dashboard[0].service_url, null)
}

output "dashboard_iap_url" {
  description = "Dashboard IAP URL (if enable_dashboard_iap=true)."
  value       = var.enable_dashboard_iap ? "https://${var.dashboard_iap_domain}" : null
}

output "admin_iap_url" {
  description = "Admin IAP URL (if enable_admin_iap=true)."
  value       = var.enable_admin_iap ? "https://${var.admin_iap_domain}" : null
}

output "runtime_service_account" {
  description = "Cloud Run runtime service account email."
  value       = module.service_accounts.runtime_service_account_email
}

output "database_url_secret" {
  description = "Secret Manager secret name for DATABASE_URL."
  value       = module.secrets.secret_names["edgewatch-database-url"]
}

output "admin_api_key_secret" {
  description = "Secret Manager secret name for ADMIN_API_KEY."
  value       = module.secrets.secret_names["edgewatch-admin-api-key"]
}

output "cloudsql_instance_name" {
  description = "Cloud SQL instance name when enabled."
  value       = try(module.cloud_sql_postgres[0].instance_name, null)
}

output "cloudsql_connection_name" {
  description = "Cloud SQL connection name when enabled."
  value       = try(module.cloud_sql_postgres[0].connection_name, null)
}

output "monitoring_dashboard_name" {
  description = "Monitoring dashboard resource name (if enabled)."
  value       = try(google_monitoring_dashboard.cloudrun[0].id, null)
}

output "alert_policy_5xx_name" {
  description = "Alert policy resource name (if enabled)."
  value       = try(google_monitoring_alert_policy.cloudrun_5xx[0].name, null)
}

output "alert_policy_latency_p95_name" {
  description = "Alert policy resource name (if enabled)."
  value       = try(google_monitoring_alert_policy.cloudrun_latency_p95[0].name, null)
}


# --- Scheduled job outputs (optional) ---

output "offline_check_job_name" {
  description = "Cloud Run Job name for offline checks (if enabled)."
  value       = try(module.offline_check_job[0].job_name, null)
}

output "offline_scheduler_job_name" {
  description = "Cloud Scheduler job name for offline checks (if enabled)."
  value       = try(google_cloud_scheduler_job.offline_check[0].name, null)
}

output "scheduler_service_account" {
  description = "Service account used by Cloud Scheduler to run jobs (if enabled)."
  value       = try(google_service_account.scheduler[0].email, null)
}


output "migration_job_name" {
  description = "Cloud Run Job name for DB migrations (if enabled)."
  value       = try(module.migrate_job[0].job_name, null)
}

output "pubsub_topic_name" {
  description = "Pub/Sub topic name for ingest batches (if enabled)."
  value       = try(google_pubsub_topic.telemetry_raw[0].name, null)
}

output "pubsub_subscription_name" {
  description = "Pub/Sub push subscription name (if enabled)."
  value       = try(google_pubsub_subscription.telemetry_raw_push[0].name, null)
}

output "analytics_export_job_name" {
  description = "Cloud Run Job name for analytics export (if enabled)."
  value       = try(module.analytics_export_job[0].job_name, null)
}

output "analytics_export_scheduler_name" {
  description = "Cloud Scheduler job name for analytics export (if enabled)."
  value       = try(google_cloud_scheduler_job.analytics_export[0].name, null)
}

output "analytics_export_bucket" {
  description = "GCS bucket used for staged analytics export files (if enabled)."
  value       = try(google_storage_bucket.analytics_export[0].name, null)
}
