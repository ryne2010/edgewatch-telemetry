# OTA Updates Runbook

## Purpose

Operate staged Raspberry Pi OTA deployments safely using artifact-aware manifests, deployment stages, and hybrid updater rollback signals.

## Feature Flags

- API route enablement:
  - `ENABLE_OTA_UPDATES=1`
- Agent update execution:
  - `EDGEWATCH_ENABLE_OTA_APPLY=0` (default dry-run)
  - set `EDGEWATCH_ENABLE_OTA_APPLY=1` only on validated cohorts
- Agent artifact verification:
  - `EDGEWATCH_OTA_CACHE_DIR` — persistent artifact cache
  - `EDGEWATCH_OTA_KEYRING_DIR` — public keys used for artifact signature verification
- Hybrid updater integration:
  - `EDGEWATCH_SYSTEM_IMAGE_APPLY_CMD` — external updater command for system/image installs
    - repo default wrapper: `python scripts/ota/system_image_updater.py`
    - if unset and the repo scripts are present, the agent falls back to this wrapper automatically
  - `EDGEWATCH_SYSTEM_IMAGE_ROLLBACK_CMD` — optional rollback command when boot health fails
    - repo default wrapper: `python scripts/ota/system_image_rollback.py`
    - if unset and the repo scripts are present, boot-health timeout rollback falls back to this wrapper automatically
  - `EDGEWATCH_ASSET_BUNDLE_APPLY_CMD` — optional hook for non-app asset bundles

## Admin Flow

1. Create a release manifest:
   - `POST /api/v1/admin/releases/manifests`
   - Required:
     - `git_tag`, `commit_sha`
     - `update_type`
     - `artifact_uri`, `artifact_size`, `artifact_sha256`
     - `signature`, `signature_key_id`
   - Optional:
     - `artifact_signature`, `artifact_signature_scheme`
     - `compatibility`
   - Promotion / retirement:
     - `PATCH /api/v1/admin/releases/manifests/{manifest_id}`
     - Update `status` to move between `draft`, `active`, and `retired`
2. Create deployment:
   - `POST /api/v1/admin/deployments`
   - Use selector + rollout stages (`1/10/50/100`)
   - `channel` is supported as a selector mode in addition to `all|cohort|labels|explicit_ids`
   - Set `rollback_to_tag` when available
3. Monitor:
   - `GET /api/v1/admin/deployments`
   - Filter by `status`, `manifest_id`, or `selector_channel` to find recent rollout attempts
   - `GET /api/v1/admin/deployments/{deployment_id}`
   - Review target counts, stage, and event history
4. Intervene if needed:
   - Pause: `POST /api/v1/admin/deployments/{deployment_id}/pause`
   - Resume: `POST /api/v1/admin/deployments/{deployment_id}/resume`
   - Abort: `POST /api/v1/admin/deployments/{deployment_id}/abort`

## Device Flow

1. Device reads policy and receives `pending_update_command` when in-scope.
2. Device reports transition states:
   - `downloading`, `downloaded`, `verifying`, `applying`, `staged`, `switching`, `restarting`, `healthy`
   - `rolled_back`, `failed`, `deferred`
3. Device verifies artifact hash before apply and optionally verifies artifact signatures on-device.
4. Power guard or device readiness can defer apply while reporting `deferred`.

## Apply Paths

- `application_bundle`
  - agent downloads bundle artifact
  - verifies artifact hash/signature
  - extracts to release directory
  - switches current symlink
- `asset_bundle`
  - agent downloads bundle artifact
  - verifies artifact hash/signature
  - extracts to managed asset path or invokes `EDGEWATCH_ASSET_BUNDLE_APPLY_CMD`
- `system_image`
  - agent downloads image artifact
  - verifies artifact hash/signature
  - invokes `EDGEWATCH_SYSTEM_IMAGE_APPLY_CMD`
  - repo wrapper stages the validated artifact under `EDGEWATCH_SYSTEM_IMAGE_STAGE_DIR` and records `latest.json`
  - records pending boot-health confirmation in update state
  - on next process start, reports `healthy` if boot returned within timeout
  - may invoke `EDGEWATCH_SYSTEM_IMAGE_ROLLBACK_CMD` on boot-health timeout

## Safety Checks

- Keep production in dry-run first (`EDGEWATCH_ENABLE_OTA_APPLY=0`).
- Ensure `rollback_to_tag` is valid before broad rollout.
- Halt rollout if failure rates exceed threshold or deferral rates spike.
- Halt rollout if no-quorum or stage timeout symptoms appear.
- Do not enable OTA apply on nodes with unstable power telemetry.
- Do not enable `system_image` apply until the external updater has passed real-device boot/rollback testing.

## Key Rotation

- Keep `signature_key_id` stable per active key.
- Add the matching public key to `EDGEWATCH_OTA_KEYRING_DIR/<signature_key_id>.pem` on devices before broad rollout.
- Publish new manifests with the new key ID only after key distribution is complete.
- Remove retired keys from the keyring after all active deployments signed with them have finished or been aborted.

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
  - check `artifact_sha256`
  - check artifact signature and public key under `EDGEWATCH_OTA_KEYRING_DIR`
- Device reports `apply_failed`:
  - for `application_bundle`: verify release filesystem permissions and symlink paths
  - confirm `EDGEWATCH_RELEASES_ROOT` and `EDGEWATCH_CURRENT_SYMLINK`
  - for `asset_bundle`: verify `EDGEWATCH_ASSET_BUNDLE_APPLY_CMD` or asset extraction path
  - for `system_image`: inspect external updater logs and command wiring
- Device reports `boot_health_timeout`:
  - inspect updater/bootloader logs
  - verify reboot actually occurred
  - confirm `health_timeout_s` is realistic for the image being deployed
  - run rollback manually if automatic rollback is not configured
- Stuck deployment:
  - check `busy_reason` / `updates_enabled` on target devices
  - verify `defer_rate_threshold`, `stage_timeout_s`, and `no_quorum_timeout_s`
  - pause deployment before widening the stage again
