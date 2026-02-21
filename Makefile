# EdgeWatch Telemetry — team-ready workflow (Makefile)
#
# Two lanes:
#   1) Local-first stack (Docker Compose)
#   2) Optional GCP demo deploy (Cloud Run)
#
# Staff-level goals:
# - No manual `export ...` blocks for GCP deploys
# - Remote Terraform state by default (GCS)
# - Plan/apply separation
# - Cloud Build builds to avoid macOS cross-arch pain
# - Clear Make targets + discoverable docs

SHELL := /bin/bash

# -----------------------------
# Local stack
# -----------------------------
COMPOSE ?= docker compose

# Defaults for local simulator (override as needed)
EDGEWATCH_API_URL ?= http://localhost:8082
EDGEWATCH_DEVICE_ID ?= demo-well-001
EDGEWATCH_DEVICE_TOKEN ?= dev-device-token-001
ADMIN_API_KEY ?= dev-admin-key
SIMULATE_FLEET_SIZE ?= 3

# -----------------------------
# GCP deployment defaults
# -----------------------------
PROJECT_ID ?= $(shell gcloud config get-value project 2>/dev/null)
REGION     ?= $(shell gcloud config get-value run/region 2>/dev/null)
REGION     ?= us-central1

ENV ?= dev

SERVICE_NAME ?= edgewatch-$(ENV)
AR_REPO      ?= edgewatch
IMAGE_NAME   ?= edgewatch-api
TAG          ?= latest

TF_DIR ?= infra/gcp/cloud_run_demo

# Optional Terraform var-file (profiles)
TFVARS ?=
ifeq ($(strip $(TFVARS)),)
TFVARS_ARG :=
else
TFVARS_ARG := -var-file="$(TFVARS)"
endif

TF_STATE_BUCKET ?= $(PROJECT_ID)-tfstate
TF_STATE_PREFIX ?= edgewatch/$(ENV)

# Workspace IAM starter pack (optional; Google Groups)
WORKSPACE_DOMAIN ?=
GROUP_PREFIX ?= edgewatch

# Observability as code
ENABLE_OBSERVABILITY ?= true

# Reproducibility: avoid environment-specific package indexes when generating lockfiles.
UV_DEFAULT_INDEX ?= https://pypi.org/simple


IMAGE := $(REGION)-docker.pkg.dev/$(PROJECT_ID)/$(AR_REPO)/$(IMAGE_NAME):$(TAG)

# -----------------------------
# Helpers
# -----------------------------

define require
	@command -v $(1) >/dev/null 2>&1 || (echo "Missing dependency: $(1)"; exit 1)
endef

.PHONY: \
	help init auth \
	doctor doctor-dev doctor-gcp \
	buildx-init docker-login-gcp build-multiarch deploy-gcp-safe-multiarch \
	clean \
	db-up db-down api-dev web-install web-dev \
	up down reset logs db-migrate db-revision \
	demo-device devices alerts simulate retention \
	bootstrap-state-gcp tf-init-gcp infra-gcp plan-gcp apply-gcp grant-cloudbuild-gcp build-gcp \
	deploy-gcp deploy-gcp-safe deploy-gcp-safe-multiarch \
	url-gcp url-gcp-admin url-gcp-dashboard verify-gcp verify-gcp-ready logs-gcp \
	migrate-gcp offline-check-local offline-check-gcp simulate-gcp analytics-export-gcp retention-gcp destroy-gcp \
	plan-gcp-demo apply-gcp-demo deploy-gcp-demo \
	plan-gcp-stage apply-gcp-stage deploy-gcp-stage \
	plan-gcp-stage-iot apply-gcp-stage-iot deploy-gcp-stage-iot \
	plan-gcp-stage-iot-lp apply-gcp-stage-iot-lp deploy-gcp-stage-iot-lp \
	plan-gcp-prod apply-gcp-prod deploy-gcp-prod \
	plan-gcp-prod-iot apply-gcp-prod-iot deploy-gcp-prod-iot \
	plan-gcp-prod-iot-lp apply-gcp-prod-iot-lp deploy-gcp-prod-iot-lp \
	db-secret admin-secret lock hygiene \
	fmt lint typecheck test build harness harness-doctor \
	tf-fmt tf-validate tf-lint tf-sec tf-policy tf-checkov tf-check \
	dist

