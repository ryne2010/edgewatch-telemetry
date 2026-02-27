# Production-style IoT posture (prod) with least-privilege separation:
# - Public ingest service (device-token auth in-app)
# - Private dashboard service (UI + read endpoints only)
# - Private admin service (UI + admin endpoints)

env          = "prod"
service_name = "edgewatch-prod"

# --- Public ingest service ---------------------------------------------------
allow_unauthenticated   = true
allow_public_in_non_dev = true

# Optional: Cloud Armor edge protection in front of public ingest.
# enable_ingest_edge_protection = true
# ingest_edge_domain            = "ingest.example.com"
# ingest_edge_rate_limit_count  = 1200
# ingest_edge_rate_limit_interval_sec = 60
# ingest_edge_rate_limit_enforce_on_key = "IP"
# ingest_edge_allowlist_cidrs = [
#   "203.0.113.0/24",
# ]

# Harden the public surface: ingest only.
enable_ui            = false
enable_read_routes   = false
enable_ingest_routes = true

# No admin endpoints on the public surface.
enable_admin_routes = false

# --- Production defaults -----------------------------------------------------
bootstrap_demo_device = false
enable_simulation     = false
# Set true only when explicitly opting into synthetic telemetry in prod.
simulation_allow_in_prod = false

# --- Private dashboard service ----------------------------------------------
enable_dashboard_service        = true
dashboard_service_name          = "edgewatch-prod-dashboard"
dashboard_allow_unauthenticated = false

# --- Private admin service ---------------------------------------------------
enable_admin_service          = true
admin_service_name            = "edgewatch-prod-admin"
admin_allow_unauthenticated   = false
admin_service_admin_auth_mode = "none"

# Optional: put dashboard/admin behind IAP (requires domains + OAuth clients + allowlists).
# enable_dashboard_iap               = true
# dashboard_iap_domain               = "dashboard.example.com"
# dashboard_iap_oauth2_client_id     = "REPLACE_ME"
# dashboard_iap_oauth2_client_secret = "REPLACE_ME"
# dashboard_iap_allowlist_members = [
#   "group:gkp-engineers@example.com",
#   "group:gkp-clients-observers@example.com",
# ]
#
# enable_admin_iap               = true
# admin_iap_domain               = "admin.example.com"
# admin_iap_oauth2_client_id     = "REPLACE_ME"
# admin_iap_oauth2_client_secret = "REPLACE_ME"
# admin_iap_allowlist_members = [
#   "group:gkp-engineers@example.com",
#   "group:gkp-engineers-min@example.com",
# ]

# Recommended: use Workspace group-based IAM.
# workspace_domain = "example.com"
# group_prefix     = "gkp"
