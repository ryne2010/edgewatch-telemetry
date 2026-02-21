variable "project_id" {
  type        = string
  description = "GCP project ID."
}

variable "region" {
  type        = string
  description = "GCP region."
  default     = "us-central1"
}

variable "env" {
  type        = string
  description = "Deployment environment label (dev|stage|prod). Used for naming + labels."
  default     = "dev"

  validation {
    condition     = contains(["dev", "stage", "prod"], var.env)
    error_message = "env must be one of dev|stage|prod."
  }
}

variable "service_name" {
  type        = string
  description = "Cloud Run service name."
  default     = "edgewatch-dev"
}

variable "artifact_repo_name" {
  type        = string
  description = "Artifact Registry repository name."
  default     = "edgewatch"
}

variable "image" {
  type        = string
  description = "Container image URI."
}

# --- Public vs private posture ------------------------------------------------

variable "allow_public_in_non_dev" {
  type        = bool
  description = <<EOT
If true, you may set allow_unauthenticated=true in stage/prod.

Guardrail:
- For demo apps it's common to run a public Cloud Run service.
- For a production posture, default to private IAM-only invocations.

This flag forces an explicit acknowledgment before making non-dev environments public.
EOT
  default     = false
}

variable "allow_public_admin_noauth" {
  type        = bool
  description = "Acknowledge risk: allow admin_auth_mode=none (no admin key) on a public Cloud Run service. NOT recommended."
  default     = false
}

variable "allow_unauthenticated" {
  type        = bool
  description = "Whether the Cloud Run service is public."
  default     = false

  validation {
    condition     = var.env == "dev" || var.allow_unauthenticated == false || var.allow_public_in_non_dev == true
    error_message = "Refusing to make stage/prod public: set allow_public_in_non_dev=true to acknowledge the risk/cost posture."
  }
}


# --- Admin surface + split-admin deployment pattern -------------------------

variable "enable_admin_routes" {
  type        = bool
  description = "If false, do not mount /api/v1/admin/* routes on the primary service."
  default     = true
}


# --- Route surface toggles ---------------------------------------------------
#
# These toggles let you deploy the same container image as multiple Cloud Run
# services with different responsibilities (recommended for IoT/edge posture).
#
# Examples:
# - Public ingest service: ingest only (no UI, no read endpoints, no admin)
# - Private dashboard service: UI + read endpoints (no ingest, no admin)
# - Private admin service: UI + admin endpoints (optionally read endpoints)

variable "enable_ui" {
  type        = bool
  description = "Whether the primary service should serve the web UI (static files from /web/dist)."
  default     = true
}

variable "enable_ingest_routes" {
  type        = bool
  description = "Whether the primary service should mount ingest routes (/api/v1/ingest, device policy, pubsub push)."
  default     = true
}

variable "enable_read_routes" {
  type        = bool
  description = "Whether the primary service should mount read-only dashboard routes (/api/v1/devices, /api/v1/alerts, /api/v1/contracts)."
  default     = true
}

variable "admin_auth_mode" {
  type        = string
  description = "Admin auth mode for the primary service: key (X-Admin-Key) or none (trust perimeter)."
  default     = "key"

  validation {
    condition     = contains(["key", "none"], var.admin_auth_mode)
    error_message = "admin_auth_mode must be one of: key, none."
  }


  validation {
    condition     = !(var.allow_unauthenticated && var.enable_admin_routes && var.admin_auth_mode == "none") || var.allow_public_admin_noauth
    error_message = "Refusing to run a public service with enable_admin_routes=true and admin_auth_mode=none. Disable admin routes, set admin_auth_mode=key, or set allow_public_admin_noauth=true to acknowledge the risk."
  }

}

variable "enable_admin_service" {
  type        = bool
  description = <<EOT
If true, deploy a second Cloud Run service that includes admin routes (recommended for a production IoT posture).

Pattern:
- public ingest service: ENABLE_ADMIN_ROUTES=0
- private admin service: ENABLE_ADMIN_ROUTES=1, ADMIN_AUTH_MODE=none (protected by Cloud Run IAM/IAP)
EOT
  default     = false
}

