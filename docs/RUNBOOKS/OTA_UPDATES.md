# OTA Updates Runbook

## Purpose

Operate staged Raspberry Pi OTA deployments safely using immutable signed
manifests, explicit rollout stages, and verified application rollback. Two
control planes are supported:

- the canonical EdgeWatch API deployment lane;
- the external Telegram fleet controller for deployments that cannot host the
  API.

Both lanes require artifact hash and signature verification. Telegram accepts
only a release key or reviewed alias in the local catalog; it never accepts an
operator-supplied URL, digest, signature, key, or command. Newly generated
catalogs contain the exact Git tag as a release key and no alias. An alias may
be added only as a separately reviewed catalog change; generated output must
not replace the exact tag key with a convenience name.

## Feature Flags

- API route enablement:
  - `ENABLE_OTA_UPDATES=1`
- Agent update execution:
  - `EDGEWATCH_ENABLE_OTA_APPLY=0` (default dry-run)
  - set `EDGEWATCH_ENABLE_OTA_APPLY=1` only on validated cohorts
  - this is also the fail-closed activation gate for Telegram app, asset, and
    system-image apply; Telegram staging and status still work while it is `0`
- Telegram-controller local OTA:
  - `application_bundle` is the initial supported apply path
  - `EDGEWATCH_LOCAL_OTA_STATE_PATH` — durable local command/apply ledger
  - `EDGEWATCH_RELEASES_ROOT` — immutable extracted releases
  - `EDGEWATCH_CURRENT_SYMLINK` — atomically selected application release
  - `EDGEWATCH_SYSTEM_IMAGE_APPLY_ENABLED=false` in generated provisioning
  - `EDGEWATCH_ENABLE_SYSTEM_IMAGE_APPLY=0` and
    `EDGEWATCH_SYSTEM_IMAGE_HARDWARE_QUALIFIED=0` remain the guarded defaults
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

## Signing and release catalog

Create a dedicated RSA signing key outside the repository. Keep the private key
mode `0600`; provision only its public key to devices as
`OTA_PUBLIC_KEY_FILE`. Use the same stable `OTA_KEY_ID` in provisioning and
release metadata.

Build a reproducible application bundle, detached signature, and schema-v1
catalog entry with:

```bash
uv run --locked python -m scripts.build_telegram_ota_release \
  --private-key "$PWD/secrets/edgewatch-ota-signing.pem" \
  --key-id edgewatch-release \
  --artifact-uri "https://downloads.example.net/edgewatch-ota_v1.2.3.tar.gz" \
  --version 1.2.3 \
  --tag v1.2.3 \
  --commit "$(git rev-parse HEAD)" \
  --output-dir "$PWD/dist/ota-v1.2.3"
```

The artifact URI must be absolute HTTPS. The bundle contains the repository's
reviewed tracked release files with reproducible metadata. Publish the artifact
at the exact URI, retain the detached signature, review the catalog, then copy
the catalog to the controller host without changing its manifest fields.

The builder resolves the exact `refs/tags/<tag>^{commit}` reference and requires
it, `--commit`, and the source worktree `HEAD` to identify the same commit. This
applies to both lightweight and annotated tags and also protects direct builder
invocations outside the release workflow. A missing or mismatched exact tag
fails before artifact creation.

Production Telegram OTA accepts only an absolute `https://` artifact URI. The
implementation can enable an absolute `file://` artifact only through an
explicit test-only construction path; no production configuration flag enables
local-file artifacts.

The release tool produces two mandatory RSA/SHA-256 signatures:

- `artifact_signature` covers the exact artifact bytes;
- `manifest_signature` covers the canonical ASCII JSON object produced by
  removing only `manifest_signature`, then encoding the remaining manifest with
  sorted keys and compact separators.

The device verifies the canonical manifest signature before compatibility,
download, extraction, or apply, then verifies the artifact signature after the
size and SHA-256 checks. Missing or invalid signatures fail closed.

The signed manifest also requires the top-level
`runtime_dependency_sha256`, calculated over `agent/requirements.txt`. The
device compares it with the installed runtime dependency baseline before it
stages an application bundle. Application OTA is therefore code-only for an
existing base image: the fingerprints must match. A dependency change requires
a new base/system image rather than an application-bundle rollout. The current
system-image OTA path remains unqualified and disabled by default as described
below.

