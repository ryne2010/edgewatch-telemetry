# Manual Deploy to GCP (Cloud Run + Terraform + WIF) for EdgeWatch

This runbook mirrors the production-grade/team-friendly workflow you used in `grounded-knowledge-platform`, adapted for this repo.

What this guide sets up:

- Reuse the same GCP project.
- Reuse the same Terraform state bucket (`<project>-tfstate`).
- Create a repo-specific WIF provider for `ryneschroder/edgewatch-telemetry`.
- Create a repo-specific deploy service account for EdgeWatch CI/CD.
- Use separate config prefixes in GCS:
  - `gs://<config-bucket>/edgewatch/dev`
  - `gs://<config-bucket>/edgewatch/stage`
  - `gs://<config-bucket>/edgewatch/prod`

This aligns with the workflows in:

- `.github/workflows/gcp-terraform-plan.yml`
- `.github/workflows/terraform-apply-gcp.yml`
- `.github/workflows/deploy-gcp.yml`
- `.github/workflows/terraform-drift.yml`

## Prereqs

- `gcloud`
- `terraform`
- access to GitHub repo settings (Environment variables)

Authenticate (interactive):

```bash
gcloud auth login
gcloud auth application-default login
```

Optional but recommended:

```bash
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

## 0) Set shared variables

Run once per shell session:

```bash
PROJECT_ID="YOUR_PROJECT_ID"
REGION="us-central1"
GITHUB_REPO="ryneschroder/edgewatch-telemetry"

TFSTATE_BUCKET="${PROJECT_ID}-tfstate"   # reused from grounded setup
CONFIG_BUCKET="${PROJECT_ID}-config"     # can be reused; different prefixes

POOL_ID="edgewatch-gh-pool"
PROVIDER_ID="edgewatch-gh-provider"
CI_SA_ID="sa-edgewatch-ci"
CI_SA_EMAIL="${CI_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "${PROJECT_ID}"
gcloud config set run/region "${REGION}"
```

## 1) Ensure required APIs are enabled

```bash
gcloud services enable \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  cloudresourcemanager.googleapis.com \
  serviceusage.googleapis.com
```

## 2) Ensure buckets exist (reuse tfstate, reuse/create config)

```bash
# tfstate bucket (reused)
gcloud storage buckets describe "gs://${TFSTATE_BUCKET}" >/dev/null 2>&1 \
  || gcloud storage buckets create "gs://${TFSTATE_BUCKET}" \
      --location="${REGION}" \
      --uniform-bucket-level-access \
      --public-access-prevention=enforced
gcloud storage buckets update "gs://${TFSTATE_BUCKET}" --versioning

# config bucket (shared is fine)
gcloud storage buckets describe "gs://${CONFIG_BUCKET}" >/dev/null 2>&1 \
  || gcloud storage buckets create "gs://${CONFIG_BUCKET}" \
      --location="${REGION}" \
      --uniform-bucket-level-access \
      --public-access-prevention=enforced
gcloud storage buckets update "gs://${CONFIG_BUCKET}" --versioning
```

## 3) Create repo-specific deploy SA + WIF provider

Create service account if missing:

```bash
gcloud iam service-accounts describe "${CI_SA_EMAIL}" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "${CI_SA_ID}" \
      --display-name="EdgeWatch CI (Terraform)"
```

Create workload identity pool/provider if missing:

```bash
gcloud iam workload-identity-pools describe "${POOL_ID}" --location=global >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools create "${POOL_ID}" \
      --location=global \
      --display-name="EdgeWatch GitHub Pool"

gcloud iam workload-identity-pools providers describe "${PROVIDER_ID}" \
  --location=global \
  --workload-identity-pool="${POOL_ID}" >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools providers create-oidc "${PROVIDER_ID}" \
      --location=global \
      --workload-identity-pool="${POOL_ID}" \
      --issuer-uri="https://token.actions.githubusercontent.com" \
      --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
      --attribute-condition="assertion.repository=='${GITHUB_REPO}' && assertion.ref=='refs/heads/main'"
```

Bind provider principal to the CI SA:

```bash
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
PRINCIPAL="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${GITHUB_REPO}"

gcloud iam service-accounts add-iam-policy-binding "${CI_SA_EMAIL}" \
  --member="${PRINCIPAL}" \
  --role="roles/iam.workloadIdentityUser"

gcloud iam service-accounts add-iam-policy-binding "${CI_SA_EMAIL}" \
  --member="${PRINCIPAL}" \
  --role="roles/iam.serviceAccountTokenCreator"
```

## 4) Grant deploy permissions to CI SA

For a personal sandbox, `roles/owner` works fastest. For team-grade posture, use a curated role set:

```bash
for ROLE in \
  roles/run.admin \
  roles/iam.serviceAccountAdmin \
  roles/iam.serviceAccountUser \
  roles/artifactregistry.admin \
  roles/cloudbuild.builds.editor \
  roles/secretmanager.admin \
  roles/serviceusage.serviceUsageAdmin \
  roles/resourcemanager.projectIamAdmin \
  roles/monitoring.admin \
  roles/logging.configWriter \
  roles/cloudscheduler.admin \
  roles/cloudsql.admin \
  roles/compute.networkAdmin
