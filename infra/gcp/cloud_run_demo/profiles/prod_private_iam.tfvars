# Production posture (cost-min + secure)
# - Private IAM-only Cloud Run endpoint (no unauthenticated access)
# - Scale-to-zero
# - Instance caps

env = "prod"

allow_unauthenticated = false

# Guardrail: never bootstrap demo devices in prod
bootstrap_demo_device = false

# Cost controls
min_instances = 0
max_instances = 2

# Jobs
enable_migration_job  = true
enable_scheduled_jobs = true
offline_job_schedule  = "*/5 * * * *"

# Keep VPC connector OFF unless you must reach private IP resources
enable_vpc_connector = false
