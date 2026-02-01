variable "project_id" {
  type        = string
  description = "GCP project ID."
}

variable "location" {
  type        = string
  description = "Region for Artifact Registry (e.g., us-central1)."
  default     = "us-central1"
}

variable "repository_id" {
  type        = string
  description = "Repository ID."
  default     = "platform-images"
}

variable "format" {
  type        = string
  description = "Repository format."
  default     = "DOCKER"
}

variable "description" {
  type        = string
  description = "Repository description."
  default     = "Docker images for platform services."
}

variable "labels" {
  type        = map(string)
  description = "Labels to apply."
  default     = {}
}


variable "cleanup_policy_dry_run" {
  type        = bool
  description = "If true, cleanup policies run in dry-run mode (no deletions)."
  default     = true
}

variable "cleanup_policies" {
  description = <<EOT
Artifact Registry cleanup policies.

This is an advanced hygiene feature: it helps keep long-lived demo repos cost-contained.

Schema matches google_artifact_registry_repository.cleanup_policies blocks. Example:
[
  {
    id     = "delete-untagged-old"
    action = "DELETE"
    condition = {
      tag_state  = "UNTAGGED"
      older_than = "1209600s" # 14d
    }
  }
]
EOT

  type = list(object({
    id     = string
    action = string
    condition = optional(object({
      tag_state             = optional(string)
      tag_prefixes          = optional(list(string))
      package_name_prefixes = optional(list(string))
      version_name_prefixes = optional(list(string))
      older_than            = optional(string)
      newer_than            = optional(string)
    }))
    most_recent_versions = optional(object({
      package_name_prefixes = optional(list(string))
      keep_count            = number
    }))
  }))

  default = []
}
