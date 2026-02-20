# Debugging Runbook

This runbook standardizes how to debug issues so both humans and agents
can follow the same process.

## 1) Triage

-   What is broken?
-   Who/what is impacted?
-   What changed recently? (deploys, config, dependencies)
-   Can you reproduce locally?

## 2) Reproduce

Prefer a deterministic reproduction: - a unit/integration test that
fails - a minimal script that triggers the bug - a recorded
request/fixture (sanitized)

## 3) Observe

Use: - structured logs - metrics dashboards - trace views (if available)

Collect: - error rates - timestamps - correlation/request ids - relevant
environment/config

## 4) Localize

Narrow scope: - which layer is failing? - which boundary is violated? -
is it an input validation issue, state issue, or external dependency
issue?

## 5) Fix

-   Prefer the smallest change that restores invariants.
-   Add/extend tests to prevent regression.
-   Update observability if needed.

## 6) Validate

Run the harness: - `python scripts/harness.py lint` -
`python scripts/harness.py test` - `python scripts/harness.py typecheck`
(if configured)

## 7) Document

-   Add a regression test.
-   Update `CONTRACTS.md` if a contract was clarified.
-   If the fix required a meaningful tradeoff, add an ADR.
