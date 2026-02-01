output "network_name" {
  value       = google_compute_network.vpc.name
  description = "VPC name."
}

output "network_id" {
  value       = google_compute_network.vpc.id
  description = "VPC resource ID."
}

output "subnet_ids" {
  value       = { for k, s in google_compute_subnetwork.subnets : k => s.id }
  description = "Subnetwork IDs by name."
}

output "serverless_connector_id" {
  value       = var.create_serverless_connector ? google_vpc_access_connector.serverless[0].id : null
  description = "Serverless VPC Access connector ID (if created)."
}
