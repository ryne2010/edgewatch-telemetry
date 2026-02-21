# Task 20 — Edge protection for public ingest (Cloud Armor / API Gateway)

🟡 **Status: Planned**

## Objective

Harden the **public ingest service** using GCP edge controls so accidental exposure does not become a cost/security incident.

This complements the in-app protections already present:

- request size limits
- points-per-request limits
- device-scoped rate limiting

## Scope

### In-scope

Provide one of the following (prefer Cloud Armor first):

1) **Cloud Armor** rate limiting + basic WAF rules in front of the public ingest service.
2) Optional: **API Gateway** or **Cloud Endpoints** posture for:
   - auth boundary
   - quotas
   - request validation

Key requirements:

- Terraform-first setup.
- Maintain the existing least-privilege multi-service layout.

## Design notes

### Cloud Armor approach

- Place the ingest service behind an external HTTPS LB.
- Attach a Cloud Armor policy:
  - global rate limits
  - optional allowlist for known IP ranges (if applicable)

### API Gateway approach

- Use API Gateway for:
  - quotas
  - request validation
  - JWT auth if moving beyond device tokens

## Acceptance criteria

- Public ingest has an edge rate limit independent of app logic.
- A runbook exists describing:
  - what policy is enabled
  - how to tune it
  - what logs/metrics to observe

## Deliverables

- Terraform updates under `infra/gcp/cloud_run_demo/`
- Docs:
  - `docs/security.md`
  - `docs/PRODUCTION_POSTURE.md`
  - a new runbook: `docs/RUNBOOKS/EDGE_PROTECTION.md`

## Validation

- Terraform validate + plan
- Manual smoke:
  - confirm rate limit triggers at edge
