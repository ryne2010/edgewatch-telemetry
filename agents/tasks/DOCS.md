# Task: Documentation Update

## Objective

Improve documentation so agents and humans can reason over the system
without tribal knowledge.

## Steps

1.  Identify which doc is the source of truth.
2.  Make the smallest edit that clarifies:
    -   intent
    -   invariants
    -   boundaries
    -   operational behavior
3.  Cross-link from `AGENTS.md` if it's an entry point.
4.  Validate formatting/lint.

## Validation

-   `python scripts/harness.py lint`
