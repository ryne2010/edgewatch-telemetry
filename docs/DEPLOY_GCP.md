# Deploy to GCP (Cloud Run + Terraform)

This repo is designed to deploy cleanly to a single GCP project using Terraform + Cloud Run.

## What gets deployed

Infrastructure (Terraform):
- APIs / baseline services
- Artifact Registry
- Cloud Run service (container built and pushed by Cloud Build)
- Observability as code:
  - dashboards + basic alerts
  - service-scoped log bucket + log view (for least-privilege client access)
  - availability SLO + burn-rate alerts

Optional:
- project-level IAM bindings for Google Groups (standalone mode)

---

## 0) Prereqs

On macOS:

- `gcloud`
- `terraform`
- `docker` (optional; used for local lint/sec/policy checks)
- Python 3.11+ (the app)
- Node 18+ (UI tooling, if applicable)

Auth:

```bash
gcloud auth login
gcloud auth application-default login
```

---

## 1) Set your project + region (no env var exports needed)

This repo’s Makefile reads your active gcloud config.

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud config set run/region us-central1
```

Sanity check:

```bash
make doctor
```

---

## 2) Deploy (dev)

One command will:
- create the remote state bucket (if missing)
- run Terraform (APIs, AR, SAs, Cloud Run, dashboards, log views, SLOs)
- build + push container via Cloud Build
- verify endpoints

```bash
make deploy ENV=dev
```

---

## 3) (Optional) Enable Google Groups IAM

If you want group-based IAM in this repo (standalone demo mode), set:

```hcl
workspace_domain  = "example.com"
group_prefix      = "edgewatch"
enable_project_iam = true
```

Recommended for real teams:
- manage project IAM centrally in Repo 3 (`terraform-gcp-platform`)
- keep app repos focused on app-scoped resources

See `docs/IAM_STARTER_PACK.md`.

---

## 4) Verify

```bash
make url
make verify
```

---

## 5) Observability

See:
- `docs/OBSERVABILITY.md` (dashboards + alerts + SLOs)
- `docs/IAM_STARTER_PACK.md` (client log view access pattern)

---

## 6) Keyless CI/CD (WIF) + drift detection

This repo includes workflow templates:

- `.github/workflows/terraform-apply-gcp.yml`
- `.github/workflows/terraform-drift.yml`

To enable, bootstrap WIF in Repo 3:
- `terraform-gcp-platform/docs/WIF_GITHUB_ACTIONS.md`
- `terraform-gcp-platform/examples/github_actions_wif/`

Then set the GitHub repo Secrets + Variables described in `docs/WIF_GITHUB_ACTIONS.md`.

---

## Cleanup

```bash
make destroy ENV=dev
```

This destroys Terraform-managed resources but **keeps the remote state bucket**.
