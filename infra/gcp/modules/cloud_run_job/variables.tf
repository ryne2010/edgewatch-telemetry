variable "project_id" {
  type        = string
  description = "GCP project ID."
}

variable "region" {
  type        = string
  description = "GCP region."
}

variable "job_name" {
  type        = string
  description = "Cloud Run Job name."
}

variable "image" {
  type        = string
  description = "Container image URI."
}

variable "service_account_email" {
  type        = string
  description = "Service account email used by the job runtime."
}

variable "command" {
  type        = list(string)
  description = "Optional container command override."
  default     = []
}

variable "args" {
  type        = list(string)
  description = "Optional container args."
  default     = []
}

variable "env_vars" {
  type        = map(string)
  description = "Plaintext environment variables."
  default     = {}
}

variable "secret_env" {
  type        = map(string)
  description = "Map of ENV_VAR_NAME => Secret Manager secret resource name."
  default     = {}
}

variable "labels" {
  type        = map(string)
  description = "Labels applied to the job."
  default     = {}
}

variable "cpu" {
  type        = string
  description = "CPU limit (e.g., '1')."
  default     = "1"
}

variable "memory" {
  type        = string
  description = "Memory limit (e.g., '512Mi')."
  default     = "512Mi"
}

variable "vpc_connector_id" {
  type        = string
  description = "Optional Serverless VPC Access connector ID."
  default     = null
}

variable "vpc_egress" {
  type        = string
  description = "VPC egress setting when a connector is attached."
  default     = "PRIVATE_RANGES_ONLY"
}
