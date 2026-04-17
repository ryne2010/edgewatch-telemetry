# Particle Parity Matrix

Scope: Raspberry Pi/Linux software-platform parity for EdgeWatch versus the feature set the project has been targeting from Particle/Tachyon-style operator workflows.

Out of scope:
- billing
- support/SLA
- customer multi-tenancy
- generic MCU runtime / Device OS parity

Status meanings:
- `meets`: EdgeWatch has the feature at practical parity
- `exceeds`: EdgeWatch goes beyond the target in the Pi/Linux/operator context
- `partial`: architecture and repo support exist, but an important operational gap remains
- `pending`: materially not there yet

## Matrix

| Area | Status | Evidence | Remaining gap |
| --- | --- | --- | --- |
| Typed remote commands / functions | `meets` | device procedures, durable invocation/history/result flow | deeper UX polish only |
| Reported variables / state | `meets` | device state snapshots in API/UI | richer diff/history optional |
| Device event publishing | `meets` | append-only device events + operator surfaces | scale/indexing follow-up |
| Fleet governance | `meets` | first-class fleets, memberships, grants, channels | mostly polish |
| App bundle OTA | `meets` | artifact-aware manifests, staged rollouts, hash/signature checks | more soak testing useful |
| Asset bundle OTA | `meets` | asset bundle apply path + staged rollout controller | more field usage useful |
| System-image OTA orchestration | `partial` | hybrid updater contract, repo-owned wrapper defaults, boot-health/rollback hooks | real Pi boot/rollback validation |
| Rollout channels / promotion | `meets` | manifest lifecycle + channel-targeted deployment + Releases UI | richer approvals/history optional |
| Deployment inspection | `meets` | paged target API/UI, events, pause/resume/abort | cursor-based scaling optional |
| Unified operator search | `meets` | mixed-entity search, entity filters, paging, release/deployment deep links | stronger ranking/full-text |
| Live event stream | `meets` | SSE with source/event filters and replay window | durable cursor/reconnect model |
| Paged event history | `meets` | `/api/v1/operator-events` + Live history UI + CLI | dedicated event index optional |
| Notification / integration fan-out | `meets` | filtered destinations + delivery history for platform events | more destination types optional |
| Cellular operator workflows | `meets` | fleet posture page + cost-cap editing | carrier/billing integrations optional |
| Operator CLI | `meets` | fleets, devices, releases, deployments, events, audit/history, live stream | more convenience wrappers only |

## Honest bottom line

EdgeWatch now meets or exceeds the targeted Particle-style software-platform surface in most repo-controlled areas.

The single biggest blocker to claiming full end-to-end parity/exceedance is:

- production-like Raspberry Pi hardware validation of the `system_image` OTA path, including reboot, boot-health confirmation, and rollback behavior

Until that is completed, the correct status for full parity is:

- `repo/platform parity: near-complete`
- `operational parity on real hardware: not yet proven`

## Acceptance gate for final signoff

Final signoff to claim “meets/exceeds Particle” requires all of:

1. A real Pi cohort successfully runs `system_image` staged deployment using the repo-default or explicitly configured updater path.
2. A deliberately bad `system_image` release proves boot-health timeout and rollback behavior.
3. Operator evidence is captured for:
   - deployment creation
   - stage progression
   - rollback signal
   - post-rollback device health
4. The hardware validation runbook at `docs/RUNBOOKS/SYSTEM_IMAGE_HARDWARE_VALIDATION.md` is completed and checked off.
