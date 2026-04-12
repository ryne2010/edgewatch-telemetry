# OTA Updates Runbook

## Purpose

Operate staged Raspberry Pi OTA deployments safely using signed manifests, deployment stages, and automatic halt/rollback signals.

## Feature Flags

- API route enablement:
  - `ENABLE_OTA_UPDATES=1`
- Agent update execution:
  - `EDGEWATCH_ENABLE_OTA_APPLY=0` (default dry-run)
  - set `EDGEWATCH_ENABLE_OTA_APPLY=1` only on validated cohorts

## Admin Flow

1. Create a release manifest:
   - `POST /api/v1/admin/releases/manifests`
   - Required: `git_tag`, `commit_sha`, `signature`, `signature_key_id`
2. Create deployment:
   - `POST /api/v1/admin/deployments`
   - Use selector + rollout stages (`1/10/50/100`)
   - Set `rollback_to_tag` when available
3. Monitor:
   - `GET /api/v1/admin/deployments/{deployment_id}`
   - Review target counts, stage, and event history
4. Intervene if needed:
   - Pause: `POST /api/v1/admin/deployments/{deployment_id}/pause`
   - Resume: `POST /api/v1/admin/deployments/{deployment_id}/resume`
   - Abort: `POST /api/v1/admin/deployments/{deployment_id}/abort`

## Device Flow

1. Device reads policy and receives `pending_update_command` when in-scope.
2. Device reports transition states:
   - `downloading`, `verifying`, `applying`, `restarting`, `healthy`
   - `rolled_back`, `failed`, `deferred`
3. Power guard can defer apply while reporting `deferred`.

## Safety Checks

- Keep production in dry-run first (`EDGEWATCH_ENABLE_OTA_APPLY=0`).
- Ensure `rollback_to_tag` is valid before broad rollout.
- Halt rollout if failure rates exceed threshold or deferral rates spike.
- Do not enable OTA apply on nodes with unstable power telemetry.

## Troubleshooting

- No pending update command:
  - verify `ENABLE_OTA_UPDATES=1`
  - confirm deployment status is `active`
  - confirm device target stage is currently enabled
  - confirm command TTL not expired
- Device reports only `deferred`:
  - inspect `power_input_out_of_range` / `power_unsustainable`
  - tune power thresholds or pause deployment
- Device reports `verify_failed`:
  - check manifest `git_tag` maps to `commit_sha`
  - check repository has fetched tags
- Device reports `apply_failed`:
  - verify release filesystem permissions and symlink paths
  - confirm `EDGEWATCH_RELEASES_ROOT` and `EDGEWATCH_CURRENT_SYMLINK`
