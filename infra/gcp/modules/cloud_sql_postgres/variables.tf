variable "project_id" {
  type        = string
  description = "GCP project ID."
}

variable "region" {
  type        = string
  description = "Cloud SQL region."
}

variable "instance_name" {
  type        = string
  description = "Cloud SQL instance name."
}

variable "database_version" {
  type        = string
  description = "Cloud SQL Postgres version (for example POSTGRES_15)."
  default     = "POSTGRES_15"
}

variable "database_name" {
  type        = string
  description = "Application database name."
  default     = "edgewatch"
}

variable "user_name" {
  type        = string
  description = "Application database user name."
  default     = "edgewatch"
}

variable "user_password" {
  type        = string
  description = "Application database user password."
  sensitive   = true
}

variable "tier" {
  type        = string
  description = "Machine tier (cost driver)."
  default     = "db-f1-micro"
}

variable "availability_type" {
  type        = string
  description = "ZONAL (cost-min) or REGIONAL (HA)."
  default     = "ZONAL"
}

variable "disk_type" {
  type        = string
  description = "Disk type for Cloud SQL storage."
  default     = "PD_HDD"
}

variable "disk_size_gb" {
  type        = number
  description = "Initial disk size in GB."
  default     = 10
}

variable "backup_enabled" {
  type        = bool
  description = "Enable automated backups."
  default     = true
}

variable "backup_start_time" {
  type        = string
  description = "Backup start time in UTC (HH:MM)."
  default     = "03:00"
}

variable "enable_public_ip" {
  type        = bool
  description = "Enable public IP. Keep true for Cloud Run connector without VPC connector."
  default     = true
}

variable "require_ssl" {
  type        = bool
  description = "Require SSL for direct IP connections."
  default     = true
}

variable "deletion_protection" {
  type        = bool
  description = "Protect instance from accidental destroy."
  default     = false
}

variable "labels" {
  type        = map(string)
  description = "Resource labels."
  default     = {}
}
