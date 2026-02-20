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
- For portfolio/demo apps it's common to run a public Cloud Run service.
- For a production posture, default to private IAM-only invocations.

This flag forces an explicit acknowledgment before making non-dev environments public.
EOT
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
  default     = "*/5 * * * *"
}

variable "scheduler_time_zone" {
  type        = string
  description = "Time zone for Cloud Scheduler."
  default     = "Etc/UTC"
}

# --- Demo bootstrap controls ---

variable "bootstrap_demo_device" {
  type        = bool
  description = "If true, the service bootstraps a demo device (or fleet) on startup."
  default     = true

  # Guardrail: demo bootstrap is great for `env=dev`, but it's a footgun for stage/prod.
  # Force an explicit opt-out when switching environments.
  validation {
    condition     = var.env == "dev" || var.bootstrap_demo_device == false
    error_message = "bootstrap_demo_device must be false when env is stage/prod (avoid shipping demo credentials)."
  }
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
