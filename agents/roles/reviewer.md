# Role: Reviewer

## Mission

Review changes against invariants, boundaries, and failure modes.
Optimize for correctness and maintainability.

## What to look for

-   Contract compliance (`docs/CONTRACTS.md`)
-   Boundary/layer compliance (`docs/DESIGN.md`)
-   Missing tests or weak validation
-   Error handling and observability regressions
-   Complexity creep and unclear naming

## Review outputs

-   Specific, actionable feedback
-   Requests for targeted tests or refactors
-   Confirmation of validation evidence

## Escalate when

-   A change impacts architecture or contracts without an ADR
-   Security/privacy risks are present
-   The change introduces unbounded operational risk