help:
	@echo "Local targets:"
	@echo "  init             One-time setup for GCP deploys (persist gcloud project/region)"
	@echo "  auth             Authenticate gcloud user + ADC (interactive)"
	@echo "  doctor           Check local Docker prerequisites"
	@echo "  doctor-dev       Check full local toolchain (uv/node/pnpm)"
	@echo "  db-up            Start ONLY the local Postgres container (fast dev lane)"
	@echo "  db-down          Stop ONLY the local Postgres container"
	@echo "  api-dev          Run FastAPI on the host with hot reload (port 8080)"
	@echo "  web-install      Install UI deps (pnpm workspace)"
	@echo "  web-dev          Run UI dev server (Vite) on the host (port 5173)"
	@echo "  up               Start local stack"
	@echo "  down             Stop local stack"
	@echo "  reset            Remove volumes and reset local data"
	@echo "  logs             Tail local logs"
	@echo "  db-migrate       Apply Alembic migrations (docker compose migrate)"
	@echo "  db-revision      Create new Alembic revision (msg=...)"
	@echo "  demo-device      Create a demo device via admin API"
	@echo "  simulate         Run the edge simulator fleet (3 by default)"
	@echo "  retention        Run DB retention/compaction (deletes old telemetry)"
	@echo "  devices          List devices"
	@echo "  alerts           List recent alerts"
	@echo ""
	@echo "GCP targets (optional):"
	@echo "  deploy-gcp       Deploy to Cloud Run (defaults to private IAM-only)"
	@echo "  deploy-gcp-safe  Deploy + migrate + readiness verify"
	@echo "  deploy-gcp-demo  Deploy the public demo profile"
	@echo "  deploy-gcp-stage Deploy the staging profile (private IAM + simulation)"
	@echo "  deploy-gcp-prod  Deploy the production profile (private IAM)"
	@echo "  plan-gcp         Terraform plan"
	@echo "  apply-gcp        Terraform apply"
	@echo "  (tip) TFVARS=... Use a Terraform profile var-file (see infra/gcp/cloud_run_demo/profiles/)"
	@echo "  url-gcp          Print service URL"
	@echo "  url-gcp-admin    Print admin service URL (if enabled)"
	@echo "  url-gcp-dashboard Print dashboard service URL (if enabled)"
	@echo "  verify-gcp       Hit /health"
	@echo "  verify-gcp-ready Hit /readyz (DB + migrations)"
	@echo "  logs-gcp         Read Cloud Run logs"
	@echo "  migrate-gcp      Run DB migrations via Cloud Run Job"
	@echo "  offline-check-local Run offline check against local docker-compose stack"
	@echo "  offline-check-gcp Manually run offline check via Cloud Run Job"
	@echo "  simulate-gcp     Manually run synthetic telemetry via Cloud Run Job"
	@echo "  analytics-export-gcp Manually run analytics export via Cloud Run Job"
	@echo "  destroy-gcp      Terraform destroy (keeps tfstate bucket)"
	@echo "  db-secret        Add DATABASE_URL secret version (stdin)"
	@echo "  admin-secret     Add ADMIN_API_KEY secret version (stdin)"
	@echo ""
	@echo ""
	@echo "Container image targets (optional):"
	@echo "  buildx-init         Ensure a local docker buildx builder exists and is bootstrapped"
	@echo "  docker-login-gcp    Configure docker auth for Artifact Registry (gcloud)"
	@echo "  build-multiarch     Build and push a multi-arch image (linux/amd64 + linux/arm64) via buildx"
	@echo "  deploy-gcp-safe-multiarch  build-multiarch + terraform apply + migrate + /readyz verify"
	@echo ""
	@echo "Reproducibility:"
	@echo "  lock             Generate uv.lock + pnpm-lock.yaml"
	@echo "  clean            Remove local runtime caches/artifacts (__pycache__, *.pyc, sqlite buffers, policy cache)"
	@echo "  dist             Create a clean distribution zip under ./dist/"

clean:
	@set -euo pipefail; \
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +; \
	find . -name "*.pyc" -type f -delete; \
	rm -rf .pytest_cache .ruff_cache .pyright; \
	rm -f edgewatch_buffer.sqlite edgewatch_buffer.sqlite3 agent/edgewatch_buffer.sqlite agent/edgewatch_buffer.sqlite3; \
	rm -f ./edgewatch_policy_cache_*.json ./agent/edgewatch_policy_cache_*.json; \
	find . -name ".DS_Store" -type f -delete; \
	echo "Cleaned caches/artifacts."







# -----------------------------
# Init (team onboarding)
# -----------------------------
# `make init` persists `PROJECT_ID` and `REGION` into your active gcloud configuration.
# This avoids copy/pasting `export ...` blocks and keeps team workflows consistent.
#
# Usage (recommended for teams):
#   make init GCLOUD_CONFIG=edgewatch-demo PROJECT_ID=my-proj REGION=us-central1
#
# Usage (current gcloud config):
#   make init PROJECT_ID=my-proj REGION=us-central1
#
# Notes:
# - This target does NOT create projects or enable billing.
# - This target does NOT run Terraform; it only configures gcloud defaults and prints next steps.
# - If you switch gcloud configs in this command, re-run your next make command in a fresh invocation.
init:
	@command -v gcloud >/dev/null 2>&1 || (echo "Missing dependency: gcloud (https://cloud.google.com/sdk/docs/install)"; exit 1)
	@set -e; \
	  echo "== Init: configure gcloud defaults =="; \
	  if [ -n "$(GCLOUD_CONFIG)" ]; then \
	    if gcloud config configurations describe "$(GCLOUD_CONFIG)" >/dev/null 2>&1; then :; else \
	      echo "Creating gcloud configuration: $(GCLOUD_CONFIG)"; \
	      gcloud config configurations create "$(GCLOUD_CONFIG)" >/dev/null; \
	    fi; \
	    echo "Activating gcloud configuration: $(GCLOUD_CONFIG)"; \
	    gcloud config configurations activate "$(GCLOUD_CONFIG)" >/dev/null; \
	  fi; \
	  proj="$(PROJECT_ID)"; \
	  if [ -z "$$proj" ]; then proj=$$(gcloud config get-value project 2>/dev/null || true); fi; \
	  region="$(REGION)"; \
	  if [ -z "$$proj" ]; then \
	    echo "ERROR: PROJECT_ID is not set."; \
	    echo "Fix: run 'make init PROJECT_ID=<your-project-id> REGION=<region>'"; \
	    exit 1; \
	  fi; \
	  echo "Setting gcloud defaults..."; \
	  gcloud config set project "$$proj" >/dev/null; \
	  gcloud config set run/region "$$region" >/dev/null; \
	  active=$$(gcloud config configurations list --filter=is_active:true --format='value(name)' 2>/dev/null | head -n1); \
	  echo ""; \
	  echo "Configured:"; \
	  echo "  project: $$proj"; \
	  echo "  region:  $$region"; \
	  echo "  gcloud config: $${active:-default}"; \
	  echo ""; \
	  acct=$$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -n1 || true); \
	  if [ -z "$$acct" ]; then \
	    echo "Auth status: not logged in"; \
	    echo "Next: make auth"; \
	  else \
	    echo "Auth status: $$acct"; \
	  fi; \
	  echo ""; \
	  echo "Next steps (GCP deploy lane):"; \
	  echo "  make doctor-gcp"; \
	  echo "  make deploy-gcp"; \
	  echo ""; \
	  echo "Tip: if you changed gcloud configs, run the next make command in a fresh invocation."

