# Task: Bug Fix

## Objective

Fix a defect with a regression test that proves the bug is fixed and
prevents recurrence.

## Steps

1.  Create or identify a reproduction:
    -   failing test preferred
    -   minimal script if needed
2.  Identify the violated invariant or boundary.
3.  Implement the smallest fix that restores the invariant.
4.  Add a regression test.
5.  Validate.
6.  Summarize changes using `agents/checklists/CHANGE_SUMMARY.md`.

## Validation

-   `python scripts/harness.py lint`
-   `python scripts/harness.py test`

## Escalation

-   The bug is rooted in unclear product intent.
-   Fix requires contract changes or migrations.
