# Task: Refactor (No Behavior Change)

## Objective

Improve code structure/clarity without changing externally observable
behavior.

## Rules

-   No contract changes.
-   Add characterization tests if behavior is not already well
    specified.

## Steps

1.  Identify the target area and "why".
2.  Add/ensure tests that lock behavior.
3.  Refactor in small steps:
    -   rename for clarity
    -   extract functions/modules
    -   reduce coupling
4.  Validate.
5.  Summarize changes using `agents/checklists/CHANGE_SUMMARY.md`.

## Validation

-   `python scripts/harness.py lint`
-   `python scripts/harness.py test`

## Escalation

-   Refactor reveals missing invariants that need product/architectural
    decisions.
