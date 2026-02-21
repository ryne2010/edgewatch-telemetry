/*
  Service Monitoring: Availability SLO + burn-rate alerts.

  Why include this in this repo?
  - It demonstrates "staff-level ops maturity": you don't just deploy; you define SLIs/SLOs,
    track error budgets, and alert on burn rate (fast + slow) instead of static thresholds.

  Notes:
  - Cloud Run metrics come from Cloud Monitoring (run.googleapis.com/*).
  - This example uses request_count with response_code_class to model availability.
*/

locals {
  monitoring_service_id = var.service_name

  # Cloud Monitoring filter syntax (NOT the same as Cloud Logging filters).
  # We scope to this Cloud Run service + region.
  base_request_count_filter = join(" AND ", [
    "metric.type=\"run.googleapis.com/request_count\"",
    "resource.type=\"cloud_run_revision\"",
    "resource.label.\"service_name\"=\"${var.service_name}\"",
    "resource.label.\"location\"=\"${var.region}\"",
  ])

  good_2xx_filter = join(" AND ", [
    local.base_request_count_filter,
    "metric.label.\"response_code_class\"=\"2xx\"",
  ])

  slo_full_name = "projects/${var.project_id}/services/${local.monitoring_service_id}/serviceLevelObjectives/availability"
}

resource "google_monitoring_service" "cloud_run_service" {
  count = (var.enable_observability && var.enable_slo) ? 1 : 0

  project      = var.project_id
  service_id   = local.monitoring_service_id
  display_name = "Cloud Run: ${var.service_name}"

  basic_service {
    service_type = "CLOUD_RUN"
    service_labels = {
      location     = var.region
      service_name = var.service_name
    }
  }

  user_labels = {
    env     = var.env
    service = var.service_name
    repo    = "edgewatch-telemetry"
  }
}

resource "google_monitoring_slo" "availability" {
  count = (var.enable_observability && var.enable_slo) ? 1 : 0

  project      = var.project_id
  service      = google_monitoring_service.cloud_run_service[0].service_id
  slo_id       = "availability"
  display_name = "Availability (2xx ratio) — ${var.service_name}"

  # Interview-ready default: 99.5% over a 28-day rolling window
  goal                = 0.995
  rolling_period_days = 28

  request_based_sli {
    good_total_ratio {
      good_service_filter  = local.good_2xx_filter
      total_service_filter = local.base_request_count_filter
    }
  }
}

resource "google_monitoring_alert_policy" "slo_burn_rate" {
  count = (var.enable_observability && var.enable_slo) ? 1 : 0

  project      = var.project_id
  display_name = "${var.service_name} — SLO burn rate (Availability)"
  combiner     = "OR"

  documentation {
    mime_type = "text/markdown"
    content   = <<EOT
This alert fires when ${var.service_name} is burning through its **availability** error budget too quickly.

**What to check**
1. Cloud Run logs (service-scoped log view)
2. Recent deploy / config changes
3. Upstream dependencies + latency
4. IAM/auth issues (401/403 spikes)

**Runbook**
See RUNBOOK.md and docs/OBSERVABILITY.md in this repo.
EOT
  }

  # Fast burn: would exhaust error budget in ~2 days (28 / 14.4 ≈ 1.9)
  conditions {
    display_name = "Fast burn (5m)"
    condition_threshold {
      filter          = "select_slo_burn_rate(\"${local.slo_full_name}\", \"5m\")"
      comparison      = "COMPARISON_GT"
      threshold_value = 14.4
      duration        = "0s"

      trigger {
        count = 1
      }
    }
  }

  # Slow burn: catches sustained degradation
  conditions {
    display_name = "Slow burn (1h)"
    condition_threshold {
      filter          = "select_slo_burn_rate(\"${local.slo_full_name}\", \"1h\")"
      comparison      = "COMPARISON_GT"
      threshold_value = 6
      duration        = "0s"

      trigger {
        count = 1
      }
    }
  }

  notification_channels = var.notification_channels
  enabled               = true

  user_labels = {
    env     = var.env
    service = var.service_name
    type    = "slo-burn-rate"
  }
}

output "slo_full_name" {
  description = "Full SLO resource name used by burn-rate alerts (select_slo_burn_rate)."
  value       = (var.enable_observability && var.enable_slo) ? local.slo_full_name : null
}
