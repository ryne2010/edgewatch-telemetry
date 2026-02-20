# Incident Runbook

> TODO: Customize for your org's incident process (on-call, paging,
> comms channels).

## Phases

1.  Detect & declare
2.  Triage and assess impact
3.  Mitigate
4.  Root cause analysis
5.  Follow-ups and prevention

## Severity (example)

-   SEV0: Complete outage / major security incident
-   SEV1: Significant degradation for many users
-   SEV2: Partial degradation / limited scope
-   SEV3: Minor impact

## Mitigation principles

-   Stop the bleed first (rollback, disable feature flag, reduce load).
-   Prefer reversible changes.
-   Keep a timeline of actions.

## Communications

-   Identify incident commander.
-   Post regular updates at a fixed cadence.
-   Maintain a single source of truth (incident doc/ticket).

## Post-incident

-   Write a root cause analysis:
    -   what happened
    -   why it happened
    -   what prevented earlier detection
    -   what changes prevent recurrence
-   Convert follow-ups into tracked issues.
