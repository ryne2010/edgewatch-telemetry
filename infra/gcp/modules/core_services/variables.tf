variable "project_id" {
  description = "GCP project ID to enable APIs in."
  type        = string
}

variable "services" {
  description = "List of service APIs to enable."
  type        = list(string)
  default = [
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "compute.googleapis.com",
    "vpcaccess.googleapis.com",
    "pubsub.googleapis.com",
    "cloudscheduler.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "secretmanager.googleapis.com"
  ]
}

variable "disable_on_destroy" {
  description = "Whether to disable services on destroy."
  type        = bool
  default     = false
}

variable "disable_dependent_services" {
  description = "Whether to disable dependent services when disabling a service."
  type        = bool
  default     = false
}
