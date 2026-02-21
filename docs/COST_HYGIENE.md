# Cost hygiene

This repo is designed to be **safe to keep running** as a long-lived demo.

If your goal is to keep the monthly bill near-zero for a small demo/staging deployment:

1. **Scale the app tier to zero** (Cloud Run) and cap instance count.
2. **Treat the database as the primary cost driver** (Cloud SQL is rarely “free”).
3. Keep background scheduling low-frequency (or disable it if you can tolerate delayed/offline-only status).

## Built-in safeguards

### Cloud Run guardrails
- min/max instances are configurable (`min_instances`, `max_instances`)
- serverless = no always-on VM cost for the app tier

Recommended low-cost defaults (Terraform `infra/gcp/cloud_run_demo`):

- `min_instances = 0` (scale to zero)
- `max_instances = 1` (hard cap)
- consider reducing `service_memory` (and `job_memory`) once you’ve validated headroom
- `allow_unauthenticated = false` for internal deployments (reduces exposure to random internet traffic)

If you can use IAM auth (`allow_unauthenticated=false`), Cloud Run will reject unauthorized requests **before** they hit your container.
That both improves security and reduces your risk of being billed for random traffic.

> If you *want* a public demo UI, keep `allow_unauthenticated=true`, but understand that any request that reaches your container can incur cost.

### Artifact Registry cleanup policies (dry-run by default)
In `infra/gcp/cloud_run_demo/main.tf` we configure cleanup policies with:

- `cleanup_policy_dry_run = true`

This shows the pattern without deleting anything unexpectedly.

Once you're confident, set it to `false` to enable actual cleanup.

### Log retention
`infra/gcp/cloud_run_demo/log_views.tf` creates a service-scoped log bucket with:

- `log_retention_days` (default: 30)

Tip: log retention mostly affects **storage** cost; the bigger lever is **log volume**.
Avoid logging raw telemetry payloads.

### Scheduled jobs
Offline checks run as:

- Cloud Scheduler (cron)
- Cloud Run Job (`edgewatch-offline-check-<env>`)

To minimize background compute:

- Increase the cron interval (default is every 5 minutes)
- Or set `enable_scheduled_jobs=false` (status still computes from `last_seen_at`, but offline alerts won’t be generated automatically)

Cloud Scheduler itself is typically low-cost; the main variable cost is the **Cloud Run Job runtime** and the database work it triggers.

### Database cost notes
This repo intentionally does **not** provision a database.

In GCP, Cloud SQL is often the dominant cost for low-traffic apps.

Options:

- Use the smallest shared-core Cloud SQL instance that meets your needs.
- Stop the Cloud SQL instance when you are not demoing (you still pay for storage/IP).
- For ultra-low-cost demos, point `DATABASE_URL` to a hosted Postgres outside GCP.

## Recommended project-level controls (platform repo)

In a real environment, enforce these centrally (Repo 3):
- Billing budgets + alerting
- Org Policies / constraints
- Standard log exclusion rules (avoid runaway telemetry costs)
- Artifact Registry retention baselines
