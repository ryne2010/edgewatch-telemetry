output "service_uri" {
  value       = google_cloud_run_v2_service.service.uri
  description = "Cloud Run service URL."
}

output "service_name" {
  value       = google_cloud_run_v2_service.service.name
  description = "Cloud Run service resource name."
}
