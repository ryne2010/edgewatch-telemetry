# Agents

This folder encodes **role definitions, task templates, and checklists**
for multi-agent workflows.

## Roles

-   `roles/planner.md` -- decomposes work, identifies risks, defines
    acceptance criteria and validation
-   `roles/implementer.md` -- makes changes with minimal scope creep and
    high legibility
-   `roles/reviewer.md` -- critiques changes against invariants,
    boundaries, and failure modes
-   `roles/maintainer.md` -- reduces entropy via cleanup/refactors
    without behavior changes

## Task templates

Use `tasks/` for repeatable execution patterns: - `FEATURE.md` -
`BUGFIX.md` - `REFACTOR.md` - `DOCS.md` - `TASK_TEMPLATE.md` (start here
for new tasks)

## Checklists

-   `checklists/PR_REVIEW.md` -- structured review against invariants
-   `checklists/CHANGE_SUMMARY.md` -- standard change summary format
-   `checklists/ESCALATION.md` -- when to ask for human judgment

## Protocol: explicit handoffs

When handing work between agents, include:

-   Current state
-   What's done
-   What's next
-   Open risks / questions
-   Validation status (commands run + results)

This prevents context loss and reduces rework.