variable "admin_service_name" {
  type        = string
  description = "Optional admin Cloud Run service name override. Null derives from service_name."
  default     = null
}

variable "admin_allow_unauthenticated" {
  type        = bool
  description = "Whether the admin service is public (NOT recommended)."
  default     = false

  validation {
    condition     = var.env == "dev" || var.admin_allow_unauthenticated == false || var.allow_public_in_non_dev == true
    error_message = "Refusing to make stage/prod admin service public: set allow_public_in_non_dev=true to acknowledge the risk/cost posture."
  }
}

variable "admin_service_admin_auth_mode" {
  type        = string
  description = "Admin auth mode for the admin service (usually none when protected by IAM/IAP)."
  default     = "none"

  validation {
    condition     = contains(["key", "none"], var.admin_service_admin_auth_mode)
    error_message = "admin_service_admin_auth_mode must be one of: key, none."
  }


  validation {
    condition     = !(var.enable_admin_service && var.admin_allow_unauthenticated && var.admin_service_admin_auth_mode == "none") || var.allow_public_admin_noauth
    error_message = "Refusing to run a public admin service with admin_service_admin_auth_mode=none. Keep admin private (recommended) or set allow_public_admin_noauth=true to acknowledge the risk."
  }

}


# --- Optional: separate dashboard service (read-only UI) ---------------------
#
# Design goal: least privilege.
# - Many users/operators should access the dashboard (read endpoints + UI)
# - Fewer users should access provisioning/debug endpoints (admin)
#
# Pattern:
# - Public ingest service: ENABLE_UI=0, ENABLE_READ_ROUTES=0, ENABLE_ADMIN_ROUTES=0
# - Private dashboard service: ENABLE_UI=1, ENABLE_READ_ROUTES=1, ENABLE_ADMIN_ROUTES=0
# - Private admin service: ENABLE_UI=1, ENABLE_ADMIN_ROUTES=1

variable "enable_dashboard_service" {
  type        = bool
  description = "If true, deploy a second Cloud Run service that serves the dashboard UI + read endpoints (no ingest, no admin)."
  default     = false
}

variable "dashboard_service_name" {
  type        = string
  description = "Optional dashboard Cloud Run service name override. Null derives from service_name."
  default     = null
}

variable "dashboard_allow_unauthenticated" {
  type        = bool
  description = "Whether the dashboard service is public (NOT recommended for stage/prod)."
  default     = false

  validation {
    condition     = var.env == "dev" || var.dashboard_allow_unauthenticated == false || var.allow_public_in_non_dev == true
    error_message = "Refusing to make stage/prod dashboard service public: set allow_public_in_non_dev=true to acknowledge the risk/cost posture."
  }
}


# --- Optional: IAP identity perimeter for dashboard/admin services ----------
#
# Design:
# - Keep ingest public if needed (IoT), while operator surfaces require Google login.
# - Put dashboard/admin behind HTTPS LB + IAP.
# - Restrict access via IAP allowlists (users/groups).

variable "enable_dashboard_iap" {
  type        = bool
  description = "If true, create HTTPS LB + IAP in front of the dashboard Cloud Run service."
  default     = false

  validation {
    condition     = !var.enable_dashboard_iap || (var.enable_dashboard_service && !var.dashboard_allow_unauthenticated)
    error_message = "enable_dashboard_iap=true requires enable_dashboard_service=true and dashboard_allow_unauthenticated=false."
  }
}

variable "dashboard_iap_domain" {
  type        = string
  description = "FQDN for the dashboard IAP HTTPS load balancer (for example: dashboard.example.com)."
  default     = null

  validation {
    condition     = !var.enable_dashboard_iap || (var.dashboard_iap_domain != null && trimspace(var.dashboard_iap_domain) != "")
    error_message = "dashboard_iap_domain is required when enable_dashboard_iap=true."
  }
}