# Interactive auth helper (explicit on purpose).
# This will open browser windows for OAuth flows.
auth:
	@command -v gcloud >/dev/null 2>&1 || (echo "Missing dependency: gcloud"; exit 1)
	@echo "This will open a browser window for gcloud login + ADC."
	gcloud auth login
	gcloud auth application-default login

# Local doctor
# -----------------------------
# Doctor (prerequisite checks)
# -----------------------------
# Local lane doctor: verifies tools needed to run the local Docker Compose stack and UI dev.
doctor:
	@set -e; \
	fail=0; \
	echo "== Doctor: EdgeWatch (local/docker) =="; \
	echo ""; \
	echo "Required:"; \
	if command -v docker >/dev/null 2>&1; then \
	  echo "  ✓ docker: $$(docker --version)"; \
	  if docker info >/dev/null 2>&1; then \
	    echo "  ✓ docker daemon: running"; \
	  else \
	    echo "  ✗ docker daemon not running (start Docker Desktop)"; \
	    fail=1; \
	  fi; \
	  if docker compose version >/dev/null 2>&1; then \
	    echo "  ✓ docker compose: $$(docker compose version | head -n1)"; \
	  else \
	    echo "  ✗ docker compose not available (install Docker Desktop / Compose v2)"; \
	    fail=1; \
	  fi; \
	else \
	  echo "  ✗ docker not found (install Docker Desktop)"; \
	  fail=1; \
	fi; \
	if command -v jq >/dev/null 2>&1; then \
	  echo "  ✓ jq: $$(jq --version)"; \
	else \
	  echo "  ⚠ jq not found (optional; makes curl output pretty). Install: brew install jq"; \
	fi; \
	echo ""; \
	echo "Recommended (for harness tasks + UI dev):"; \
	if command -v uv >/dev/null 2>&1; then \
	  echo "  ✓ uv: $$(uv --version)"; \
	else \
	  echo "  ⚠ uv not found. Install: https://docs.astral.sh/uv/"; \
	fi; \
	if command -v node >/dev/null 2>&1; then \
	  echo "  ✓ node: $$(node -v)"; \
	else \
	  echo "  ⚠ node not found. Install: https://nodejs.org/"; \
	fi; \
	if command -v pnpm >/dev/null 2>&1; then \
	  echo "  ✓ pnpm: $$(pnpm -v)"; \
	else \
	  echo "  ⚠ pnpm not found. Enable corepack: corepack enable"; \
	fi; \
	echo ""; \
	if [ "$$fail" -ne 0 ]; then \
	  echo "Doctor failed: fix missing items above, then re-run."; \
	  exit $$fail; \
	fi; \
	echo "Doctor OK."

# Full local dev doctor: verifies toolchain required for harness (uv + Node + pnpm).
doctor-dev: doctor
	@set -e; \
	fail=0; \
	echo "== Doctor: EdgeWatch (local/dev toolchain) =="; \
	echo ""; \
	if command -v uv >/dev/null 2>&1; then \
	  echo "  ✓ uv: $$(uv --version)"; \
	else \
	  echo "  ✗ uv not found. Install: https://docs.astral.sh/uv/"; \
	  fail=1; \
	fi; \
	if command -v node >/dev/null 2>&1; then \
	  echo "  ✓ node: $$(node -v)"; \
	else \
	  echo "  ✗ node not found. Install: https://nodejs.org/"; \
	  fail=1; \
	fi; \
	if command -v pnpm >/dev/null 2>&1; then \
	  echo "  ✓ pnpm: $$(pnpm -v)"; \
	else \
	  echo "  ✗ pnpm not found. Enable corepack: corepack enable"; \
	  fail=1; \
	fi; \
	echo ""; \
	echo "Local simulator defaults (override with VAR=...):"; \
	echo "  EDGEWATCH_API_URL=$(EDGEWATCH_API_URL)"; \
	echo "  EDGEWATCH_DEVICE_ID=$(EDGEWATCH_DEVICE_ID)"; \
	echo "  EDGEWATCH_DEVICE_TOKEN=$(EDGEWATCH_DEVICE_TOKEN)"; \
	echo "  ADMIN_API_KEY=$(ADMIN_API_KEY)"; \
	echo ""; \
	if [ "$$fail" -ne 0 ]; then \
	  echo "Doctor-dev failed: fix missing items above, then re-run."; \
	  exit $$fail; \
	fi; \
	echo "Doctor-dev OK."

