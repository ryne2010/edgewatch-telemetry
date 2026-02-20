resource "google_cloud_run_v2_job" "job" {
  name     = var.job_name
  project  = var.project_id
  location = var.region

  labels = var.labels

  template {
    template {
      service_account = var.service_account_email

      containers {
        image   = var.image
        command = var.command
        args    = var.args

        resources {
          limits = {
            cpu    = var.cpu
            memory = var.memory
          }
        }

        dynamic "env" {
          for_each = var.env_vars
          content {
            name  = env.key
            value = env.value
          }
        }

        dynamic "env" {
          for_each = var.secret_env
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = env.value
                version = "latest"
              }
            }
          }
        }
      }

      dynamic "vpc_access" {
        for_each = var.vpc_connector_id == null ? [] : [1]
        content {
          connector = var.vpc_connector_id
          egress    = var.vpc_egress
        }
      }
    }
  }
}
