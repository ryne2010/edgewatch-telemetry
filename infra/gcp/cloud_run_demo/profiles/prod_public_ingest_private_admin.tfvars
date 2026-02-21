# Production-style IoT posture (prod):
# - Public ingest service (device-token auth in-app)
# - No admin routes on the public service
# - Separate private admin service protected by Cloud Run IAM

env          = "prod"
service_name = "edgewatch-prod"

# Public ingest service
# Harden the public surface: no UI, no read endpoints
enable_ui               = false
enable_read_routes      = false
enable_ingest_routes    = true
allow_unauthenticated   = true
allow_public_in_non_dev = true

# Remove admin endpoints from the public surface
enable_admin_routes = false

# Demo bootstrap should be off in production
bootstrap_demo_device = false

# Optional: export lane, retention jobs, etc can be enabled per your environment.

# Deploy a separate admin service for operators
enable_admin_service          = true
admin_service_name            = "edgewatch-prod-admin"
admin_allow_unauthenticated   = false
admin_service_admin_auth_mode = "none"

# Optional: put admin behind IAP (requires domain + OAuth client + allowlist).
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
