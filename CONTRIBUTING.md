# Contributing

This repo is designed for **agent-first execution** with human-defined
invariants. Keep contributions small, testable, and legible.

## Principles

-   The repo is the system of record: encode decisions in versioned
    docs.
-   Prefer mechanical validation over subjective review.
-   Preserve architectural boundaries and contracts.

## Before you change behavior

If a change affects public interfaces, invariants, or architecture: 1.
Write or update an ADR in `docs/DECISIONS/`. 2. Update
`docs/CONTRACTS.md` and/or `docs/DESIGN.md`. 3. Ensure tests cover the
intended behavior.

## Tooling setup

- Python (preferred): `uv sync --dev`
- Node/TS (preferred): `pnpm install`

If your repo uses Go or Rust, the harness will also run `go` / `cargo` commands when `go.mod` / `Cargo.toml` are present.

## Development loop

-   Plan the change.
-   Implement the smallest coherent slice.
-   Validate locally:
    -   `python scripts/harness.py lint`
    -   `python scripts/harness.py test`
    -   `python scripts/harness.py typecheck` (if configured)
-   Update docs if behavior or contracts changed.

## Pull request expectations

Use the PR template. A PR should include: - the intent ("what" and
"why") - risks and rollout notes if relevant - validation evidence
(commands run, results) - follow-up tasks if debt was introduced

## Decision records (ADR)

Use `docs/DECISIONS/ADR_TEMPLATE.md` for significant changes. Prefer
short, decisive ADRs: - context - decision - consequences - alternatives
considered

## Agent contributions

Agents should: - start from `AGENTS.md` - work in small diffs - run the
harness before final output - summarize changes using
`agents/checklists/CHANGE_SUMMARY.md` - escalate if intent or contracts
are unclear
