output "service_url" {
  description = "Cloud Run service URL."
  value       = module.cloud_run.service_url
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

output "monitoring_dashboard_name" {
  description = "Monitoring dashboard resource name (if enabled)."
  value       = try(google_monitoring_dashboard.cloudrun[0].name, null)
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