variable "dashboard_iap_oauth2_client_id" {
  type        = string
  description = "OAuth2 client ID used by IAP for the dashboard backend."
  default     = null

  validation {
    condition = !var.enable_dashboard_iap || (
      var.dashboard_iap_oauth2_client_id != null
      && trimspace(var.dashboard_iap_oauth2_client_id) != ""
    )
    error_message = "dashboard_iap_oauth2_client_id is required when enable_dashboard_iap=true."
  }
}

variable "dashboard_iap_oauth2_client_secret" {
  type        = string
  description = "OAuth2 client secret used by IAP for the dashboard backend."
  default     = null
  sensitive   = true

  validation {
    condition = !var.enable_dashboard_iap || (
      var.dashboard_iap_oauth2_client_secret != null
      && trimspace(var.dashboard_iap_oauth2_client_secret) != ""
    )
    error_message = "dashboard_iap_oauth2_client_secret is required when enable_dashboard_iap=true."
  }
}

variable "dashboard_iap_allowlist_members" {
  type        = list(string)
  description = "Members allowed by IAP to access the dashboard backend (user:alice@example.com, group:ops@example.com)."
  default     = []

  validation {
    condition     = !var.enable_dashboard_iap || length(var.dashboard_iap_allowlist_members) > 0
    error_message = "dashboard_iap_allowlist_members must include at least one user/group when enable_dashboard_iap=true."
  }
}

variable "enable_admin_iap" {
  type        = bool
  description = "If true, create HTTPS LB + IAP in front of the admin Cloud Run service."
  default     = false

  validation {
    condition     = !var.enable_admin_iap || (var.enable_admin_service && !var.admin_allow_unauthenticated)
    error_message = "enable_admin_iap=true requires enable_admin_service=true and admin_allow_unauthenticated=false."
  }
}

variable "admin_iap_domain" {
  type        = string
  description = "FQDN for the admin IAP HTTPS load balancer (for example: admin.example.com)."
  default     = null

  validation {
    condition     = !var.enable_admin_iap || (var.admin_iap_domain != null && trimspace(var.admin_iap_domain) != "")
    error_message = "admin_iap_domain is required when enable_admin_iap=true."
  }
}

variable "admin_iap_oauth2_client_id" {
  type        = string
  description = "OAuth2 client ID used by IAP for the admin backend."
  default     = null

  validation {
    condition = !var.enable_admin_iap || (
      var.admin_iap_oauth2_client_id != null
      && trimspace(var.admin_iap_oauth2_client_id) != ""
    )
    error_message = "admin_iap_oauth2_client_id is required when enable_admin_iap=true."
  }
}

variable "admin_iap_oauth2_client_secret" {
  type        = string
  description = "OAuth2 client secret used by IAP for the admin backend."
  default     = null
  sensitive   = true

  validation {
    condition = !var.enable_admin_iap || (
      var.admin_iap_oauth2_client_secret != null
      && trimspace(var.admin_iap_oauth2_client_secret) != ""
    )
    error_message = "admin_iap_oauth2_client_secret is required when enable_admin_iap=true."
  }
}

variable "admin_iap_allowlist_members" {
  type        = list(string)
  description = "Members allowed by IAP to access the admin backend (user:alice@example.com, group:ops@example.com)."
  default     = []

  validation {
    condition     = !var.enable_admin_iap || length(var.admin_iap_allowlist_members) > 0
    error_message = "admin_iap_allowlist_members must include at least one user/group when enable_admin_iap=true."
  }
}

variable "cors_allow_origins_csv" {
  type        = string
  description = <<EOT
Optional comma-separated list of allowed origins for CORS.

When null (default), the API applies safe in-app defaults:
- dev: ["*"]
- stage/prod: []

Set this when you deploy a browser UI to a fixed domain.
EOT
  default     = null
}

variable "max_request_body_bytes" {
  type        = number
  description = "Max request body size (bytes) for write endpoints (defense-in-depth)."
  default     = 1000000
}

variable "max_points_per_request" {
  type        = number
  description = "Max number of telemetry points accepted per /api/v1/ingest request."
  default     = 5000
}

