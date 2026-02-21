# Production posture (cost-min + secure)
# - Private IAM-only Cloud Run endpoint (no unauthenticated access)
# - Scale-to-zero
# - Instance caps

env = "prod"

allow_unauthenticated = false

# Service-level admin auth: since this profile is private IAM-only, do not require browser-held keys.
admin_auth_mode = "none"

# Guardrail: never bootstrap demo devices in prod
bootstrap_demo_device = false

# Cost controls
min_instances = 0
max_instances = 2

# Jobs
enable_migration_job  = true
enable_scheduled_jobs = true
offline_job_schedule  = "*/5 * * * *"

# Managed Cloud SQL (start cost-min, tune tier for production load)
enable_cloud_sql             = true
cloudsql_tier                = "db-g1-small"
cloudsql_deletion_protection = true

# Optional lanes (default OFF for cost-min posture)
enable_pubsub_ingest    = false
enable_analytics_export = false

# Keep VPC connector OFF unless you must reach private IP resources
enable_vpc_connector = false

# Retention / compaction
enable_retention_job   = true
retention_job_schedule = "30 3 * * *"
telemetry_retention_days  = 90
quarantine_retention_days = 90
