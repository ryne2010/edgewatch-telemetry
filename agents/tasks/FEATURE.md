# Task: Feature Implementation

## Objective

Implement a new feature while preserving architecture, contracts, and
observability.

## Steps

1.  Restate intent, constraints, and non-goals.
2.  Identify impacted layers/boundaries in `docs/DESIGN.md`.
3.  Identify contract implications in `docs/CONTRACTS.md`.
4.  Implement the smallest coherent slice:
    -   prefer adding a thin API surface
    -   keep domain logic isolated
5.  Add tests:
    -   unit tests for logic
    -   integration tests for boundary crossings
6.  Add/adjust observability if the feature affects critical paths.
7.  Validate (see below).
8.  Summarize changes using `agents/checklists/CHANGE_SUMMARY.md`.

## Validation

-   `python scripts/harness.py lint`
-   `python scripts/harness.py test`
-   `python scripts/harness.py typecheck` (if configured)

## Escalation

-   Feature requires changing a public contract or invariant.
-   Feature breaks an architectural boundary.
