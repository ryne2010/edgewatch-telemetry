variable "project_id" {
  type        = string
  description = "GCP project ID."
}

variable "secrets" {
  description = "Map of secret_id -> config. This module creates secret containers only (no secret versions)."
  type = map(object({
    labels = optional(map(string), {})
  }))
  default = {}
}
