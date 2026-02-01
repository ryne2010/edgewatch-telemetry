# Drift detection (Terraform)

This repo includes a scheduled GitHub Actions workflow:

- `.github/workflows/terraform-drift.yml`

It runs a `terraform plan -detailed-exitcode` on a schedule to detect **drift**
(resources changed outside of Terraform).

## Why it matters

In real teams, drift happens:
- an emergency hotfix
- a console change
- a manual permission tweak

Drift detection gives you:
- early visibility
- a clean audit trail (workflow logs)
- confidence that Terraform is still the source of truth

## How to enable

1) Configure Workload Identity Federation (WIF) for GitHub Actions (see `docs/WIF_GITHUB_ACTIONS.md`)
2) Set GitHub Actions repo variables:
   - `PROJECT_ID`
   - `REGION`
   - `TFSTATE_BUCKET`
   - `TFSTATE_PREFIX`

Then the scheduled workflow will run automatically.

## What to do when drift is detected

- Review the plan output in the workflow logs.
- Decide whether:
  - the manual change should be reverted (preferred), or
  - Terraform should be updated to match the new desired state.
- Create a PR with the Terraform fix and re-apply via the apply workflow.