# Cloud lane doctor: verifies tools and config required to deploy the API to Cloud Run using Terraform + Cloud Build.
doctor-gcp:
	@set -e; \
	fail=0; \
	echo "== Doctor: EdgeWatch (GCP deploy) =="; \
	echo ""; \
	echo "Resolved config (override with VAR=...):"; \
	echo "  PROJECT_ID=$(PROJECT_ID)"; \
	echo "  REGION=$(REGION)"; \
	echo "  ENV=$(ENV)"; \
	echo "  SERVICE_NAME=$(SERVICE_NAME)"; \
	echo "  IMAGE=$(IMAGE)"; \
	echo "  TF_STATE_BUCKET=$(TF_STATE_BUCKET)"; \
	echo "  TF_STATE_PREFIX=$(TF_STATE_PREFIX)"; \
		echo "  WORKSPACE_DOMAIN=$(WORKSPACE_DOMAIN)"; \
		echo "  GROUP_PREFIX=$(GROUP_PREFIX)"; \
		echo "  ENABLE_OBSERVABILITY=$(ENABLE_OBSERVABILITY)"; \
	echo ""; \
	echo "Required for Cloud deploy:"; \
	if command -v gcloud >/dev/null 2>&1; then \
	  echo "  ✓ gcloud: $$(gcloud --version 2>/dev/null | head -n1)"; \
	else \
	  echo "  ✗ gcloud not found. Install: https://cloud.google.com/sdk/docs/install"; \
	  fail=1; \
	fi; \
	if command -v terraform >/dev/null 2>&1; then \
	  echo "  ✓ terraform: $$(terraform version | head -n1)"; \
	else \
	  echo "  ✗ terraform not found. Install: https://developer.hashicorp.com/terraform/downloads"; \
	  fail=1; \
	fi; \
	if [ -z "$(PROJECT_ID)" ]; then \
	  echo "  ✗ gcloud project not set. Run: gcloud config set project <PROJECT_ID>"; \
	  fail=1; \
	else \
	  echo "  ✓ gcloud project set"; \
	fi; \
	if [ -z "$(REGION)" ]; then \
	  echo "  ⚠ gcloud run/region not set. Recommended: gcloud config set run/region us-central1"; \
	else \
	  echo "  ✓ gcloud run/region: $(REGION)"; \
	fi; \
	if command -v gcloud >/dev/null 2>&1; then \
	  acct=$$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -n1); \
	  if [ -n "$$acct" ]; then \
	    echo "  ✓ gcloud user auth: $$acct"; \
	  else \
	    echo "  ⚠ gcloud user not authenticated. Run: gcloud auth login"; \
	  fi; \
	  if gcloud auth application-default print-access-token >/dev/null 2>&1; then \
	    echo "  ✓ ADC credentials: OK"; \
	  else \
	    echo "  ⚠ ADC not configured. Run: gcloud auth application-default login"; \
	  fi; \
	fi; \
	echo ""; \
	if [ "$$fail" -ne 0 ]; then \
	  echo "Doctor failed: fix missing items above, then re-run."; \
	  exit $$fail; \
	fi; \
	echo "Doctor OK."
up: doctor
	cp -n .env.example .env || true
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

reset:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) logs -f --tail=200


# Fast dev lane (host-run API/UI, Docker DB)
db-up: doctor
	$(COMPOSE) up -d db

db-down:
	$(COMPOSE) stop db

api-dev: doctor-dev db-up
	@echo "Starting API dev server (hot reload) on http://localhost:8080"; \
	DATABASE_URL="postgresql+psycopg://edgewatch:edgewatch@localhost:5435/edgewatch" \
	APP_ENV=dev AUTO_MIGRATE=1 ENABLE_SCHEDULER=1 LOG_FORMAT=text \
	uv run --locked uvicorn api.app.main:app --reload --host 0.0.0.0 --port 8080

web-install: doctor-dev
	@echo "Installing UI deps (pnpm workspace)"; \
	corepack enable; \
	if [ -f pnpm-lock.yaml ]; then \
	  pnpm install --frozen-lockfile; \
	else \
	  pnpm install --no-frozen-lockfile; \
	fi

web-dev: doctor-dev
	@echo "Starting UI dev server on http://localhost:5173"; \
	corepack enable; \
	pnpm -C web dev --host 0.0.0.0 --port 5173


# Apply DB migrations locally (uses the compose 'migrate' service).
db-migrate: doctor
	$(COMPOSE) run --rm migrate

# Create a new migration revision. Usage: make db-revision msg="add_foo"
db-revision: doctor-dev
	@if [ -z "$(msg)" ]; then echo "msg is required. Example: make db-revision msg=add_devices"; exit 2; fi
	uv run alembic revision -m "$(msg)" --autogenerate

# Create a demo device using the admin API.
# NOTE: default ADMIN_API_KEY comes from api/app/config.py and .env.example.
demo-device:
	@set -euo pipefail; \
	resp=$$(curl -fsS -X POST "$(EDGEWATCH_API_URL)/api/v1/admin/devices" \
	  -H "X-Admin-Key: $(ADMIN_API_KEY)" \
	  -H "Content-Type: application/json" \
	  -d '{"device_id":"$(EDGEWATCH_DEVICE_ID)","display_name":"Demo Well 001","token":"$(EDGEWATCH_DEVICE_TOKEN)","heartbeat_interval_s":300,"offline_after_s":900}'); \
	if command -v jq >/dev/null 2>&1; then echo "$$resp" | jq .; else echo "$$resp"; fi


