# ADR-20260227: Strict Per-Device Ownership + Operation Controls

## Status

Accepted

## Context

EdgeWatch needed a least-privilege ownership model for read/control surfaces:

- non-admin users must only access explicitly granted devices
- owners/operators need seasonal controls:
  - mute notifications (without stopping alert lifecycle)
  - sleep mode (long-cadence polling)
  - disable mode (logical disable with local restart requirement)

The existing role model (`viewer|operator|admin`) was global and insufficient for
per-device ownership.

## Decision

1. Add per-device grant storage (`device_access_grants`) with roles:
- `viewer`
- `operator`
- `owner`

2. Enforce per-device grants for non-admin users when `AUTHZ_ENABLED=1`:
- read routes (`/devices`, `/alerts`, telemetry routes) are scoped by grants
- control routes require `operator` or `owner` grant
- admin bypass remains in place

3. Add device control state on `devices`:
- `operation_mode` (`active|sleep|disabled`)
- `sleep_poll_interval_s` (default `604800`)
- `alerts_muted_until`
- `alerts_muted_reason`

4. Keep mute semantics as notifications-only suppression:
- alert rows still open/resolve for observability and audit continuity

5. Represent sleep/disabled explicitly in computed status:
- status enum includes `sleep` and `disabled`
- offline lifecycle is suppressed while device is in sleep/disabled

## Consequences

- Access is now explicit and auditable at the device level.
- Operators can safely reduce noise and power/network usage during offseason windows.
- Disabled mode is intentionally conservative: recovery requires local restart.
- Legacy behavior remains available with `AUTHZ_ENABLED=0`.
