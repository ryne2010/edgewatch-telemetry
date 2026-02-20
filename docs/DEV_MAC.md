# macOS (M2 Max) development setup

Target machine: **Apple Silicon (M2 Max MacBook Pro)**.

This repo is intentionally "local-first": you can run the full stack with Docker Compose.

---

## 1) Install prerequisites

### Homebrew

Install Homebrew (if you don't have it already).

### Docker Desktop

- Install Docker Desktop for Mac
- Ensure Docker is running (you should be able to run `docker info`)

**Cloud Run note (architecture):**

Cloud Run expects Linux `x86_64` / `linux/amd64` images.

- This repo uses **Cloud Build** for GCP builds to avoid Apple Silicon cross-arch issues.
- If you do build/push images from your M2 laptop manually, use:

```bash
docker build --platform linux/amd64 -t your-image:tag .
```

### gcloud SDK

Install the Google Cloud SDK.

Common Homebrew install:

```bash
brew install --cask google-cloud-sdk
```

Then add it to your shell (Homebrew prints the exact command).

### Terraform

```bash
brew tap hashicorp/tap
brew install hashicorp/tap/terraform
```

### uv (Python)

Install uv (fast Python tooling):

```bash
brew install uv
```

### Node.js

Recommended: Node 20 LTS.

You can use:
- `brew install node@20`
- `nvm`
- `mise`

### pnpm

This repo is pnpm-friendly.

Recommended:

```bash
corepack enable
```

Then pnpm will be available automatically via the `packageManager` field.

---

## 2) Run locally (fast path)

From repo root:

```bash
make doctor
make hygiene
make up

# For full local toolchain checks (uv/node/pnpm) used by harness + UI dev:
make doctor-dev
```

Open:
- UI: `http://localhost:8082`
- API docs: `http://localhost:8082/docs`

Create a demo device:

```bash
make demo-device
```

Simulate a 3-device fleet:

```bash
make simulate
```

---

## 3) DB migrations

This repo uses **Alembic** migrations (`migrations/`).

- `make up` runs migrations automatically (compose `migrate` service)
- after schema changes, apply migrations with:

```bash
make db-migrate
```

To create a new migration revision (after changing models):

```bash
make db-revision msg="add_my_table"
```

See runbook: `docs/RUNBOOKS/DB.md`.

---

## 4) Quality gates (recommended before PRs)

```bash
make fmt
make lint
make typecheck
make test
make hygiene
```

Or:

```bash
make harness
```

---

## 5) GCP deploy lane

```bash
make init GCLOUD_CONFIG=personal-portfolio PROJECT_ID=YOUR_PROJECT_ID REGION=us-central1
make auth
make doctor-gcp

make db-secret
make admin-secret

# Public demo posture (dev)
make deploy-gcp-demo

# Or: production posture (private IAM)
make deploy-gcp-prod

# Or: explicit lane
# make deploy-gcp-safe ENV=dev
# or: make deploy-gcp ENV=dev && make migrate-gcp ENV=dev && make verify-gcp-ready ENV=dev
```

See `docs/DEPLOY_GCP.md`.

## Lockfiles

EdgeWatch enforces reproducible runs via `uv.lock`.

- If you change `pyproject.toml` dependencies, run:

```bash
make lock
```