# Run the edge simulator (pretends to be an RPi).
simulate: doctor-dev
	cp -n agent/.env.example agent/.env || true
	@set -euo pipefail; \
	trap 'kill 0' INT TERM EXIT; \
	base_id="$(EDGEWATCH_DEVICE_ID)"; \
	base_tok="$(EDGEWATCH_DEVICE_TOKEN)"; \
	echo "Starting $(SIMULATE_FLEET_SIZE) simulators... (Ctrl-C to stop all)"; \
	for n in $$(seq 1 "$(SIMULATE_FLEET_SIZE)"); do \
	  if [[ "$$base_id" =~ ^(.*)([0-9]{3})$$ ]]; then id="$$(printf "%s%03d" "$${BASH_REMATCH[1]}" "$$n")"; else id="$$base_id"; if [[ "$$n" -gt 1 ]]; then id="$$base_id-$$(printf "%03d" "$$n")"; fi; fi; \
	  if [[ "$$base_tok" =~ ^(.*)([0-9]{3})$$ ]]; then tok="$$(printf "%s%03d" "$${BASH_REMATCH[1]}" "$$n")"; else tok="$$base_tok"; if [[ "$$n" -gt 1 ]]; then tok="$$base_tok-$$(printf "%03d" "$$n")"; fi; fi; \
	  buf="./edgewatch_buffer_$${id}.sqlite"; \
	  echo "  - $$id (token suffix $$(printf "%03d" "$$n"))"; \
	  EDGEWATCH_API_URL="$(EDGEWATCH_API_URL)" EDGEWATCH_DEVICE_ID="$$id" EDGEWATCH_DEVICE_TOKEN="$$tok" BUFFER_DB_PATH="$$buf" \
	    uv run python agent/simulator.py & \
	done; \
	wait

devices:
	@set -euo pipefail; \
	resp=$$(curl -fsS "$(EDGEWATCH_API_URL)/api/v1/devices"); \
	if command -v jq >/dev/null 2>&1; then echo "$$resp" | jq .; else echo "$$resp"; fi

alerts:
	@set -euo pipefail; \
	resp=$$(curl -fsS "$(EDGEWATCH_API_URL)/api/v1/alerts?limit=25"); \
	if command -v jq >/dev/null 2>&1; then echo "$$resp" | jq .; else echo "$$resp"; fi

# -----------------------------
# GCP deploy lane (Cloud Run)
# -----------------------------

bootstrap-state-gcp: doctor-gcp
	@echo "Ensuring tfstate bucket exists: gs://$(TF_STATE_BUCKET)"
	@if gcloud storage buckets describe "gs://$(TF_STATE_BUCKET)" >/dev/null 2>&1; then \
		echo "Bucket already exists."; \
	else \
		echo "Creating bucket..."; \
		gcloud storage buckets create "gs://$(TF_STATE_BUCKET)" --location="$(REGION)" --uniform-bucket-level-access --public-access-prevention=enforced; \
		echo "Enabling versioning..."; \
		gcloud storage buckets update "gs://$(TF_STATE_BUCKET)" --versioning; \
	fi

tf-init-gcp: bootstrap-state-gcp
	terraform -chdir=$(TF_DIR) init -reconfigure \
		-backend-config="bucket=$(TF_STATE_BUCKET)" \
		-backend-config="prefix=$(TF_STATE_PREFIX)"

infra-gcp: tf-init-gcp
	terraform -chdir=$(TF_DIR) apply -auto-approve \
		$(TFVARS_ARG) \
		-var "project_id=$(PROJECT_ID)" \
		-var "region=$(REGION)" \
		-var "env=$(ENV)" \
		-var "workspace_domain=$(WORKSPACE_DOMAIN)" \
		-var "group_prefix=$(GROUP_PREFIX)" \
		-var "enable_observability=$(ENABLE_OBSERVABILITY)" \
		-var "service_name=$(SERVICE_NAME)" \
		-var "artifact_repo_name=$(AR_REPO)" \
		-var "image=$(IMAGE)" \
		-target=module.core_services \
		-target=module.artifact_registry \
		-target=module.service_accounts \
		-target=module.secrets

plan-gcp: tf-init-gcp
	terraform -chdir=$(TF_DIR) plan \
		$(TFVARS_ARG) \
		-var "project_id=$(PROJECT_ID)" \
		-var "region=$(REGION)" \
		-var "env=$(ENV)" \
		-var "workspace_domain=$(WORKSPACE_DOMAIN)" \
		-var "group_prefix=$(GROUP_PREFIX)" \
		-var "enable_observability=$(ENABLE_OBSERVABILITY)" \
		-var "service_name=$(SERVICE_NAME)" \
		-var "artifact_repo_name=$(AR_REPO)" \
		-var "image=$(IMAGE)"

apply-gcp: tf-init-gcp
	terraform -chdir=$(TF_DIR) apply -auto-approve \
		$(TFVARS_ARG) \
		-var "project_id=$(PROJECT_ID)" \
		-var "region=$(REGION)" \
		-var "env=$(ENV)" \
		-var "workspace_domain=$(WORKSPACE_DOMAIN)" \
		-var "group_prefix=$(GROUP_PREFIX)" \
		-var "enable_observability=$(ENABLE_OBSERVABILITY)" \
		-var "service_name=$(SERVICE_NAME)" \
		-var "artifact_repo_name=$(AR_REPO)" \
		-var "image=$(IMAGE)"

grant-cloudbuild-gcp: doctor-gcp
	@PROJECT_NUMBER=$$(gcloud projects describe "$(PROJECT_ID)" --format='value(projectNumber)'); \
	echo "Granting Cloud Build writer on Artifact Registry (project $$PROJECT_NUMBER)"; \
	gcloud projects add-iam-policy-binding "$(PROJECT_ID)" \
	  --member="serviceAccount:$${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
	  --role="roles/artifactregistry.writer" \
	  --condition=None >/dev/null



