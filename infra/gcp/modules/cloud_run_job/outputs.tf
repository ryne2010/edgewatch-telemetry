output "job_name" {
  description = "Cloud Run Job name."
  value       = google_cloud_run_v2_job.job.name
}

output "job_id" {
  description = "Full job resource ID."
  value       = google_cloud_run_v2_job.job.id
}
