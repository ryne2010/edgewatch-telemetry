variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "network_name" {
  description = "Name of the VPC network."
  type        = string
  default     = "platform-vpc"
}

variable "routing_mode" {
  description = "Routing mode for the VPC. REGIONAL or GLOBAL."
  type        = string
  default     = "REGIONAL"
}

variable "subnets" {
  description = "Map of subnet name -> { region, cidr, private_ip_google_access }"
  type = map(object({
    region                   = string
    cidr                     = string
    private_ip_google_access = optional(bool, true)
    purpose                  = optional(string)
    role                     = optional(string)
  }))
  default = {
    "platform-subnet-us-central1" = {
      region = "us-central1"
      cidr   = "10.10.0.0/24"
    }
  }
}

variable "create_serverless_connector" {
  description = "Whether to create a Serverless VPC Access connector (for Cloud Run -> VPC)."
  type        = bool
  default     = false
}

variable "serverless_connector_name" {
  description = "Name for the Serverless VPC Access connector."
  type        = string
  default     = "serverless-connector"
}

variable "serverless_connector_region" {
  description = "Region for the Serverless VPC Access connector."
  type        = string
  default     = "us-central1"
}

variable "serverless_connector_cidr" {
  description = "CIDR range for the Serverless VPC Access connector (must not overlap subnets)."
  type        = string
  default     = "10.8.0.0/28"
}

variable "serverless_connector_min_throughput" {
  description = "Min throughput for the connector (Mbps)."
  type        = number
  default     = 200
}

variable "serverless_connector_max_throughput" {
  description = "Max throughput for the connector (Mbps)."
  type        = number
  default     = 300
}
