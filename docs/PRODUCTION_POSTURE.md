# Intended production posture

This repo is designed to be **cost-aware**, **secure-by-default**, and **operator-friendly**.

Because EdgeWatch is an IoT-style system (RPi over cellular + bearer tokens), there isn’t a single “best” posture.
Instead, you pick a posture based on whether you’re optimizing for:

- **Shareable demo links**
- **Internal/operator-only staging**
- **Real IoT ingestion over the public internet**

---

## Posture A: Public demo

Use this when you want to share a live link quickly.

**Characteristics**
- Cloud Run service is **public** (`allow_unauthenticated=true`)
- Hard cost caps (scale-to-zero + `max_instances=1`)
- Demo device bootstrap enabled (dev-only)
- Admin routes are enabled and protected by an admin key (convenient, not ideal for public internet)

**Deploy**

```bash
make deploy-gcp-demo PROJECT_ID=... REGION=us-central1
```

**Notes**
- If the endpoint is public, any request that reaches your container can incur cost.
- Keep `max_instances` low and avoid logging full telemetry payloads.

---

## Posture B: Private IAM staging

Use this for a safer long-lived environment **when all callers can use IAM identity tokens** (humans, CI, other GCP services).

**Characteristics**
- Cloud Run service is **private** (IAM-only invocations)
- Cloud Run still scales to zero (no always-on compute cost)
- Migrations and background checks run as **Cloud Run Jobs**
- No demo credentials shipped
- Admin endpoints can run with `ADMIN_AUTH_MODE=none` (no shared browser-held key) because the service itself is private

**Deploy**

```bash
make deploy-gcp-stage PROJECT_ID=... REGION=us-central1
make deploy-gcp-prod  PROJECT_ID=... REGION=us-central1
```

**Operational notes**
- Your user/service account needs `roles/run.invoker` on the Cloud Run service.
- `make verify-gcp` and `make verify-gcp-ready` automatically try to call the service with `gcloud auth print-identity-token`.

**Important limitation for IoT**
- A Raspberry Pi on a cellular SIM typically **does not** have an easy, safe way to mint Google identity tokens.
  If your edge devices are not using IAM, prefer Posture C.

---

## Posture C: IoT production

Use this for a realistic fleet posture:
- devices ingest over the public internet
- operators/admins have private, authenticated controls

**Characteristics**
- **Public ingest service** (Cloud Run is public, but ingest is protected in-app via device bearer tokens)
  - `ENABLE_INGEST_ROUTES=1`
  - `ENABLE_UI=0` (no browser UI on the public surface)
  - `ENABLE_READ_ROUTES=0` (no dashboard read endpoints exposed publicly)
  - `ENABLE_ADMIN_ROUTES=0` (no `/api/v1/admin/*` surface)
- **Separate private dashboard service** (optional, recommended for least privilege)
  - `ENABLE_UI=1` + `ENABLE_READ_ROUTES=1`
  - `ENABLE_INGEST_ROUTES=0`
  - `ENABLE_ADMIN_ROUTES=0`
- **Separate private admin service** (Cloud Run IAM/IAP)
  - `ENABLE_UI=1` + `ENABLE_READ_ROUTES=1`
  - `ENABLE_INGEST_ROUTES=0`
  - `ENABLE_ADMIN_ROUTES=1`
  - `ADMIN_AUTH_MODE=none` (trust perimeter; no admin key stored in browsers)

**Deploy**

```bash
# Two-service IoT posture (public ingest + private admin)
make deploy-gcp-stage-iot PROJECT_ID=... REGION=us-central1
make deploy-gcp-prod-iot  PROJECT_ID=... REGION=us-central1

# Recommended least-privilege IoT posture (public ingest + private dashboard + private admin)
make deploy-gcp-stage-iot-lp PROJECT_ID=... REGION=us-central1
make deploy-gcp-prod-iot-lp  PROJECT_ID=... REGION=us-central1

# URLs
make url-gcp       PROJECT_ID=... REGION=us-central1 TFVARS=infra/gcp/cloud_run_demo/profiles/prod_public_ingest_private_admin.tfvars
make url-gcp-admin  PROJECT_ID=... REGION=us-central1 TFVARS=infra/gcp/cloud_run_demo/profiles/prod_public_ingest_private_admin.tfvars

# If you enabled the dashboard service (enable_dashboard_service=true):
make url-gcp-dashboard PROJECT_ID=... REGION=us-central1 TFVARS=infra/gcp/cloud_run_demo/profiles/prod_public_ingest_private_dashboard_private_admin.tfvars
```

**Recommended additions (infrastructure perimeter)**
- Cloud Armor / WAF + basic rate limits
- Optional: put the **dashboard/admin UI** behind IAP (Load Balancer + IAP) while keeping ingest public

---

## Database cost reality check

For low-traffic apps, the database is usually the **primary cost driver**.

EdgeWatch supports two database approaches:

1) **Terraform-provisioned Cloud SQL Postgres** (GCP-native)
- The Terraform stack in `infra/gcp/cloud_run_demo/` can provision Cloud SQL.
- The provided tfvars profiles enable Cloud SQL by default.

2) **External hosted Postgres** (often cheaper for demos)
- Disable Cloud SQL in Terraform and point `DATABASE_URL` at your external Postgres.

If you choose Cloud SQL, keep:
- the smallest instance size that meets your needs
- low storage
- reasonable log retention

---

## Guardrails in Terraform

Terraform adds deliberate safety checks:

- To make `env=stage|prod` public, you must set:
  - `allow_unauthenticated=true`
  - AND `allow_public_in_non_dev=true`

This prevents accidental “make prod public” incidents.

---

## When you outgrow this

Common next steps:
- Put operator UX behind IAP (LB + IAP) and keep ingest public
- Perimeter rate limiting + WAF (Cloud Armor / API Gateway / Cloudflare)
- Telemetry storage scale path (partitioning + rollups)
- Pub/Sub buffering + replay/backfill patterns
- SLOs/burn alerts tuned to fleet size
- OpenTelemetry traces (optional)
