locals {
  ingest_edge_resource_prefix = substr(
    replace(var.service_name, "_", "-"),
    0,
    30,
  )
  ingest_edge_rate_limit_key = upper(trimspace(var.ingest_edge_rate_limit_enforce_on_key))
}

# Public ingest edge perimeter (HTTPS LB + Cloud Armor throttling)
resource "google_compute_security_policy" "ingest_edge" {
  count = var.enable_ingest_edge_protection ? 1 : 0
  name  = "${local.ingest_edge_resource_prefix}-edge-armor"

  description = "Cloud Armor edge policy for public ingest service"

  dynamic "rule" {
    for_each = length(var.ingest_edge_allowlist_cidrs) > 0 ? [1] : []
    content {
      action      = "allow"
      priority    = 100
      description = "Optional trusted source allowlist (bypasses throttle)"

      match {
        versioned_expr = "SRC_IPS_V1"
        config {
          src_ip_ranges = var.ingest_edge_allowlist_cidrs
        }
      }
    }
  }

  rule {
    action      = "throttle"
    priority    = 200
    description = "Per-key edge throttle for public ingest"
    preview     = var.ingest_edge_rate_limit_preview

    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }

    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = local.ingest_edge_rate_limit_key

      rate_limit_threshold {
        count        = var.ingest_edge_rate_limit_count
        interval_sec = var.ingest_edge_rate_limit_interval_sec
      }
    }
  }

  # Explicit default rule keeps policy behavior obvious in reviews.
  rule {
    action      = "allow"
    priority    = 2147483647
    description = "Default allow (after specific edge-protection rules)"

    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
  }
}

resource "google_compute_global_address" "ingest_edge" {
  count = var.enable_ingest_edge_protection ? 1 : 0
  name  = "${local.ingest_edge_resource_prefix}-edge-ip"
}

resource "google_compute_managed_ssl_certificate" "ingest_edge" {
  count = var.enable_ingest_edge_protection ? 1 : 0
  name  = "${local.ingest_edge_resource_prefix}-edge-cert"

  managed {
    domains = [var.ingest_edge_domain]
  }
}

resource "google_compute_region_network_endpoint_group" "ingest_edge" {
  count = var.enable_ingest_edge_protection ? 1 : 0
  name  = "${local.ingest_edge_resource_prefix}-edge-neg"

  region                = var.region
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = module.cloud_run.service_name
  }
}

resource "google_compute_backend_service" "ingest_edge" {
  count = var.enable_ingest_edge_protection ? 1 : 0
  name  = "${local.ingest_edge_resource_prefix}-edge-be"

  protocol              = "HTTP"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  timeout_sec           = 30
  security_policy       = google_compute_security_policy.ingest_edge[0].id

  backend {
    group = google_compute_region_network_endpoint_group.ingest_edge[0].id
  }
}

resource "google_compute_url_map" "ingest_edge" {
  count = var.enable_ingest_edge_protection ? 1 : 0
  name  = "${local.ingest_edge_resource_prefix}-edge-map"

  default_service = google_compute_backend_service.ingest_edge[0].id
}

resource "google_compute_target_https_proxy" "ingest_edge" {
  count = var.enable_ingest_edge_protection ? 1 : 0
  name  = "${local.ingest_edge_resource_prefix}-edge-proxy"

  url_map          = google_compute_url_map.ingest_edge[0].id
  ssl_certificates = [google_compute_managed_ssl_certificate.ingest_edge[0].id]
}

resource "google_compute_global_forwarding_rule" "ingest_edge" {
  count = var.enable_ingest_edge_protection ? 1 : 0
  name  = "${local.ingest_edge_resource_prefix}-edge-fr"

  ip_address            = google_compute_global_address.ingest_edge[0].id
  target                = google_compute_target_https_proxy.ingest_edge[0].id
  load_balancing_scheme = "EXTERNAL_MANAGED"
  port_range            = "443"
}
