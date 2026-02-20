# Intended production posture (cost-min + secure)

This repo supports **two** main deployment postures on GCP.

The intent is to keep costs low *and* avoid unsafe defaults.

---

## Posture A: Public portfolio demo (dev)

Use this when you want to share a live link quickly.

**Characteristics**
- Cloud Run service is **public** (`allow_unauthenticated=true`)
- Hard cost caps (scale-to-zero + `max_instances=1`)
- Demo device bootstrap enabled (dev-only)

**Deploy**

```bash
make deploy-gcp-demo PROJECT_ID=... REGION=us-central1
```

**Notes**
- If the endpoint is public, any request that reaches your container can incur cost.
- Keep `max_instances` low and avoid logging full telemetry payloads.

---

## Posture B: Production (private IAM)

Use this for "real" production (or a safer long-lived demo).

**Characteristics**
- Cloud Run service is **private** (IAM-only invocations)
- Cloud Run still scales to zero (no always-on compute cost)
- Migrations and background checks run as **Cloud Run Jobs**
- No demo credentials shipped

**Deploy**

```bash
make deploy-gcp-prod PROJECT_ID=... REGION=us-central1
```

**Operational notes**
- Your user/service account needs `roles/run.invoker` on the Cloud Run service.
- `make verify-gcp` and `make verify-gcp-ready` automatically try to call the service
  with `gcloud auth print-identity-token`.

---

## Database cost reality check

For low-traffic apps, the database is usually the **primary cost driver**.

This repo intentionally does **not** provision a database to keep coupling and costs low.

Recommended options (in increasing cost / decreasing friction):

1. **External hosted Postgres** (cheapest for a portfolio demo)
2. **Small Cloud SQL Postgres** (GCP-native, but rarely "free")
3. **Private IP Cloud SQL + VPC connector** (more secure networking, higher baseline cost)

Tip: if you choose Cloud SQL, keep:
- the smallest instance size that meets your needs
- low storage
- short log retention

---

## Guardrails in Terraform

Terraform adds a deliberate safety check:

- To make `env=stage|prod` public, you must set:
  - `allow_unauthenticated=true`
  - AND `allow_public_in_non_dev=true`

This prevents accidental "make prod public" incidents.

---

## When you outgrow this posture

Common next steps (kept as tasks for a future iteration):
- Add a real auth layer (IAP / OIDC)
- Rate limiting (Cloud Armor / Cloudflare)
- Split ingestion (fast path) from analytics (warehouse)
- Pub/Sub buffering + replay/backfill patterns
- SLOs/burn alerts tuned to fleet size
