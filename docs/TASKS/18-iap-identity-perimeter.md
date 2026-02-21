# Task 18 — IAP identity perimeter for dashboard/admin (Terraform + app verification)

✅ **Status: Implemented**

## Objective

Make the operator UI truly production-grade by putting the **dashboard** and/or **admin** services behind:

- Google identity login
- group/user allowlists

using **Identity-Aware Proxy (IAP)**.

This is the recommended “professional” posture for:

- a public ingest service (no UI)
- private operator dashboard UI
- private admin UI

## Scope

### In-scope

- Terraform adds an HTTPS Load Balancer + IAP configuration for:
  - dashboard service
  - admin service

- Terraform should support:
  - enabling/disabling IAP per service
  - allowlists by principal (email) or group
  - clean outputs: `dashboard_iap_url`, `admin_iap_url`

- App defense-in-depth (optional but recommended):
  - verify IAP identity headers when enabled
  - attach acting principal (email) to admin mutations
  - emit structured audit logs

### Out-of-scope

- Multi-tenant RBAC inside the app (separate follow-up; can live in Task 15).

## Design notes

### Infrastructure

- Use a serverless NEG pointing to Cloud Run.
- Use IAP on the backend service.
- Ensure TLS is managed (Google-managed cert is fine).

### App-level verification

- When `IAP_AUTH_ENABLED=true`:
  - require `X-Goog-Authenticated-User-Email`
  - optionally validate the IAP JWT assertion

Store `actor_email` on admin events in DB and include in logs.

## Acceptance criteria

- A user must authenticate via Google login to access dashboard/admin.
- Access can be restricted to an allowlist.
- Admin actions record the acting principal.

## Deliverables

- Terraform additions under `infra/gcp/cloud_run_demo/`:
  - LB resources
  - IAP bindings
  - profile examples
- API:
  - optional IAP verification middleware
  - admin mutation audit attribution
- Docs:
  - `docs/DEPLOY_GCP.md`
  - `docs/security.md`
  - `docs/PRODUCTION_POSTURE.md`

## Validation

```bash
make lint
make typecheck
make test

# Terraform validation
make tf-fmt
make tf-validate
```
