# ADR-20260227: RPi Fleet OTA with Signed Manifests and Staged Rollout

## Status

Accepted

## Context

EdgeWatch v1 devices are Raspberry Pi nodes operating in intermittent, power-constrained field environments.
We need remote update capability with:

- auditability
- staged rollout safety
- automatic halt/rollback posture
- no dependency on SSH/manual intervention for standard release flow

## Decision

Implement additive OTA primitives in the existing API + agent architecture:

1. Release manifests:
   - immutable metadata (`git_tag`, `commit_sha`, signature, key id, constraints)
2. Deployments:
   - selector-targeted staged rollout (`1/10/50/100` default)
   - failure-budget halt behavior
3. Device policy delivery:
   - `pending_update_command` in `/api/v1/device-policy`
4. Device reporting:
   - `POST /api/v1/device-updates/{deployment_id}/report` lifecycle states
5. Agent apply guardrails:
   - power guard defer behavior
   - default dry-run execution path (`EDGEWATCH_ENABLE_OTA_APPLY=0`)
   - explicit opt-in for filesystem/symlink apply path

## Consequences

### Positive

- Deployment intent and results are queryable and auditable.
- Offline devices can converge via durable policy refresh.
- Rollout risk is reduced by stage gating and halt thresholds.
- Power-aware defer logic aligns with field hardware constraints.

### Tradeoffs

- Additional operational complexity (manifest/deployment lifecycle).
- Full cryptographic verification and key rotation governance require disciplined operations.
- Apply path correctness still depends on per-device filesystem/runtime consistency.

## Compatibility

- Additive schema + API changes.
- Existing devices continue operating without immediate OTA adoption.
- OTA route usage is gated by `ENABLE_OTA_UPDATES`.
