output "enabled_services" {
  description = "The list of enabled service APIs."
  value       = [for s in google_project_service.enabled : s.service]
}
