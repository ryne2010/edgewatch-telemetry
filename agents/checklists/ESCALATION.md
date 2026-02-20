# Escalation Checklist

Escalate to a human when any are true:

-   Intent is ambiguous and affects architecture/contracts.
-   A tradeoff is required that cannot be validated mechanically.
-   A change would modify a public invariant or boundary without an ADR.
-   Security/privacy concerns exist (data handling, secrets, telemetry).
-   Validation cannot be made green without skipping critical checks.

When escalating, include: - intent restatement - options considered -
recommended choice and rationale - validation status and blockers
