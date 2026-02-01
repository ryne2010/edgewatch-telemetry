output "runtime_service_account_email" {
  value       = google_service_account.runtime.email
  description = "Runtime service account email."
}

output "ci_service_account_email" {
  value       = var.create_ci_account ? google_service_account.ci[0].email : null
  description = "CI service account email (if created)."
}
