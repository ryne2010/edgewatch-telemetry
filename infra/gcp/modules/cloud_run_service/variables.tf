variable "project_id" {
  type        = string
  description = "GCP project ID."
}

variable "region" {
  type        = string
  description = "Cloud Run region."
  default     = "us-central1"
}

variable "service_name" {
  type        = string
  description = "Cloud Run service name."
}

variable "image" {
  type        = string
  description = "Container image URI (e.g., us-central1-docker.pkg.dev/PROJECT/REPO/IMAGE:TAG)."
}

variable "service_account_email" {
  type        = string
  description = "Service account email used by the Cloud Run service."
}

variable "container_port" {
  type        = number
  description = "Container port."
  default     = 8080
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

variable "min_instances" {
  type        = number
  description = "Minimum instances (0 for scale-to-zero)."
  default     = 0
}

variable "max_instances" {
  type        = number
  description = "Maximum instances."
  default     = 2
}

variable "ingress" {
  type        = string
  description = "Ingress setting (e.g., INGRESS_TRAFFIC_ALL, INGRESS_TRAFFIC_INTERNAL_ONLY)."
  default     = "INGRESS_TRAFFIC_ALL"
}

variable "allow_unauthenticated" {
  type        = bool
  description = "Whether to allow unauthenticated invocations (public service)."
  default     = false
}

variable "env_vars" {
  type        = map(string)
  description = "Plaintext environment variables."
  default     = {}
}

variable "secret_env" {
  type        = map(string)
  description = "Map of ENV_NAME -> Secret Manager secret_id. Uses latest version."
  default     = {}
}

variable "vpc_connector_id" {
  type        = string
  description = "Serverless VPC Access connector ID (optional)."
  default     = null
}

variable "vpc_egress" {
  type        = string
  description = "VPC egress setting (ALL_TRAFFIC or PRIVATE_RANGES_ONLY)."
  default     = "PRIVATE_RANGES_ONLY"
}

variable "labels" {
  type        = map(string)
  description = "Labels for the service."
  default     = {}
}
