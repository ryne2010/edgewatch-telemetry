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
