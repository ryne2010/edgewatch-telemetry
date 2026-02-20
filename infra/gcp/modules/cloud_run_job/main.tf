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

        dynamic "volume_mounts" {
          for_each = length(var.cloud_sql_instances) == 0 ? [] : [1]
          content {
            name       = "cloudsql"
            mount_path = "/cloudsql"
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

      dynamic "volumes" {
        for_each = length(var.cloud_sql_instances) == 0 ? [] : [1]
        content {
          name = "cloudsql"
          cloud_sql_instance {
            instances = var.cloud_sql_instances
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
