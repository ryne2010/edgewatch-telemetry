output "repository_name" {
  value       = google_artifact_registry_repository.repo.name
  description = "Full resource name."
}

output "docker_repository" {
  description = "Docker repository hostname/path (e.g., us-central1-docker.pkg.dev/PROJECT/REPO)."
  value       = "${var.location}-docker.pkg.dev/${var.project_id}/${var.repository_id}"
}