variable "rate_limit_enabled" {
  type        = bool
  description = "Enable in-app rate limiting backstops (defense-in-depth)."
  default     = true
}

variable "ingest_rate_limit_points_per_min" {
  type        = number
  description = "Device-scoped ingest rate limit (points per minute) used by the in-app limiter."
  default     = 25000
}

variable "min_instances" {
  type        = number
  description = "Minimum Cloud Run instances (0 for scale-to-zero)."
  default     = 0
}

variable "max_instances" {
  type        = number
  description = "Maximum Cloud Run instances (cost guardrail)."
  default     = 1
}

variable "service_cpu" {
  type        = string
  description = "Cloud Run service CPU limit (e.g., '1')."
  default     = "1"
}

variable "service_memory" {
  type        = string
  description = "Cloud Run service memory limit (e.g., '512Mi')."
  default     = "512Mi"
}

# --- Cloud SQL (managed PostgreSQL) ---

variable "enable_cloud_sql" {
  type        = bool
  description = "Provision a Cloud SQL Postgres instance and manage DATABASE_URL secret from Terraform."
  default     = true
}

variable "cloudsql_instance_name" {
  type        = string
  description = "Optional Cloud SQL instance name override. Null derives from service_name."
  default     = null
}

variable "cloudsql_database_version" {
  type        = string
  description = "Cloud SQL Postgres major version."
  default     = "POSTGRES_15"
}

variable "cloudsql_database_name" {
  type        = string
  description = "Application database name."
  default     = "edgewatch"
}

variable "cloudsql_user_name" {
  type        = string
  description = "Application database user name."
  default     = "edgewatch"
}

variable "cloudsql_user_password" {
  type        = string
  description = "Optional DB user password override. If null, Terraform derives a stable env-specific fallback."
  default     = null
  sensitive   = true
}

variable "cloudsql_tier" {
  type        = string
  description = "Cloud SQL machine tier. Keep shared-core for minimal cost."
  default     = "db-f1-micro"
}

variable "cloudsql_disk_size_gb" {
  type        = number
  description = "Initial Cloud SQL disk size in GB."
  default     = 10
}

variable "cloudsql_disk_type" {
  type        = string
  description = "Cloud SQL disk type."
  default     = "PD_HDD"
}

variable "cloudsql_availability_type" {
  type        = string
  description = "ZONAL (cost-min) or REGIONAL (HA)."
  default     = "ZONAL"
}

variable "cloudsql_backup_enabled" {
  type        = bool
  description = "Enable Cloud SQL backups."
  default     = true
}

variable "cloudsql_backup_start_time" {
  type        = string
  description = "Backup start time in UTC (HH:MM)."
  default     = "03:00"
}

variable "cloudsql_require_ssl" {
  type        = bool
  description = "Require SSL for direct IP DB connections."
  default     = true
}

variable "cloudsql_deletion_protection" {
  type        = bool
  description = "Protect Cloud SQL instance from accidental deletion."
  default     = false
}

variable "job_cpu" {
  type        = string
  description = "Cloud Run Job CPU limit (e.g., '1')."
  default     = "1"
}

variable "job_memory" {
  type        = string
  description = "Cloud Run Job memory limit (e.g., '512Mi')."
  default     = "512Mi"
}

variable "enable_vpc_connector" {
  type        = bool
  description = "Create and attach a Serverless VPC Access connector (NOT free)."
  default     = false
}

variable "vpc_egress" {
  type        = string
  description = "VPC egress setting when a connector is attached."
  default     = "PRIVATE_RANGES_ONLY"
}

# --- Optional: workspace IAM starter pack (Google Groups) ---

variable "workspace_domain" {
  type        = string
  description = "Google Workspace domain for group-based IAM (e.g., example.com). When empty, no group IAM bindings are created."
  default     = ""
}

variable "group_prefix" {
  type        = string
  description = "Group prefix, used to form group emails like <prefix>-engineers@<workspace_domain>."
  default     = "edgewatch"
}

# --- Optional: observability as code ---

