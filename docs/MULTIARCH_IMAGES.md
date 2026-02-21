# Multi-arch container images (amd64 + arm64)

EdgeWatch targets:

- **Cloud Run** (expects `linux/amd64`)
- **Apple Silicon dev laptops** (usually `linux/arm64`)
- **Raspberry Pi** (usually `linux/arm64`)

A **multi-arch** container image is a single tag that contains multiple platform variants
(e.g. `linux/amd64` + `linux/arm64`). The runtime (Cloud Run, Docker) pulls the correct
variant automatically.

> Cloud Run still requires that the image includes a `linux/amd64` variant.

---

## Recommended: GitHub Actions publishes multi-arch to Artifact Registry

This repo includes a workflow:

- `.github/workflows/publish-image-multiarch.yml`

It builds and pushes a **manifest list** to Artifact Registry containing:

- `linux/amd64`
- `linux/arm64`

### Prerequisites

1) Configure GitHub → GCP auth via Workload Identity Federation (WIF).

See: `docs/WIF_GITHUB_ACTIONS.md`

2) Set these GitHub Actions repository variables:

- `PROJECT_ID`
- `REGION` (example: `us-central1`)
- `AR_REPO` (example: `edgewatch`)
- `GCP_WIF_PROVIDER`
- `GCP_WIF_SERVICE_ACCOUNT`

3) Ensure the deploy service account has `roles/artifactregistry.writer`.

### Run it

GitHub → **Actions** → **Publish Multi-Arch Image (Artifact Registry)**

Inputs:

- `env`: just a label for operator clarity (does not change infrastructure)
- `tag`: optional; default is commit SHA
- `image_name`: default `edgewatch-api`
- `ar_repo`: optional override

Example image ref produced:

```
us-central1-docker.pkg.dev/<PROJECT_ID>/<AR_REPO>/edgewatch-api:<TAG>
```

### Verify the manifest

After publishing:

```bash
docker buildx imagetools inspect \
  us-central1-docker.pkg.dev/<PROJECT_ID>/<AR_REPO>/edgewatch-api:<TAG>
```

You should see both `linux/amd64` and `linux/arm64` listed.

---

## Local dev: build + push multi-arch from your M2 Max

If you want to publish from your laptop (slower than CI, but works):

```bash
make init PROJECT_ID=<your-project> REGION=us-central1
make auth

# Configure docker auth for Artifact Registry
make docker-login-gcp

# Build and push a multi-arch image (amd64+arm64)
TAG=$(git rev-parse HEAD) make build-multiarch
```

Notes:

- Building `linux/amd64` on Apple Silicon uses emulation; expect it to be slower.
- CI publishing via GitHub Actions is typically faster and more repeatable.

---

## Deploying a multi-arch image to Cloud Run

Cloud Run will pull the `linux/amd64` variant automatically.

If you published an image tag yourself (instead of Cloud Build), you can deploy by:

```bash
TAG=<tag-you-published> make apply-gcp ENV=stage TFVARS=infra/gcp/cloud_run_demo/profiles/stage_private_iam.tfvars
make migrate-gcp ENV=stage
make verify-gcp-ready ENV=stage
```

Or, if you prefer a single target:

```bash
TAG=<tag-you-published> make deploy-gcp-safe-multiarch ENV=stage TFVARS=infra/gcp/cloud_run_demo/profiles/stage_private_iam.tfvars
```

---

## Using the image on Raspberry Pi

Most of the time, the Pi runs the **agent** directly (systemd + Python), not the full Cloud Run API container.

However, if you ever want to run the full stack container on an `arm64` device for testing,
Docker will pull the `linux/arm64` variant automatically.

(For production RPi agent setup, see `docs/DEPLOY_RPI.md`.)
