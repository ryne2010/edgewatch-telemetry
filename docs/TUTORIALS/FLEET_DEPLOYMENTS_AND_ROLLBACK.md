# Fleet Deployments and Rollback Tutorial

## Goal

Deploy a new release tag to Raspberry Pi devices with staged rollout and rollback safety.

## Prerequisites

- API started with `ENABLE_OTA_UPDATES=1`
- Devices already registered and reporting telemetry
- At least one known-good rollback tag

## Step 1: Publish manifest

Call:

```http
POST /api/v1/admin/releases/manifests
```

Payload:

```json
{
  "git_tag": "v1.4.0",
  "commit_sha": "abc123...",
  "signature": "base64-signature",
  "signature_key_id": "ops-key-2026-02",
  "constraints": {
    "hardware_rev": "rpi4b"
  },
  "status": "active"
}
```

## Step 2: Start staged deployment

Call:

```http
POST /api/v1/admin/deployments
```

Payload example (cohort targeted):

```json
{
  "manifest_id": "<manifest-id>",
  "target_selector": {
    "mode": "cohort",
    "cohort": "pilot-west"
  },
  "rollout_stages_pct": [1, 10, 50, 100],
  "failure_rate_threshold": 0.2,
  "health_timeout_s": 300,
  "command_ttl_s": 15552000,
  "power_guard_required": true,
  "rollback_to_tag": "v1.3.4"
}
```

## Step 3: Observe progression

Use:

```http
GET /api/v1/admin/deployments/{deployment_id}
```

Track:

- `stage`
- `status`
- per-target states (`queued`, `applying`, `healthy`, `failed`, `rolled_back`, `deferred`)
- deployment events for halt/advance reasons

## Step 4: Handle failures

- If failure budget breaches threshold, deployment auto-halts.
- You can manually:
  - pause (`/pause`)
  - resume (`/resume`)
  - abort (`/abort`)
- Devices can emit `rolled_back` when rollback tag apply succeeds.

## Step 5: Move from dry-run to real apply

- Start with `EDGEWATCH_ENABLE_OTA_APPLY=0` on pilot devices.
- Validate report lifecycle and power guard behavior.
- Enable apply (`EDGEWATCH_ENABLE_OTA_APPLY=1`) only for validated cohorts.

## Notes

- Offline devices receive pending commands when they reconnect and refresh policy.
- Power guard is enforced per device and prevents risky updates during unstable supply conditions.