variable "enable_observability" {
  type        = bool
  description = "Create Monitoring dashboard + alert policies (recommended)."
  default     = true
}

variable "notification_channels" {
  type        = list(string)
  description = "Optional Monitoring notification channel IDs to attach to alert policies."
  default     = []
}


# --- Staff-level hygiene toggles (recommended defaults) ---

variable "enable_project_iam" {
  type        = bool
  description = <<EOT
If true, this stack will manage *project-level* IAM bindings for your Google Groups.

Staff-level recommendation:
- Manage project-level IAM centrally in the Terraform GCP Platform Baseline repo (repo 3),
  and keep application repos focused on *app-scoped* resources.
- Leave this false unless you explicitly want this repo to be standalone.
EOT
  default     = false
}

variable "log_retention_days" {
  type        = number
  description = "Retention (days) for the service-scoped log bucket used for client log views."
  default     = 30
}

variable "enable_log_views" {
  type        = bool
  description = "Create a service-scoped log bucket + Logs Router sink + log view for least-privilege client access."
  default     = true
}

variable "enable_slo" {
  type        = bool
  description = "Create a Service Monitoring Service + Availability SLO + burn-rate alert policy."
  default     = true
}


# --- Optional: production-safe scheduled jobs (Cloud Scheduler -> Cloud Run Jobs) ---

variable "enable_scheduled_jobs" {
  type        = bool
  description = "If true, create a Cloud Run Job + Cloud Scheduler trigger for offline checks."
  default     = true
}

variable "enable_migration_job" {
  type        = bool
  description = "If true, create a Cloud Run Job to run DB migrations on demand."
  default     = true
}

variable "offline_job_schedule" {
  type        = string
  description = "Cron schedule for the offline check Cloud Scheduler job."
  # Default to every 5 minutes to minimize background compute cost.
  # If you need faster detection, set to "*/1 * * * *".
  default = "*/5 * * * *"
}

variable "scheduler_time_zone" {
  type        = string
  description = "Time zone for Cloud Scheduler."
  default     = "Etc/UTC"
}


# --- Optional: retention / compaction job (recommended) ---

variable "enable_retention_job" {
  type        = bool
  description = "If true, provision a Cloud Run Job + Cloud Scheduler trigger to prune old telemetry (reduces Cloud SQL storage growth)."
  default     = true
}

variable "retention_job_schedule" {
  type        = string
  description = "Cron schedule for the retention job."
  default     = "15 3 * * *"
}

variable "telemetry_retention_days" {
  type        = number
  description = "Delete telemetry_points older than N days."
  default     = 30
}

variable "quarantine_retention_days" {
  type        = number
  description = "Delete quarantined_telemetry older than N days."
  default     = 30
}

variable "retention_batch_size" {
  type        = number
  description = "Rows deleted per batch (Postgres uses a CTE + LIMIT)."
  default     = 5000
}

variable "retention_max_batches" {
  type        = number
  description = "Maximum batches per run (guardrail to avoid runaway deletions)."
  default     = 50
}

# --- Optional: partition manager job (Postgres scale path) ---

variable "enable_partition_manager_job" {
  type        = bool
  description = "If true, provision a Cloud Run Job + Cloud Scheduler trigger to pre-create telemetry partitions and refresh hourly rollups."
  default     = true
}

variable "partition_manager_job_schedule" {
  type        = string
  description = "Cron schedule for the partition manager job."
  default     = "0 */6 * * *"
}

variable "telemetry_partition_lookback_months" {
  type        = number
  description = "How many months back the partition manager should ensure exist for late-arriving telemetry."
  default     = 1
}

variable "telemetry_partition_prewarm_months" {
  type        = number
  description = "How many months ahead the partition manager should pre-create telemetry partitions."
  default     = 2
}

variable "telemetry_rollups_enabled" {
  type        = bool
  description = "If true, the partition manager computes hourly telemetry rollups for long-range charts."
  default     = true
}

