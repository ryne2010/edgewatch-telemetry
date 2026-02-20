variable "project_id" {
  type        = string
  description = "GCP project ID."
}

variable "service_account_email" {
  type        = string
  description = "Service account email to impersonate from GitHub Actions."
}

variable "github_repository" {
  type        = string
  description = "GitHub repository in OWNER/REPO format."
}

variable "allowed_branches" {
  type        = list(string)
  description = "Allowed GitHub branches for OIDC auth (e.g., ['main']). Empty list means any branch."
  default     = ["main"]
}

variable "pool_id" {
  type        = string
  description = "Workload Identity Pool ID."
  default     = "github-pool"
}

variable "provider_id" {
  type        = string
  description = "Workload Identity Provider ID."
  default     = "github-provider"
}

variable "pool_display_name" {
  type    = string
  default = "GitHub Actions Pool"
}

variable "pool_description" {
  type    = string
  default = "Workload Identity Pool for GitHub Actions OIDC."
}

variable "provider_display_name" {
  type    = string
  default = "GitHub OIDC Provider"
}

variable "provider_description" {
  type    = string
  default = "OIDC provider for token.actions.githubusercontent.com"
}

variable "grant_token_creator" {
  type        = bool
  description = "Whether to also grant roles/iam.serviceAccountTokenCreator to the GitHub principal set."
  default     = true
}
