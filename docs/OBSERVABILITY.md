# Observability (Logging + Monitoring + SLOs)

This repo treats observability as **code**: dashboards, alerts, log routing, and SLOs are provisioned via Terraform.

Files to review:
- `infra/gcp/cloud_run_demo/observability.tf` — dashboards + basic alerts
- `infra/gcp/cloud_run_demo/log_views.tf` — service-scoped log bucket + sink + log view
- `infra/gcp/cloud_run_demo/slo.tf` — Service Monitoring + Availability SLO + burn-rate alerts

---

## Logging: service-scoped logs (client-safe pattern)

Instead of giving stakeholders broad `roles/logging.viewer` access on the project, this repo:

1) Routes only this service’s logs into a dedicated log bucket (Logs Router sink).
2) Creates a log view over that bucket.
3) Grants clients `roles/logging.viewAccessor` with an IAM condition pinned to that view.

This is a common pattern for:
- government/regulated work
- consulting engagements with shared observability
- multi-tenant environments

---

## Monitoring dashboards

The default dashboard includes:
- request volume
- error (5xx) rate
- p95-ish latency (via Cloud Run metrics)

Dashboards are safe to share with view-only audiences via `roles/monitoring.viewer`.

---

## SLOs and error budgets (staff-level ops story)

`slo.tf` creates:
- a **Service Monitoring service** for the Cloud Run service
- an **availability SLO** (2xx / total)
- **burn-rate alerts**:
  - fast burn (5m > 14.4x)
  - slow burn (1h > 6x)

Why burn rate alerts?
- They reflect **error budget consumption** instead of static thresholds.
- They are robust across traffic volume changes.

---

## Troubleshooting drills (great interview practice)

Try these controlled failures and document your findings:

1) **IAM failure**  
   Remove Secret Manager access (if used) or remove invoker role (for private services) and watch:
   - Cloud Run revision fails or 401/403 spikes
   - logs show permission errors

2) **Bad deploy**  
   Deploy a container that listens on the wrong port and confirm:
   - revision fails health checks
   - error surfaces in Cloud Run + logs

3) **Performance regression**  
   Add an artificial delay and observe:
   - latency metrics rise
   - alert thresholds trigger
   - SLO burn-rate trends change

Capture your results in `RUNBOOK.md` — that’s interview gold.
