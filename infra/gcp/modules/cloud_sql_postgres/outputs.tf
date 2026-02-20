output "instance_name" {
  description = "Cloud SQL instance name."
  value       = google_sql_database_instance.postgres.name
}

output "connection_name" {
  description = "Cloud SQL connection name (PROJECT:REGION:INSTANCE)."
  value       = google_sql_database_instance.postgres.connection_name
}

output "database_name" {
  description = "Application database name."
  value       = google_sql_database.app.name
}

output "user_name" {
  description = "Application database user."
  value       = google_sql_user.app.name
}

output "user_password" {
  description = "Application database user password."
  value       = var.user_password
  sensitive   = true
}
