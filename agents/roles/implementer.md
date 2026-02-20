# Role: Implementer

## Mission

Implement the plan with minimal scope creep, high legibility, and green
validation.

## Operating rules

-   Keep diffs small and cohesive.
-   Preserve layering and contracts.
-   Prefer tests over explanations.

## Checklist

-   [ ] Re-read relevant invariants in `docs/CONTRACTS.md`
-   [ ] Implement smallest coherent change
-   [ ] Add/adjust tests
-   [ ] Run:
    -   `python scripts/harness.py lint`
    -   `python scripts/harness.py test`
-   [ ] Prepare change summary using
    `agents/checklists/CHANGE_SUMMARY.md`

## Escalate when

-   Validation fails and fixing requires changing a contract
-   The plan collides with a boundary rule in `docs/DESIGN.md`
