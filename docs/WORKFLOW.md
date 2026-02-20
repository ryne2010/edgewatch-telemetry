# WORKFLOW.md

This document standardizes how humans and agents execute work in this repo.

## The standard loop

1) **Clarify intent**
   - restate goal
   - list constraints and non-goals

2) **Plan**
   - small steps
   - explicit acceptance criteria
   - validation strategy

3) **Implement**
   - smallest coherent diff first
   - keep boundaries intact (see `docs/DESIGN.md`)

4) **Validate**

```bash
python scripts/harness.py lint
python scripts/harness.py typecheck
python scripts/harness.py test
```

5) **Review**
   - self-review using `agents/checklists/PR_REVIEW.md`

6) **Summarize**
   - use `agents/checklists/CHANGE_SUMMARY.md`

## Autonomy gradient

- **Low risk** (docs, comments, small refactors): proceed with minimal coordination.
- **Medium risk** (bugfixes, small features): follow the full loop; add targeted tests.
- **High risk** (security, auth, contracts, infra changes): require ADR + human review.

## Definition of done

A change is done when:
- intent is satisfied
- invariants and boundaries remain intact
- relevant tests pass
- docs are updated if behavior/contracts changed
- a change summary exists

## Infra changes

If you modify Terraform under `infra/gcp/**`, also run:

```bash
make tf-check
```

(These checks also run in CI.)

## Artifacts to update

Update these when relevant:
- `docs/DOMAIN.md` — domain rules + vocabulary
- `docs/DESIGN.md` — boundaries/layering
- `docs/CONTRACTS.md` — public interfaces + invariants
- `docs/DECISIONS/` — significant decisions
- `docs/RUNBOOKS/` and/or `RUNBOOK.md` — operational behavior

## Pre-commit (optional but recommended)

If you use pre-commit locally:

```bash
uv tool install pre-commit
pre-commit install
```

Hooks are defined in `.pre-commit-config.yaml` and run the same gates as CI.
