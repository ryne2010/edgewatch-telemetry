# Edge Protection Runbook (Task 20)

This runbook covers Cloud Armor edge protection for a public ingest service.

## What is enabled

When `enable_ingest_edge_protection=true`, Terraform provisions:

- External HTTPS Load Balancer for primary ingest service
- Cloud Armor policy attached to the ingest backend
- Edge throttle rule (independent of app-level rate limiting)
- Optional trusted CIDR allowlist bypass

Key Terraform vars:

- `enable_ingest_edge_protection`
- `ingest_edge_domain`
- `ingest_edge_rate_limit_count`
- `ingest_edge_rate_limit_interval_sec`
- `ingest_edge_rate_limit_enforce_on_key`
- `ingest_edge_allowlist_cidrs`
- `ingest_edge_rate_limit_preview`

Useful outputs:

- `ingest_edge_url`
- `ingest_edge_security_policy_name`

## Deployment notes

1. Set `ingest_edge_domain` and create DNS A record to the provisioned HTTPS LB IP.
2. Keep app-level controls enabled (`MAX_REQUEST_BODY_BYTES`, `MAX_POINTS_PER_REQUEST`, in-app device limiter).
3. For staged rollout, start with `ingest_edge_rate_limit_preview=true` and tune from logs before enforcing.

## Tuning guidance

- Start conservative:
  - `ingest_edge_rate_limit_count=1200`
  - `ingest_edge_rate_limit_interval_sec=60`
  - `ingest_edge_rate_limit_enforce_on_key="IP"`
- If many devices sit behind one NAT and get throttled, increase threshold or switch to `XFF_IP` when your edge path preserves client IPs.
- Use `ingest_edge_allowlist_cidrs` only for trusted fixed egress ranges (for example, office diagnostics networks).

## Observability

Monitor:

- Cloud Armor request logs (match, action, preview/enforced)
- HTTP 429 rates at edge and app
- ingest success/duplicate/quarantine rates in app telemetry

Example log filters (Cloud Logging):

```text
resource.type="http_load_balancer"
jsonPayload.enforcedSecurityPolicy.name:"edge-armor"
```

```text
resource.type="http_load_balancer"
jsonPayload.statusDetails="denied_by_security_policy"
```

## Manual smoke test

Run a burst against `ingest_edge_url` (non-production token/device) and verify:

1. Edge 429 responses appear before app-level limits.
2. Cloud Armor logs show throttle actions.
3. App remains healthy (`/health`, `/readyz`), and no secret leakage in logs.

## Rollback

- Immediate soft rollback: set `ingest_edge_rate_limit_preview=true`.
- Full rollback: set `enable_ingest_edge_protection=false`, apply Terraform, and continue ingest via `service_url`.
