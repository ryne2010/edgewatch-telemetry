resource "google_compute_network" "vpc" {
  name                    = var.network_name
  project                 = var.project_id
  auto_create_subnetworks = false
  routing_mode            = var.routing_mode
}

resource "google_compute_subnetwork" "subnets" {
  for_each = var.subnets

  name          = each.key
  project       = var.project_id
  region        = each.value.region
  network       = google_compute_network.vpc.id
  ip_cidr_range = each.value.cidr
  purpose       = lookup(each.value, "purpose", null)
  role          = lookup(each.value, "role", null)

  private_ip_google_access = lookup(each.value, "private_ip_google_access", true)
}

resource "google_vpc_access_connector" "serverless" {
  count = var.create_serverless_connector ? 1 : 0

  name          = var.serverless_connector_name
  project       = var.project_id
  region        = var.serverless_connector_region
  network       = google_compute_network.vpc.name
  ip_cidr_range = var.serverless_connector_cidr

  min_throughput = var.serverless_connector_min_throughput
  max_throughput = var.serverless_connector_max_throughput
}