# -----------------------------
# Container images (multi-arch)
# -----------------------------

# Ensure a local buildx builder exists and is bootstrapped.
# (Required for multi-platform builds.)
buildx-init: doctor
	@set -euo pipefail; \
	  if docker buildx inspect edgewatch-builder >/dev/null 2>&1; then \
	    docker buildx use edgewatch-builder >/dev/null; \
	  else \
	    echo "Creating docker buildx builder: edgewatch-builder"; \
	    docker buildx create --name edgewatch-builder --use >/dev/null; \
	  fi; \
	  docker buildx inspect --bootstrap >/dev/null; \
	  echo "Buildx builder ready."

# Configure docker auth for Artifact Registry.
docker-login-gcp: doctor-gcp
	@echo "Configuring docker auth for Artifact Registry: $(REGION)-docker.pkg.dev"
	gcloud auth configure-docker "$(REGION)-docker.pkg.dev" --quiet

# Build and push a *single tag* containing linux/amd64 + linux/arm64 variants.
#
# Notes:
# - Cloud Run will automatically pull the linux/amd64 variant.
# - Apple Silicon + Raspberry Pi will automatically pull linux/arm64.
# - This lane is optional; the default `build-gcp` target uses Cloud Build.
build-multiarch: doctor doctor-gcp infra-gcp buildx-init docker-login-gcp
	@echo "Building + pushing multi-arch image via buildx: $(IMAGE)"
	docker buildx build --platform linux/amd64,linux/arm64 -t "$(IMAGE)" --push .

# Safe deploy sequence using the multi-arch build lane.
deploy-gcp-safe-multiarch: build-multiarch apply-gcp migrate-gcp verify-gcp-ready

build-gcp: doctor-gcp infra-gcp grant-cloudbuild-gcp
	@echo "Building + pushing via Cloud Build: $(IMAGE)"
	gcloud builds submit --tag "$(IMAGE)" .

deploy-gcp: build-gcp apply-gcp verify-gcp

# Safe deploy sequence: deploy service, run migrations via Cloud Run Job, then verify readiness.
deploy-gcp-safe: build-gcp apply-gcp migrate-gcp verify-gcp-ready

# Opinionated shortcuts (Terraform profiles)
plan-gcp-demo:
	$(MAKE) plan-gcp ENV=dev TFVARS=infra/gcp/cloud_run_demo/profiles/dev_public_demo.tfvars

apply-gcp-demo:
	$(MAKE) apply-gcp ENV=dev TFVARS=infra/gcp/cloud_run_demo/profiles/dev_public_demo.tfvars

deploy-gcp-demo:
	$(MAKE) deploy-gcp-safe ENV=dev TFVARS=infra/gcp/cloud_run_demo/profiles/dev_public_demo.tfvars

plan-gcp-stage:
	$(MAKE) plan-gcp ENV=stage TFVARS=infra/gcp/cloud_run_demo/profiles/stage_private_iam.tfvars

apply-gcp-stage:
	$(MAKE) apply-gcp ENV=stage TFVARS=infra/gcp/cloud_run_demo/profiles/stage_private_iam.tfvars

deploy-gcp-stage:
	$(MAKE) deploy-gcp-safe ENV=stage TFVARS=infra/gcp/cloud_run_demo/profiles/stage_private_iam.tfvars

plan-gcp-stage-iot:
	$(MAKE) plan-gcp ENV=stage TFVARS=infra/gcp/cloud_run_demo/profiles/stage_public_ingest_private_admin.tfvars

apply-gcp-stage-iot:
	$(MAKE) apply-gcp ENV=stage TFVARS=infra/gcp/cloud_run_demo/profiles/stage_public_ingest_private_admin.tfvars

deploy-gcp-stage-iot:
	$(MAKE) deploy-gcp-safe ENV=stage TFVARS=infra/gcp/cloud_run_demo/profiles/stage_public_ingest_private_admin.tfvars

plan-gcp-stage-iot-lp:
	$(MAKE) plan-gcp ENV=stage TFVARS=infra/gcp/cloud_run_demo/profiles/stage_public_ingest_private_dashboard_private_admin.tfvars

apply-gcp-stage-iot-lp:
	$(MAKE) apply-gcp ENV=stage TFVARS=infra/gcp/cloud_run_demo/profiles/stage_public_ingest_private_dashboard_private_admin.tfvars

deploy-gcp-stage-iot-lp:
	$(MAKE) deploy-gcp-safe ENV=stage TFVARS=infra/gcp/cloud_run_demo/profiles/stage_public_ingest_private_dashboard_private_admin.tfvars

plan-gcp-prod:
	$(MAKE) plan-gcp ENV=prod TFVARS=infra/gcp/cloud_run_demo/profiles/prod_private_iam.tfvars

apply-gcp-prod:
	$(MAKE) apply-gcp ENV=prod TFVARS=infra/gcp/cloud_run_demo/profiles/prod_private_iam.tfvars

deploy-gcp-prod:
	$(MAKE) deploy-gcp-safe ENV=prod TFVARS=infra/gcp/cloud_run_demo/profiles/prod_private_iam.tfvars

plan-gcp-prod-iot:
	$(MAKE) plan-gcp ENV=prod TFVARS=infra/gcp/cloud_run_demo/profiles/prod_public_ingest_private_admin.tfvars

