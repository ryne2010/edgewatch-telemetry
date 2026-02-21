# Production-style IoT posture (staging):
# - Public ingest service (device-token auth in-app)
# - No admin routes on the public service
# - Separate private admin service protected by Cloud Run IAM

env          = "stage"
service_name = "edgewatch-stage"

# Public ingest service
# Harden the public surface: no UI, no read endpoints
enable_ui               = false
enable_read_routes      = false
enable_ingest_routes    = true
allow_unauthenticated   = true
allow_public_in_non_dev = true

# Remove admin endpoints from the public surface
enable_admin_routes = false

# Still enable simulation in staging
bootstrap_demo_device = false
enable_simulation     = true

# Deploy a separate admin service for operators
enable_admin_service          = true
admin_service_name            = "edgewatch-stage-admin"
admin_allow_unauthenticated   = false
admin_service_admin_auth_mode = "none"

# Recommended: use Workspace group-based IAM.
# workspace_domain = "example.com"
# group_prefix     = "gkp"