variable "telemetry_rollup_backfill_hours" {
  type        = number
  description = "How many recent hours the partition manager recomputes when refreshing hourly rollups."
  default     = 168
}


# --- Optional: synthetic telemetry generator (dev/stage only) ---

variable "enable_simulation" {
  type        = bool
  description = "If true, provision a Cloud Run Job + Cloud Scheduler trigger that generates synthetic telemetry for the demo fleet. Intended for dev/stage only."
  default     = false

  validation {
    condition     = var.env != "prod" || var.enable_simulation == false
    error_message = "enable_simulation must be false when env=prod (synthetic telemetry is for dev/stage only)."
  }
}

variable "simulation_schedule" {
  type        = string
  description = "Cron schedule for the simulation Cloud Scheduler job."
  # Default to every minute so dashboards feel "live".
  default = "*/1 * * * *"
}

variable "simulation_points_per_device" {
  type        = number
  description = "How many telemetry points to generate per device per simulation job run."
  default     = 1
}

# --- Optional: event-driven ingest (Pub/Sub) ---

variable "enable_pubsub_ingest" {
  type        = bool
  description = "If true, create Pub/Sub resources and set INGEST_PIPELINE_MODE=pubsub."
  default     = false
}

variable "pubsub_topic_name" {
  type        = string
  description = "Pub/Sub topic name for raw telemetry batches."
  default     = "edgewatch-telemetry-raw"
}

variable "pubsub_push_subscription_name" {
  type        = string
  description = "Push subscription name for telemetry worker delivery."
  default     = "edgewatch-telemetry-worker"
}

# --- Optional: analytics export lane (GCS + BigQuery + Cloud Run Job) ---

variable "enable_analytics_export" {
  type        = bool
  description = "If true, provision analytics export resources and scheduler."
  default     = false
}

variable "analytics_export_schedule" {
  type        = string
  description = "Cron schedule for analytics export Cloud Scheduler job."
  default     = "0 * * * *"
}

variable "analytics_export_bucket_name" {
  type        = string
  description = "Optional bucket name override for analytics staging files."
  default     = null
}

variable "analytics_export_bucket_lifecycle_days" {
  type        = number
  description = "Delete staged export objects after N days."
  default     = 14
}

variable "analytics_export_dataset" {
  type        = string
  description = "BigQuery dataset for telemetry exports."
  default     = "edgewatch_analytics"
}

variable "analytics_export_table" {
  type        = string
  description = "BigQuery table for telemetry exports."
  default     = "telemetry_points"
}

variable "analytics_export_gcs_prefix" {
  type        = string
  description = "GCS object prefix for staged export files."
  default     = "telemetry"
}

# --- Demo bootstrap controls ---

variable "bootstrap_demo_device" {
  type        = bool
  description = "If true, the service bootstraps a demo device (or fleet) on startup."
  default     = true

  # Guardrail: demo bootstrap is great for `env=dev`, but it's a footgun for stage/prod.
  # Force an explicit opt-in when switching environments.
  validation {
    condition     = var.env == "dev" || var.bootstrap_demo_device == false || var.allow_demo_in_non_dev
    error_message = "bootstrap_demo_device must be false when env is stage/prod unless allow_demo_in_non_dev=true (avoid shipping demo credentials by accident)."
  }
}

variable "allow_demo_in_non_dev" {
  type        = bool
  description = "Guardrail override: allow demo fleet bootstrap in stage/prod. Only set this to true for non-production staging environments."
  default     = false
}

variable "demo_fleet_size" {
  type        = number
  description = "Number of demo devices to bootstrap when bootstrap_demo_device is true."
  default     = 3
}

variable "demo_device_id" {
  type        = string
  description = "Base demo device id (supports 3-digit suffix derivation)."
  default     = "demo-well-001"
}

variable "demo_device_name" {
  type        = string
  description = "Base demo device display name (supports 3-digit suffix derivation)."
  default     = "Demo Well 001"
}

variable "demo_device_token" {
  type        = string
  description = "Base demo device token (supports 3-digit suffix derivation)."
  default     = "dev-device-token-001"
}
