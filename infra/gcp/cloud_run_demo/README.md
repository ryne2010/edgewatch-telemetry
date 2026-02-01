# Cloud Run deployment (Terraform) — EdgeWatch

This Terraform root deploys the **EdgeWatch API + UI** to **Cloud Run**.

What this demonstrates:
- remote Terraform state (GCS)
- Artifact Registry + Cloud Build image build flow
- Secret Manager (DATABASE_URL, ADMIN_API_KEY)
- optional Serverless VPC Access connector (disabled by default)
- optional **Google Groups IAM starter pack** (`iam_bindings.tf`)
- optional **dashboards + alerts as code** (`observability.tf`)

> Like other portfolio repos, this example does not provision a database to keep costs and coupling low. Point `DATABASE_URL` to Cloud SQL, AlloyDB, or another Postgres.

## Quickstart

From the repo root:

```bash
make doctor-gcp
make deploy-gcp ENV=dev
```

## Variables

Terraform variables (passed by the Makefile):
- `env` — `dev|stage|prod`
- `workspace_domain` + `group_prefix` — optional Google Group IAM bindings
- `enable_observability` — create dashboard + alert policies

## Optional

### Enable the VPC connector

> Not free. Use for demos of private connectivity patterns.

```bash
TF_VAR_enable_vpc_connector=true make plan-gcp ENV=dev
TF_VAR_enable_vpc_connector=true make apply-gcp ENV=dev
```
