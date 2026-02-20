# PR Review Checklist

Use this checklist for human or reviewer-agent review.

## Intent

-   [ ] The PR clearly states what and why.
-   [ ] Non-goals are explicit (scope control).

## Architecture

-   [ ] Boundaries/layering rules in `docs/DESIGN.md` are respected.
-   [ ] No cross-layer leakage or new circular dependencies.

## Contracts and invariants

-   [ ] `docs/CONTRACTS.md` invariants remain true.
-   [ ] Public interfaces are documented and stable (or ADR exists for
    breaking change).

## Validation

-   [ ] Lint is green (`python scripts/harness.py lint`)
-   [ ] Tests are green (`python scripts/harness.py test`)
-   [ ] Typecheck is green if applicable
    (`python scripts/harness.py typecheck`)
-   [ ] New tests cover new behavior and regressions.

## Observability

-   [ ] Logs/metrics/traces remain useful and do not leak secrets.
-   [ ] Critical path changes include observability updates.

## Maintainability

-   [ ] Names are clear and consistent.
-   [ ] Complexity is reasonable; refactor suggestions captured if
    needed.
-   [ ] Docs updated if behavior/contracts changed.

## Rollout / risk

-   [ ] Risk is assessed; rollback plan exists if needed.
-   [ ] Follow-ups are filed if debt is introduced.
