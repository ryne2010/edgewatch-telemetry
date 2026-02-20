# -----------------------------------------------------------------------------
# Optional event-driven ingest lane (Pub/Sub)
# -----------------------------------------------------------------------------

resource "google_pubsub_topic" "telemetry_raw" {
  count = var.enable_pubsub_ingest ? 1 : 0

  project = var.project_id
  name    = var.pubsub_topic_name

  labels = local.labels
}

resource "google_pubsub_topic" "telemetry_raw_dlq" {
  count = var.enable_pubsub_ingest ? 1 : 0

  project = var.project_id
  name    = "${var.pubsub_topic_name}-dlq"

  labels = local.labels
}

resource "google_service_account" "pubsub_push" {
  count = var.enable_pubsub_ingest ? 1 : 0

  project      = var.project_id
  account_id   = "sa-edgewatch-pubsub-push-${var.env}"
  display_name = "EdgeWatch PubSub Push (${var.env})"
}

resource "google_service_account_iam_member" "pubsub_push_token_creator" {
  count = var.enable_pubsub_ingest ? 1 : 0

  service_account_id = google_service_account.pubsub_push[0].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_cloud_run_v2_service_iam_member" "pubsub_push_invoker" {
  count = var.enable_pubsub_ingest ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = module.cloud_run.service_name

  role   = "roles/run.invoker"
  member = "serviceAccount:${google_service_account.pubsub_push[0].email}"
}

resource "google_pubsub_subscription" "telemetry_raw_push" {
  count = var.enable_pubsub_ingest ? 1 : 0

  project = var.project_id
  name    = var.pubsub_push_subscription_name
  topic   = google_pubsub_topic.telemetry_raw[0].id

  ack_deadline_seconds       = 30
  message_retention_duration = "86400s"

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.telemetry_raw_dlq[0].id
    max_delivery_attempts = 5
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  push_config {
    push_endpoint = "${module.cloud_run.service_url}/api/v1/internal/pubsub/push"

    oidc_token {
      service_account_email = google_service_account.pubsub_push[0].email
      audience              = module.cloud_run.service_url
    }
  }

  depends_on = [
    google_cloud_run_v2_service_iam_member.pubsub_push_invoker,
    google_service_account_iam_member.pubsub_push_token_creator,
  ]
}

resource "google_pubsub_subscription" "telemetry_raw_dlq" {
  count = var.enable_pubsub_ingest ? 1 : 0

  project = var.project_id
  name    = "${var.pubsub_push_subscription_name}-dlq"
  topic   = google_pubsub_topic.telemetry_raw_dlq[0].id
}

resource "google_project_iam_member" "runtime_pubsub_publisher" {
  count = var.enable_pubsub_ingest ? 1 : 0

  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${module.service_accounts.runtime_service_account_email}"
}

# -----------------------------------------------------------------------------
# Optional analytics export lane (GCS + BigQuery)
# -----------------------------------------------------------------------------

resource "google_storage_bucket" "analytics_export" {
  count = var.enable_analytics_export ? 1 : 0

  project                     = var.project_id
  name                        = local.analytics_export_bucket
  location                    = "US"
  force_destroy               = false
  uniform_bucket_level_access = true

  lifecycle_rule {
    condition {
      age = var.analytics_export_bucket_lifecycle_days
    }
    action {
      type = "Delete"
    }
  }

  labels = local.labels
}

resource "google_storage_bucket_iam_member" "runtime_analytics_bucket_writer" {
  count = var.enable_analytics_export ? 1 : 0

  bucket = google_storage_bucket.analytics_export[0].name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${module.service_accounts.runtime_service_account_email}"
}

resource "google_bigquery_dataset" "analytics" {
  count = var.enable_analytics_export ? 1 : 0

  project                    = var.project_id
  dataset_id                 = var.analytics_export_dataset
  location                   = "US"
  delete_contents_on_destroy = false

  labels = local.labels
}

resource "google_bigquery_table" "telemetry_export" {
  count = var.enable_analytics_export ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics[0].dataset_id
  table_id   = var.analytics_export_table

  deletion_protection = false

  time_partitioning {
    type  = "DAY"
    field = "ts"
  }

  clustering = ["device_id", "message_id"]

  schema = jsonencode([
    { name = "ts", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "created_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "device_id", type = "STRING", mode = "NULLABLE" },
    { name = "message_id", type = "STRING", mode = "NULLABLE" },
    { name = "batch_id", type = "STRING", mode = "NULLABLE" },
    { name = "ingestion_batch_id", type = "STRING", mode = "NULLABLE" },
    { name = "contract_version", type = "STRING", mode = "NULLABLE" },
    { name = "contract_hash", type = "STRING", mode = "NULLABLE" },
    { name = "metrics", type = "JSON", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_dataset_iam_member" "runtime_analytics_editor" {
  count = var.enable_analytics_export ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics[0].dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${module.service_accounts.runtime_service_account_email}"
}

resource "google_project_iam_member" "runtime_analytics_job_user" {
  count = var.enable_analytics_export ? 1 : 0

  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${module.service_accounts.runtime_service_account_email}"
}
