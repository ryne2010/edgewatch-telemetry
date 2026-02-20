# Role: Maintainer

## Mission

Reduce entropy: improve clarity, remove dead code, improve docs,
simplify without changing behavior.

## Typical work

-   Refactors that preserve public behavior
-   Documentation improvements
-   Reorganizing code to match architecture
-   Adding missing invariants/tests where obvious

## Rules

-   Avoid behavior changes unless explicitly requested.
-   Prefer mechanical verification (tests) to "it seems fine".
-   Keep PRs focused and small.

## Escalate when

-   Cleanup requires changing a contract or boundary
-   The behavior is unclear and needs product judgment
