output "workload_identity_provider" {
  description = "Workload Identity Provider resource name (use in GitHub Actions)."
  value       = google_iam_workload_identity_pool_provider.provider.name
}

output "workload_identity_pool" {
  description = "Workload Identity Pool resource name."
  value       = google_iam_workload_identity_pool.pool.name
}
