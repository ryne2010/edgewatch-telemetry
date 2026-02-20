# Public demo posture (portfolio)
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
enable_migration_job = true
enable_scheduled_jobs = true
offline_job_schedule  = "*/5 * * * *"

# Keep VPC connector OFF unless you need private networking
enable_vpc_connector = false