`compatibility` is a closed schema with exactly these nine fields; missing and
unknown fields are rejected:

| Field | Required value/shape |
| --- | --- |
| `schema_version` | Integer `1` |
| `hardware_models` | Unique, non-empty list of safe hardware identifiers |
| `release_channel` | Safe channel identifier |
| `minimum_python_version` | `MAJOR.MINOR.PATCH` |
| `minimum_runtime_schema` | Integer `>= 1` |
| `minimum_ota_schema` | Integer `>= 1` |
| `requires_stable_power` | Boolean |
| `requires_apply_enabled` | Boolean |
| `minimum_free_bytes` | Integer `>= 0` |

The GitHub release workflow builds these artifacts when
`EDGEWATCH_OTA_SIGNING_PRIVATE_KEY` is configured as a secret and
`EDGEWATCH_OTA_SIGNATURE_KEY_ID` is configured as a repository variable. The
workflow must fail rather than publish an unsigned Telegram OTA artifact when
either value is missing.

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

## Telegram controller flow

The Telegram controller is separate from the telemetry bot and is not live
until the [Telegram fleet-control runbook](TELEGRAM_FLEET_CONTROL.md) has been
completed. Its local catalog, SQLite state, controller key, pinned host keys,
and numeric RBAC are part of the operational trust boundary.

1. Configure at least one explicit canary for the fleet and point
   `ota.catalog_file` at the reviewed catalog.
2. Stage and verify the immutable artifact on every frozen target:

   ```text
   /ota <fleet> stage v1.2.3
   /ota <fleet> confirm <confirmation-id>
   ```

3. Obtain the deployment ID from the reply or status, then apply only the
   configured canaries:

   ```text
   /ota <fleet> status
   /ota <fleet> canary <deployment-id>
   /ota <fleet> confirm <confirmation-id>
   ```

4. After health, failure-rate, and defer-rate gates pass, advance exactly one
   configured tranche per confirmed promotion:

   ```text
   /ota <fleet> promote <deployment-id>
   /ota <fleet> confirm <confirmation-id>
   ```

5. To prevent undispatched targets from starting:

   ```text
   /ota <fleet> abort <deployment-id>
   /ota <fleet> confirm <confirmation-id>
   ```

The target set is frozen at preview creation. Confirmation is one-use,
actor/chat/topic-bound, re-authorized before it queues dispatch, and expires
after two minutes by default. All frozen targets must stage successfully before
canary apply. The stage preview and command also freeze the complete signed
manifest and immutable identity displayed to the reviewer, so a later catalog
alias change cannot substitute another release. Abort stops remaining work but
does not claim to reverse an already-applied device.

Confirmation durably queues the OTA command. A separate supervised worker
claims it under a lease and dispatches bounded waves, checking command expiry
and abort state between waves. Controller restart reclaims expired leases and
replays stable command IDs. Terminal state and the deduplicated completion reply
are committed together, while Telegram reply delivery retries independently.

## Device Flow

1. Device reads policy and receives `pending_update_command` when in-scope.
2. Device reports transition states:
   - `downloading`, `downloaded`, `verifying`, `applying`, `staged`, `switching`, `restarting`, `healthy`
   - `rolled_back`, `failed`, `deferred`
3. Device verifies artifact hash before apply and optionally verifies artifact signatures on-device.
4. Power guard or device readiness can defer apply while reporting `deferred`.

For the Telegram lane, the controller sends the already-resolved trusted
manifest through the forced typed helper. The helper maintains an on-device
SQLite replay ledger; a repeated command ID returns its original result. A
device may also have a local catalog, but if present its resolved manifest must
match the controller-supplied manifest exactly.

Transient local OTA failures such as an interrupted download, temporary storage
inspection failure, updater-hook failure, or readiness/rollback-restart failure
return the explicit retryable result without committing that command ID to the
local OTA or applied-command ledger. The controller retries the same stable
command ID under its persisted bounded policy (three attempts per target by
default, per-attempt SSH timeout, and exponential backoff). Validation,
compatibility, trust, digest, and signature failures are terminal.

## Apply Paths

