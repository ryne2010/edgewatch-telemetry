data "google_project" "current" {
  project_id = var.project_id
}

locals {
  iap_service_account_member = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-iap.iam.gserviceaccount.com"
  dashboard_iap_resource_prefix = substr(
    replace(local.dashboard_service_name_effective, "_", "-"),
    0,
    35,
  )
  admin_iap_resource_prefix = substr(
    replace(local.admin_service_name_effective, "_", "-"),
    0,
    35,
  )
}

# Dashboard IAP perimeter (HTTPS LB + IAP + allowlist)
resource "google_compute_global_address" "dashboard_iap" {
  count = var.enable_dashboard_iap ? 1 : 0
  name  = "${local.dashboard_iap_resource_prefix}-iap-ip"
}

resource "google_compute_managed_ssl_certificate" "dashboard_iap" {
  count = var.enable_dashboard_iap ? 1 : 0
  name  = "${local.dashboard_iap_resource_prefix}-iap-cert"

  managed {
    domains = [var.dashboard_iap_domain]
  }
}

resource "google_compute_region_network_endpoint_group" "dashboard_iap" {
  count = var.enable_dashboard_iap ? 1 : 0
  name  = "${local.dashboard_iap_resource_prefix}-iap-neg"

  region                = var.region
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = module.cloud_run_dashboard[0].service_name
  }
}

resource "google_compute_backend_service" "dashboard_iap" {
  count = var.enable_dashboard_iap ? 1 : 0
  name  = "${local.dashboard_iap_resource_prefix}-iap-be"

  protocol              = "HTTP"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  timeout_sec           = 30

  backend {
    group = google_compute_region_network_endpoint_group.dashboard_iap[0].id
  }

  iap {
    oauth2_client_id     = var.dashboard_iap_oauth2_client_id
    oauth2_client_secret = var.dashboard_iap_oauth2_client_secret
  }
}

resource "google_compute_url_map" "dashboard_iap" {
  count = var.enable_dashboard_iap ? 1 : 0
  name  = "${local.dashboard_iap_resource_prefix}-iap-map"

  default_service = google_compute_backend_service.dashboard_iap[0].id
}

resource "google_compute_target_https_proxy" "dashboard_iap" {
  count = var.enable_dashboard_iap ? 1 : 0
  name  = "${local.dashboard_iap_resource_prefix}-iap-proxy"

  url_map          = google_compute_url_map.dashboard_iap[0].id
  ssl_certificates = [google_compute_managed_ssl_certificate.dashboard_iap[0].id]
}

resource "google_compute_global_forwarding_rule" "dashboard_iap" {
  count = var.enable_dashboard_iap ? 1 : 0
  name  = "${local.dashboard_iap_resource_prefix}-iap-fr"

  ip_address            = google_compute_global_address.dashboard_iap[0].id
  target                = google_compute_target_https_proxy.dashboard_iap[0].id
  load_balancing_scheme = "EXTERNAL_MANAGED"
  port_range            = "443"
}

resource "google_iap_web_backend_service_iam_binding" "dashboard_iap_allowlist" {
  count = var.enable_dashboard_iap ? 1 : 0

  project             = var.project_id
  web_backend_service = google_compute_backend_service.dashboard_iap[0].name
  role                = "roles/iap.httpsResourceAccessor"
  members             = var.dashboard_iap_allowlist_members
}

resource "google_cloud_run_v2_service_iam_member" "dashboard_iap_invoker" {
  count = var.enable_dashboard_iap ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = module.cloud_run_dashboard[0].service_name

  role   = "roles/run.invoker"
  member = local.iap_service_account_member
}

# Admin IAP perimeter (HTTPS LB + IAP + allowlist)
resource "google_compute_global_address" "admin_iap" {
  count = var.enable_admin_iap ? 1 : 0
  name  = "${local.admin_iap_resource_prefix}-iap-ip"
}

resource "google_compute_managed_ssl_certificate" "admin_iap" {
  count = var.enable_admin_iap ? 1 : 0
  name  = "${local.admin_iap_resource_prefix}-iap-cert"

  managed {
    domains = [var.admin_iap_domain]
  }
}

resource "google_compute_region_network_endpoint_group" "admin_iap" {
  count = var.enable_admin_iap ? 1 : 0
  name  = "${local.admin_iap_resource_prefix}-iap-neg"

  region                = var.region
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = module.cloud_run_admin[0].service_name
  }
}

resource "google_compute_backend_service" "admin_iap" {
  count = var.enable_admin_iap ? 1 : 0
  name  = "${local.admin_iap_resource_prefix}-iap-be"

  protocol              = "HTTP"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  timeout_sec           = 30

  backend {
    group = google_compute_region_network_endpoint_group.admin_iap[0].id
  }

  iap {
    oauth2_client_id     = var.admin_iap_oauth2_client_id
    oauth2_client_secret = var.admin_iap_oauth2_client_secret
  }
}

resource "google_compute_url_map" "admin_iap" {
  count = var.enable_admin_iap ? 1 : 0
  name  = "${local.admin_iap_resource_prefix}-iap-map"

  default_service = google_compute_backend_service.admin_iap[0].id
}

resource "google_compute_target_https_proxy" "admin_iap" {
  count = var.enable_admin_iap ? 1 : 0
  name  = "${local.admin_iap_resource_prefix}-iap-proxy"

  url_map          = google_compute_url_map.admin_iap[0].id
  ssl_certificates = [google_compute_managed_ssl_certificate.admin_iap[0].id]
}

resource "google_compute_global_forwarding_rule" "admin_iap" {
  count = var.enable_admin_iap ? 1 : 0
  name  = "${local.admin_iap_resource_prefix}-iap-fr"

  ip_address            = google_compute_global_address.admin_iap[0].id
  target                = google_compute_target_https_proxy.admin_iap[0].id
  load_balancing_scheme = "EXTERNAL_MANAGED"
  port_range            = "443"
}

resource "google_iap_web_backend_service_iam_binding" "admin_iap_allowlist" {
  count = var.enable_admin_iap ? 1 : 0

  project             = var.project_id
  web_backend_service = google_compute_backend_service.admin_iap[0].name
  role                = "roles/iap.httpsResourceAccessor"
  members             = var.admin_iap_allowlist_members
}

resource "google_cloud_run_v2_service_iam_member" "admin_iap_invoker" {
  count = var.enable_admin_iap ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = module.cloud_run_admin[0].service_name

  role   = "roles/run.invoker"
  member = local.iap_service_account_member
}
