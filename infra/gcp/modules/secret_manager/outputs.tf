output "secret_ids" {
  description = "Secret resource IDs by secret_id."
  value       = { for k, s in google_secret_manager_secret.secrets : k => s.id }
}

output "secret_names" {
  description = "Secret resource names by secret_id."
  value       = { for k, s in google_secret_manager_secret.secrets : k => s.name }
}