- `application_bundle`
  - agent downloads bundle artifact
  - verifies artifact hash/signature
  - requires the signed `runtime_dependency_sha256` to match the installed
    `agent/requirements.txt` baseline; dependency changes require a new base image
  - safely extracts regular files/directories to an immutable release directory
  - rejects traversal, links, device nodes, FIFOs, and undeclared oversize data
  - fsyncs extracted files and directories, the staging tree, and its parent
    around the atomic staging rename
  - durably journals the original target, intended target, and activation phase
    before switching, and recovers that transaction after an abrupt restart
  - atomically switches the current symlink
  - restarts `edgewatch-agent` and requires a fresh, stable agent-owned readiness
    receipt
  - restores the prior symlink and restarts it when readiness fails
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
  - is not qualified for production use and remains disabled in the Telegram
    lane until real-device reboot, boot-health, and bad-release rollback
    qualification has passed; application-bundle success does not qualify it

## Safety Checks

- Keep the API lane in dry-run first (`EDGEWATCH_ENABLE_OTA_APPLY=0`).
- Generated Telegram provisioning also leaves `EDGEWATCH_ENABLE_OTA_APPLY=0`.
  Signed artifacts may be staged in that state, but canary and promotion apply
  are rejected until the flag is explicitly set to `1` on the validated cohort.
- Apply is disabled by default for every Telegram update type. Do not interpret
  a successful stage as authorization to activate an application, asset, or
  system image.
- For the Telegram lane, prove stage, canary apply, fresh readiness, and
  application rollback on a home-network device before any field promotion.
- Ensure `rollback_to_tag` is valid before broad rollout.
- Halt rollout if failure rates exceed threshold or deferral rates spike.
- Halt rollout if no-quorum or stage timeout symptoms appear.
- Do not enable OTA apply on nodes with unstable power telemetry.
- When `requires_stable_power=true` on a Pi, the device requires a fresh,
  healthy durable power evaluation. If that evaluation has `evidence=none`
  because no power sensor is installed, `vcgencmd get_throttled` must also
  succeed and return exactly `throttled=0x0`. Missing, stale, malformed, or
  unhealthy evidence fails closed.
- Do not enable `system_image` apply until the external updater has passed the
  real-device boot/rollback checklist. Application-bundle validation does not
  qualify system-image OTA.

## Key Rotation

- Keep `signature_key_id` stable per active key.
- Add the matching public key to `EDGEWATCH_OTA_KEYRING_DIR/<signature_key_id>.pem` on devices before broad rollout.
- For new fleet-image devices, pass the new public key through
  `OTA_PUBLIC_KEY_FILE` and `OTA_KEY_ID` during per-device provisioning.
- Publish new manifests with the new key ID only after key distribution is complete.
- Remove retired keys from the keyring after all active deployments signed with them have finished or been aborted.

## Troubleshooting

- No pending update command:
  - verify `ENABLE_OTA_UPDATES=1`
  - confirm deployment status is `active`
  - confirm device target stage is currently enabled
  - confirm command TTL not expired
- Telegram alias is unknown:
  - verify `ota.catalog_file` points to the reviewed schema-v1 catalog
  - verify the alias maps to an immutable release entry
  - do not work around the error by pasting a URL into Telegram
- Telegram dispatch cannot connect:
  - verify the controller is running and its SQLite state is writable
  - verify the device uses `direct` at home or `spacebridge` in the field
  - verify the controller and Spacebridge key files are mode `0600`
  - verify the stable device host-key alias is pinned; never disable checking
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
- Telegram application readiness fails:
  - verify `/opt/edgewatch/current` points back to the previous healthy release
  - inspect `edgewatch-agent` restart and readiness-receipt logs
  - do not promote until the rollback restart is proven healthy
- Device reports `boot_health_timeout`:
  - inspect updater/bootloader logs
  - verify reboot actually occurred
  - confirm `health_timeout_s` is realistic for the image being deployed
  - run rollback manually if automatic rollback is not configured
- Stuck deployment:
  - check `busy_reason` / `updates_enabled` on target devices
  - verify `defer_rate_threshold`, `stage_timeout_s`, and `no_quorum_timeout_s`
  - pause deployment before widening the stage again