apply-gcp-prod-iot:
	$(MAKE) apply-gcp ENV=prod TFVARS=infra/gcp/cloud_run_demo/profiles/prod_public_ingest_private_admin.tfvars

deploy-gcp-prod-iot:
	$(MAKE) deploy-gcp-safe ENV=prod TFVARS=infra/gcp/cloud_run_demo/profiles/prod_public_ingest_private_admin.tfvars

plan-gcp-prod-iot-lp:
	$(MAKE) plan-gcp ENV=prod TFVARS=infra/gcp/cloud_run_demo/profiles/prod_public_ingest_private_dashboard_private_admin.tfvars

apply-gcp-prod-iot-lp:
	$(MAKE) apply-gcp ENV=prod TFVARS=infra/gcp/cloud_run_demo/profiles/prod_public_ingest_private_dashboard_private_admin.tfvars

deploy-gcp-prod-iot-lp:
	$(MAKE) deploy-gcp-safe ENV=prod TFVARS=infra/gcp/cloud_run_demo/profiles/prod_public_ingest_private_dashboard_private_admin.tfvars

url-gcp: tf-init-gcp
	@terraform -chdir=$(TF_DIR) output -raw service_url

url-gcp-admin: tf-init-gcp
	@terraform -chdir=$(TF_DIR) output -raw admin_service_url

url-gcp-dashboard: tf-init-gcp
	@terraform -chdir=$(TF_DIR) output -raw dashboard_service_url

verify-gcp: doctor-gcp tf-init-gcp
	@set -euo pipefail; \
	URL=$$(terraform -chdir=$(TF_DIR) output -raw service_url); \
	echo "Service URL: $$URL"; \
	token=$$(gcloud auth print-identity-token 2>/dev/null || true); \
	if [ -n "$$token" ]; then \
	  curl -fsS -H "Authorization: Bearer $$token" "$$URL/health" >/dev/null && echo "OK: /health"; \
	else \
	  if curl -fsS "$$URL/health" >/dev/null; then \
	    echo "OK: /health"; \
	  else \
	    echo "Health check failed. If the service is private, ensure you have roles/run.invoker and run: make auth"; \
	    exit 1; \
	  fi; \
	fi

# Readiness check includes DB connectivity + migrations (alembic_version table exists).
verify-gcp-ready: doctor-gcp tf-init-gcp
	@set -euo pipefail; \
	URL=$$(terraform -chdir=$(TF_DIR) output -raw service_url); \
	echo "Service URL: $$URL"; \
	token=$$(gcloud auth print-identity-token 2>/dev/null || true); \
	if [ -n "$$token" ]; then \
	  curl -fsS -H "Authorization: Bearer $$token" "$$URL/readyz" >/dev/null && echo "OK: /readyz"; \
	else \
	  if curl -fsS "$$URL/readyz" >/dev/null; then \
	    echo "OK: /readyz"; \
	  else \
	    echo "Readiness check failed. If the service is private, ensure you have roles/run.invoker and run: make auth"; \
	    exit 1; \
	  fi; \
	fi

logs-gcp: doctor-gcp
	gcloud run services logs read "$(SERVICE_NAME)" --region "$(REGION)" --limit 100


# Run alembic migrations using the Cloud Run Job created by Terraform.
# This is the recommended pattern for prod/stage rollouts.
migrate-gcp: doctor-gcp
	@gcloud run jobs execute "edgewatch-migrate-$(ENV)" --region "$(REGION)" --wait

# Run the offline check job against the local docker-compose stack.
offline-check-local:
	@docker compose exec -T api python -m api.app.jobs.offline_check

# Manually trigger the offline check job (useful for smoke tests).
offline-check-gcp: doctor-gcp
	@gcloud run jobs execute "edgewatch-offline-check-$(ENV)" --region "$(REGION)" --wait

# Manually trigger synthetic telemetry generation when enabled.
simulate-gcp: doctor-gcp
	@gcloud run jobs execute "edgewatch-simulate-telemetry-$(ENV)" --region "$(REGION)" --wait

# Manually trigger the analytics export job when enabled.
analytics-export-gcp: doctor-gcp
	@gcloud run jobs execute "edgewatch-analytics-export-$(ENV)" --region "$(REGION)" --wait

destroy-gcp: tf-init-gcp
	terraform -chdir=$(TF_DIR) destroy -auto-approve \
		$(TFVARS_ARG) \
		-var "project_id=$(PROJECT_ID)" \
		-var "region=$(REGION)" \
		-var "env=$(ENV)" \
		-var "workspace_domain=$(WORKSPACE_DOMAIN)" \
		-var "group_prefix=$(GROUP_PREFIX)" \
		-var "enable_observability=$(ENABLE_OBSERVABILITY)" \
		-var "service_name=$(SERVICE_NAME)" \
		-var "artifact_repo_name=$(AR_REPO)" \
		-var "image=$(IMAGE)"

# Secret helper targets

db-secret: doctor-gcp
	@echo "Paste DATABASE_URL then press Ctrl-D (example: postgresql+psycopg://user:pass@host:5432/edgewatch)";
	@gcloud secrets versions add edgewatch-database-url --data-file=-

admin-secret: doctor-gcp
	@echo "Paste ADMIN_API_KEY then press Ctrl-D";
	@gcloud secrets versions add edgewatch-admin-api-key --data-file=-

# Lockfiles
lock: doctor-dev
	@echo "Generating uv.lock (Python)"; uv lock --default-index "$(UV_DEFAULT_INDEX)"
	@echo "Generating pnpm-lock.yaml (workspace)"; pnpm install
	@echo "Done. Commit uv.lock and pnpm-lock.yaml for team reproducibility."

