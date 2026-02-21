# Production-style IoT posture (prod) with least-privilege separation:
# - Public ingest service (device-token auth in-app)
# - Private dashboard service (UI + read endpoints only)
# - Private admin service (UI + admin endpoints)

env          = "prod"
service_name = "edgewatch-prod"

# --- Public ingest service ---------------------------------------------------
allow_unauthenticated   = true
allow_public_in_non_dev = true

# Harden the public surface: ingest only.
enable_ui            = false
enable_read_routes   = false
enable_ingest_routes = true

# No admin endpoints on the public surface.
enable_admin_routes = false

# --- Production defaults -----------------------------------------------------
bootstrap_demo_device = false

# --- Private dashboard service ----------------------------------------------
enable_dashboard_service        = true
dashboard_service_name          = "edgewatch-prod-dashboard"
dashboard_allow_unauthenticated = false

# --- Private admin service ---------------------------------------------------
enable_admin_service          = true
admin_service_name            = "edgewatch-prod-admin"
admin_allow_unauthenticated   = false
admin_service_admin_auth_mode = "none"

# Recommended: use Workspace group-based IAM.
# workspace_domain = "example.com"
# group_prefix     = "gkp"
