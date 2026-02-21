# Staging posture (secure + simulated telemetry)
# - Private IAM-only Cloud Run endpoint (no unauthenticated access)
# - Demo fleet bootstrap ENABLED (explicit opt-in) so simulation has devices
# - Synthetic telemetry generator job ENABLED

env = "stage"

allow_unauthenticated = false

# Service-level admin auth: since this profile is private IAM-only, do not require browser-held keys.
admin_auth_mode = "none"

# Explicit opt-in: allow demo bootstrap in non-dev environments.
allow_demo_in_non_dev = true

# Demo fleet bootstrap (staging only)
bootstrap_demo_device = true
demo_fleet_size       = 3

# Cost controls
min_instances = 0
max_instances = 2

# Jobs
enable_migration_job  = true
enable_scheduled_jobs = true
offline_job_schedule  = "*/5 * * * *"

# Simulation (synthetic telemetry)
enable_simulation            = true
simulation_schedule          = "*/1 * * * *"
simulation_points_per_device = 1

# Managed Cloud SQL
enable_cloud_sql             = true
cloudsql_tier                = "db-g1-small"
cloudsql_deletion_protection = false

# Optional lanes (default OFF)
enable_pubsub_ingest    = false
enable_analytics_export = false

# Keep VPC connector OFF unless you must reach private IP resources
enable_vpc_connector = false

# Retention / compaction
enable_retention_job   = true
retention_job_schedule = "30 3 * * *"
telemetry_retention_days  = 14
quarantine_retention_days = 14