hygiene:
	python scripts/repo_hygiene.py


# -----------------------------------------------------------------------------
# Staff-level IaC hygiene (lint / security / policy)
#
# These targets are optional locally (CI always runs them). They are convenient
# for "pre-flight" checks before a PR.
#
# We try to use locally-installed tools if present; otherwise we fall back to
# running the tool in a container (requires Docker).
# -----------------------------------------------------------------------------

POLICY_DIR := infra/gcp/policy

.PHONY: tf-fmt tf-validate tf-lint tf-sec tf-policy tf-checkov tf-check

# checkov can be noisy for small demo stacks. By default we run it in
# "soft-fail" mode so findings are visible without blocking other work.
# Set CHECKOV_SOFT_FAIL=0 to make it a hard gate.
CHECKOV_SOFT_FAIL ?= 1

tf-fmt: ## Terraform fmt check (no changes)
	@terraform -chdir=$(TF_DIR) fmt -check -recursive

tf-validate: ## Terraform validate (no remote backend required)
	@terraform -chdir=$(TF_DIR) init -backend=false >/dev/null
	@terraform -chdir=$(TF_DIR) validate

tf-lint: ## tflint (falls back to docker)
	@if command -v tflint >/dev/null 2>&1; then \
	  echo "Running tflint (local)"; \
	  (cd $(TF_DIR) && tflint --init && tflint); \
	else \
	  echo "tflint not found; running via Docker"; \
	  tf_parent=$$(dirname "$(TF_DIR)"); \
	  tf_leaf=$$(basename "$(TF_DIR)"); \
	  docker run --rm --entrypoint sh -v "$$(pwd)/$$tf_parent:/workspace" -w "/workspace/$$tf_leaf" ghcr.io/terraform-linters/tflint:latest -lc 'tflint --init && tflint'; \
	fi

tf-sec: ## tfsec (falls back to docker)
	@if command -v tfsec >/dev/null 2>&1; then \
	  echo "Running tfsec (local)"; \
	  tfsec $(TF_DIR); \
	else \
	  echo "tfsec not found; running via Docker"; \
	  docker run --rm -v "$$(pwd):/src" aquasec/tfsec:latest /src/$(TF_DIR); \
	fi

tf-policy: ## OPA/Conftest policy gate for Terraform (falls back to docker)
	@TF_FILES=$$(find "$(TF_DIR)" -type f -name '*.tf' ! -path '*/.terraform/*' | sort); \
	if [ -z "$$TF_FILES" ]; then \
	  echo "No Terraform files found under $(TF_DIR)"; \
	  exit 1; \
	fi; \
	if command -v conftest >/dev/null 2>&1; then \
	  echo "Running conftest (local)"; \
	  conftest test --rego-version v0 --parser hcl2 --policy $(POLICY_DIR) $$TF_FILES; \
	else \
	  echo "conftest not found; running via Docker"; \
	  docker run --rm -v "$$(pwd):/project" -w /project openpolicyagent/conftest:latest test --rego-version v0 --parser hcl2 --policy $(POLICY_DIR) $$TF_FILES; \
	fi

tf-checkov: ## checkov IaC policy scan (falls back to docker; soft-fail by default)
	@set +e; \
	status=0; \
	if command -v checkov >/dev/null 2>&1; then \
	  echo "Running checkov (local)"; \
	  checkov -d $(TF_DIR); \
	  status=$$?; \
	else \
	  echo "checkov not found; running via Docker"; \
	  docker run --rm -v "$$(pwd):/src" -w /src bridgecrew/checkov:latest -d /src/$(TF_DIR); \
	  status=$$?; \
	fi; \
	if [ "$(CHECKOV_SOFT_FAIL)" = "1" ] && [ $$status -ne 0 ]; then \
	  echo "checkov reported findings (exit $$status) — soft-fail enabled (CHECKOV_SOFT_FAIL=1)"; \
	  exit 0; \
	fi; \
	exit $$status

tf-check: tf-fmt tf-validate tf-lint tf-sec tf-policy tf-checkov ## Run all Terraform hygiene checks


# -----------------------------------------------------------------------------
# Harness / repo-quality gates (agent-friendly)
#
# These targets are intentionally separate from the local "doctor" target.
# Use them for lint/test/typecheck in a consistent way (locally and in CI).
# -----------------------------------------------------------------------------

.PHONY: fmt lint typecheck test build harness harness-doctor

fmt:
	python scripts/harness.py fmt

lint:
	python scripts/harness.py lint

typecheck:
	python scripts/harness.py typecheck

test:
	python scripts/harness.py test

build:
	python scripts/harness.py build

harness:
	python scripts/harness.py all

harness-doctor:
	python scripts/harness.py doctor

# -----------------------------------------------------------------------------
# Distribution packaging
# -----------------------------------------------------------------------------

.PHONY: dist

dist: clean ## Create a clean distribution zip under ./dist/
	python scripts/package_dist.py


# Retention / compaction
retention:
	@echo "Running retention/compaction job (RETENTION_ENABLED must be true)."
	RETENTION_ENABLED=true python -m api.app.jobs.retention

retention-gcp:
	$(call require,gcloud)
	@echo "Executing Cloud Run retention job: edgewatch-retention-$(ENV)"
	gcloud run jobs execute edgewatch-retention-$(ENV) --region $(REGION) --project $(PROJECT_ID) --wait