do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${CI_SA_EMAIL}" \
    --role="${ROLE}" \
    --condition=None
done
```

Grant bucket access needed by workflows:

```bash
# config bundle read (and optional write if you want CI to update files later)
gcloud storage buckets add-iam-policy-binding "gs://${CONFIG_BUCKET}" \
  --member="serviceAccount:${CI_SA_EMAIL}" \
  --role="roles/storage.objectViewer"

gcloud storage buckets add-iam-policy-binding "gs://${CONFIG_BUCKET}" \
  --member="serviceAccount:${CI_SA_EMAIL}" \
  --role="roles/storage.objectAdmin"

# terraform state read/write
gcloud storage buckets add-iam-policy-binding "gs://${TFSTATE_BUCKET}" \
  --member="serviceAccount:${CI_SA_EMAIL}" \
  --role="roles/storage.objectAdmin"
```

## 5) Create config bundle objects for dev/stage/prod

### 5a) Write backend config per env

```bash
for ENV in dev stage prod; do
  cat <<EOF | gcloud storage cp - "gs://${CONFIG_BUCKET}/edgewatch/${ENV}/backend.hcl"
bucket = "${TFSTATE_BUCKET}"
prefix = "edgewatch/${ENV}"
EOF
done
```

### 5b) Seed terraform.tfvars per env

Use shipped profiles as the base:

```bash
gcloud storage cp infra/gcp/cloud_run_demo/profiles/dev_public_demo.tfvars \
  "gs://${CONFIG_BUCKET}/edgewatch/dev/terraform.tfvars"

gcloud storage cp infra/gcp/cloud_run_demo/profiles/stage_private_iam.tfvars \
  "gs://${CONFIG_BUCKET}/edgewatch/stage/terraform.tfvars"

gcloud storage cp infra/gcp/cloud_run_demo/profiles/prod_private_iam.tfvars \
  "gs://${CONFIG_BUCKET}/edgewatch/prod/terraform.tfvars"
```

If needed, pull/edit/push:

```bash
ENV="dev"
gcloud storage cp "gs://${CONFIG_BUCKET}/edgewatch/${ENV}/terraform.tfvars" ./tmp.${ENV}.tfvars
# edit ./tmp.${ENV}.tfvars
gcloud storage cp ./tmp.${ENV}.tfvars "gs://${CONFIG_BUCKET}/edgewatch/${ENV}/terraform.tfvars"
rm -f ./tmp.${ENV}.tfvars
```

## 6) Set GitHub Environment variables

In GitHub repo settings, create environments: `dev`, `stage`, `prod`.

Set these variables in each environment:

- `GCP_WIF_PROVIDER`
- `GCP_WIF_SERVICE_ACCOUNT`
- `GCP_TF_CONFIG_GCS_PATH`

Values:

```bash
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
echo "GCP_WIF_PROVIDER=projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"
echo "GCP_WIF_SERVICE_ACCOUNT=${CI_SA_EMAIL}"
echo "DEV GCP_TF_CONFIG_GCS_PATH=gs://${CONFIG_BUCKET}/edgewatch/dev"
echo "STAGE GCP_TF_CONFIG_GCS_PATH=gs://${CONFIG_BUCKET}/edgewatch/stage"
echo "PROD GCP_TF_CONFIG_GCS_PATH=gs://${CONFIG_BUCKET}/edgewatch/prod"
```

Set `PROJECT_ID` and `REGION` as repository-level variables (or environment-level if you prefer).

## 7) Verify config bundle locally (optional)

Use repo helpers:

```bash
# dev
make tf-config-pull-gcp ENV=dev TF_CONFIG_BUCKET="${CONFIG_BUCKET}"
make tf-init-gcp ENV=dev TF_BACKEND_HCL=backend.hcl
make plan-gcp ENV=dev TF_BACKEND_HCL=backend.hcl
```

## 8) Deploy via GitHub Actions

Recommended sequence:

1. `Terraform plan (GCP)` with `env=dev`
2. `Terraform apply (GCP)` with `env=dev`
3. `Deploy to GCP (Cloud Run)` with `env=dev`

Then promote similarly for `stage` and `prod`.

## Troubleshooting

- `403` on GCS config download:
  - confirm `roles/storage.objectViewer` on `gs://<config-bucket>` for CI SA.
- `403` writing Terraform state:
  - confirm `roles/storage.objectAdmin` on `gs://<project>-tfstate` for CI SA.
- WIF auth failure:
  - check `GCP_WIF_PROVIDER` is exact resource string.
  - verify provider condition includes `assertion.repository=='ryneschroder/edgewatch-telemetry'`.
  - if deploying from non-`main` branch, update `assertion.ref` condition accordingly.
- Terraform apply permission errors:
  - temporarily grant `roles/owner` to CI SA to prove it is IAM scope, then tighten roles.
