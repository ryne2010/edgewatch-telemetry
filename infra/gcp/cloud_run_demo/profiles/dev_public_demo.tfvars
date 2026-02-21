# Public demo posture (dev)
# - Public Cloud Run endpoint
# - Scale-to-zero
# - Max instances capped to control cost

env = "dev"

allow_unauthenticated = true

# Demo bootstrap (dev-only)
bootstrap_demo_device = true
demo_fleet_size       = 3

# Cost controls
min_instances = 0
max_instances = 1

# Cost-min demo sizing. If you see OOMs under load, bump these back to 512Mi.
service_memory = "256Mi"
job_memory     = "256Mi"

# Jobs
enable_migration_job  = true
enable_scheduled_jobs = true
offline_job_schedule  = "*/5 * * * *"

# Simulation (synthetic telemetry)
enable_simulation           = true
simulation_schedule         = "*/1 * * * *"
simulation_points_per_device = 1

# Managed Cloud SQL (minimal-cost defaults)
enable_cloud_sql             = true
cloudsql_tier                = "db-f1-micro"
cloudsql_deletion_protection = false

# Optional lanes (default OFF for cost-min posture)
enable_pubsub_ingest    = false
enable_analytics_export = false

# Keep VPC connector OFF unless you need private networking
enable_vpc_connector = false

# Retention / compaction
enable_retention_job   = true
retention_job_schedule = "30 3 * * *"
telemetry_retention_days  = 7
quarantine_retention_days = 7
