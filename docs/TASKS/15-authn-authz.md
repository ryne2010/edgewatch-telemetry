# Task 15 — AuthN/AuthZ hardening (RBAC + audit attribution)

🟡 **Status: Planned (identity perimeter is tracked in Task 18)**

## Objective

Move from “shared admin secret in a browser” toward **identity-based access control** and a **principled authorization model**, while keeping local development convenient.

This task focuses on **in-app authorization** once an identity perimeter exists.

> Note: Infrastructure identity (IAP/LB) is tracked separately in `docs/TASKS/18-iap-identity-perimeter.md`.

## What is already implemented

- Route surface toggles:
  - `ENABLE_UI=0|1`
  - `ENABLE_READ_ROUTES=0|1`
  - `ENABLE_INGEST_ROUTES=0|1`
  - `ENABLE_ADMIN_ROUTES=0|1`

- Admin auth mode:
  - `ADMIN_AUTH_MODE=key|none`

- Terraform supports least-privilege multi-service layouts:
  - public ingest + private dashboard + private admin

- UI adapts automatically via `/api/v1/health` feature flags.

## Scope

### In-scope

1) **Role-based authorization (RBAC)**

- Define roles:
  - `viewer` (read-only)
  - `operator` (ack/resolve alerts, view devices)
  - `admin` (device provisioning, policy overrides, destructive actions)

- Enforce route-level ACLs:
  - admin routes require `admin`
  - read routes require at least `viewer`

2) **Audit identity attribution**

- Persist the acting principal on mutations:
  - device provisioning
  - policy changes
  - any destructive actions

- Emit structured audit logs with:
  - `actor_email`
  - `actor_subject` (if available)
  - `request_id`

3) **Local dev convenience**

- Keep `ADMIN_AUTH_MODE=key` as the default dev path.
- Provide a local “dev principal” mode for RBAC testing.

### Out-of-scope

- Full multi-tenant org hierarchy (can be a later task if needed).

## Design notes

- RBAC should be implemented as a single dependency boundary:
  - an `authz` module that routes call

- Identity source should be abstracted:
  - IAP headers / JWT assertions (prod)
  - admin key (dev)

## Acceptance criteria

- Admin actions are blocked without `admin` role.
- Acting principal is persisted and visible in the admin audit UI.
- No secrets are stored in localStorage in production posture.

## Deliverables

- `api/app/auth/` modules for:
  - principal extraction
  - RBAC
  - audit attribution

- DB migration adding `actor_email`/`actor_subject` on relevant audit tables.
- Docs updates:
  - `docs/security.md`
  - `docs/DEPLOY_GCP.md`

## Validation

```bash
make fmt
make lint
make typecheck
make test
```
