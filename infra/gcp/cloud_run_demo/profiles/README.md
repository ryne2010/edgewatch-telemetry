# Terraform profiles

These `*.tfvars` files provide **opinionated presets** for common deployment postures.

Use them with the Makefile via `TFVARS=...`:

```bash
make plan-gcp  PROJECT_ID=... REGION=us-central1 TFVARS=infra/gcp/cloud_run_demo/profiles/dev_public_demo.tfvars
make apply-gcp PROJECT_ID=... REGION=us-central1 TFVARS=infra/gcp/cloud_run_demo/profiles/dev_public_demo.tfvars
```

Or use the shortcuts:

```bash
make deploy-gcp-demo  PROJECT_ID=... REGION=us-central1
make deploy-gcp-stage PROJECT_ID=... REGION=us-central1
make deploy-gcp-prod  PROJECT_ID=... REGION=us-central1
```

## Profiles

- `dev_public_demo.tfvars`
  - Public Cloud Run service for a lightweight demo environment.
  - Guardrails: `max_instances=1` and scale-to-zero.
  - Includes a minimal-cost managed Cloud SQL Postgres instance.
  - Admin routes are enabled and protected by an admin key (convenient for demos).

- `stage_private_iam.tfvars`
  - Private IAM-only Cloud Run service for staging.
  - Enables the synthetic telemetry generator job so the UI has live data without physical hardware.
  - Uses `admin_auth_mode=none` (no browser-held admin key) because the service is private.

- `prod_private_iam.tfvars`
  - Private IAM-only Cloud Run service.
  - Includes managed Cloud SQL Postgres with deletion protection.
  - Uses `admin_auth_mode=none` (no browser-held admin key) because the service is private.

- `stage_public_ingest_private_admin.tfvars`
  - **IoT posture**: public ingest service + no admin routes on the public surface.
  - Deploys a second, private **admin** Cloud Run service for operators.

- `prod_public_ingest_private_admin.tfvars`
  - Same as the staging IoT posture, but for production.

- `stage_public_ingest_private_dashboard_private_admin.tfvars`
  - **Recommended IoT posture**: public ingest service + private dashboard service + private admin service.
  - Least privilege: many users can access the dashboard without receiving admin endpoints.

- `prod_public_ingest_private_dashboard_private_admin.tfvars`
  - Same as the staging least-privilege IoT posture, but for production.

## Notes

- `DATABASE_URL` is managed by Terraform when `enable_cloud_sql=true`.
- `ADMIN_API_KEY` is only required by the app when `ADMIN_AUTH_MODE=key`. Terraform still creates and passes the secret by default, which is fine.
- If you use `enable_admin_service=true`, the module outputs `admin_service_url` in addition to `service_url`.
- If you use `enable_dashboard_service=true`, the module outputs `dashboard_service_url`.
