#tfsec:ignore:google-sql-no-public-access: Cost-min default uses Cloud SQL connector from Cloud Run without VPC connector.
resource "google_sql_database_instance" "postgres" {
  name                = var.instance_name
  project             = var.project_id
  region              = var.region
  database_version    = var.database_version
  deletion_protection = var.deletion_protection

  settings {
    tier              = var.tier
    availability_type = var.availability_type
    disk_type         = var.disk_type
    disk_size         = var.disk_size_gb
    disk_autoresize   = true
    user_labels       = var.labels

    backup_configuration {
      enabled    = var.backup_enabled
      start_time = var.backup_start_time
    }

    database_flags {
      name  = "log_temp_files"
      value = "0"
    }

    database_flags {
      name  = "log_connections"
      value = "on"
    }

    database_flags {
      name  = "log_disconnections"
      value = "on"
    }

    database_flags {
      name  = "log_lock_waits"
      value = "on"
    }

    database_flags {
      name  = "log_checkpoints"
      value = "on"
    }

    ip_configuration {
      ipv4_enabled = var.enable_public_ip
      require_ssl  = var.require_ssl
    }

    maintenance_window {
      day          = 7
      hour         = 4
      update_track = "stable"
    }
  }
}

resource "google_sql_database" "app" {
  name     = var.database_name
  project  = var.project_id
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "app" {
  name     = var.user_name
  project  = var.project_id
  instance = google_sql_database_instance.postgres.name
  password = var.user_password
}
