variable "project_id" {
  type        = string
  description = "GCP project ID."
}

variable "runtime_account_id" {
  type        = string
  description = "Service account ID for runtime workloads (Cloud Run)."
  default     = "sa-runtime"
}

variable "runtime_display_name" {
  type        = string
  description = "Runtime service account display name."
  default     = "Runtime Service Account"
}

variable "runtime_roles" {
  type        = list(string)
  description = "Project-level roles to grant the runtime service account."
  default = [
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter"
  ]
}

variable "create_ci_account" {
  type        = bool
  description = "Whether to create a CI service account (for Terraform/CI pipelines)."
  default     = false
}

variable "ci_account_id" {
  type        = string
  description = "CI service account ID."
  default     = "sa-ci"
}

variable "ci_display_name" {
  type        = string
  description = "CI service account display name."
  default     = "CI Service Account"
}

variable "ci_roles" {
  type        = list(string)
  description = "Project-level roles to grant the CI service account (least privilege for Terraform apply)."
  default = [
    "roles/run.admin",
    "roles/iam.serviceAccountUser",
    "roles/artifactregistry.admin",
    "roles/compute.networkAdmin",
    "roles/secretmanager.admin",
    "roles/serviceusage.serviceUsageAdmin"
  ]
}
