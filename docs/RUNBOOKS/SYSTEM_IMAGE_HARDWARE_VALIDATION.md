# System-Image Hardware Validation

Purpose: prove that EdgeWatch `system_image` OTA is operationally trustworthy on real Raspberry Pi hardware.

This runbook is the final gate for claiming end-to-end Particle-style OTA parity/exceedance.

## Preconditions

- API started with `ENABLE_OTA_UPDATES=1`
- Devices enrolled and visible in EdgeWatch
- Repo-default or explicit updater wiring in place:
  - `EDGEWATCH_SYSTEM_IMAGE_APPLY_CMD`
  - `EDGEWATCH_SYSTEM_IMAGE_ROLLBACK_CMD`
- Device-side apply enabled on the cohort:
  - `EDGEWATCH_ENABLE_OTA_APPLY=1`
- A known-good rollback image/tag exists
- Power is stable and intentionally monitored during the test

## Test cohort

- 1 sacrificial Pi for the first bad-release rollback drill
- 1 to 3 additional Pi devices for a tiny staged validation cohort
- Record:
  - Pi model / storage medium
  - power path
  - active updater command
  - image provenance

## Validation sequence

### 1. Baseline health

- Confirm devices are healthy in EdgeWatch before the rollout.
- Confirm `runtime_power_mode`, `ota_channel`, and `updates_enabled` are as expected.
- Confirm the repo-default wrapper staging path is writable if you use the wrapper fallback.

### 2. Good release drill

- Publish a `system_image` release manifest.
- Start a staged deployment against the tiny cohort.
- Verify:
  - device reports `downloading -> downloaded -> verifying -> applying -> staged -> switching -> restarting`
  - after reboot/process return, device reports `healthy`
  - deployment advances/finishes without false halt

Evidence to capture:
- deployment id
- device ids
- timestamps for each transition
- updater logs

### 3. Bad release rollback drill

- Publish a deliberately bad `system_image` manifest that should fail boot-health or intentionally fail the updater’s health path.
- Start deployment against the sacrificial Pi only.
- Verify:
  - rollout reaches `restarting`
  - device fails boot-health within `health_timeout_s`
  - rollback command/path executes
  - device reports `rolled_back`
  - device returns to healthy post-rollback state

Evidence to capture:
- failing manifest id
- rollback reason
- rollback logs
- final healthy state after rollback

### 4. Multi-device tiny cohort

- Run the same good release across 2 to 4 Pi devices.
- Verify:
  - deployment stage math is sensible
  - event surfaces show deployment and release-manifest lifecycle clearly
  - no device is falsely left in a stuck staged state

### 5. Power guard sanity

- Confirm updates defer correctly when power guard conditions are simulated or naturally present.
- Verify no unsafe apply occurs while power is out of range / unsustainable.

## Pass criteria

Validation passes only if all are true:

- good release completes successfully on real hardware
- bad release triggers rollback behavior successfully
- post-rollback device health is confirmed
- operator event/history surfaces contain enough evidence to reconstruct the rollout
- no unexplained stuck targets remain

## Fail criteria

Any of these block final parity signoff:

- updater stages but cannot reboot/apply reliably
- boot-health timeout does not produce rollback behavior
- rollback behavior is inconsistent across Pi hardware/storage variants
- deployment state becomes stuck or misleading
- required evidence cannot be captured from logs/UI/API

## Close-out artifact

When finished, record:

- tested Pi models
- updater command used
- manifests tested
- pass/fail per scenario
- rollback evidence
- known residual risks

Store that report wherever your team keeps rollout validation records before claiming full Particle-style parity.

Optional helper:

```bash
python scripts/ota/collect_system_image_validation_evidence.py \
  --device-id <device-id> \
  --output ./system-image-validation-<device-id>.json
```

This helper collects the current agent update-state file plus staged system-image metadata (`latest.json` and per-manifest metadata when present) into one JSON artifact for validation evidence.

Optional evaluator:

```bash
python scripts/ota/evaluate_system_image_validation.py \
  --scenario good_release \
  --evidence-json ./system-image-validation-<device-id>.json
```

Use `--scenario rollback_drill` for the rollback exercise. This evaluator checks that the collected evidence is complete enough for manual signoff review; it does not replace the real-device validation itself.

Combined helper:

```bash
python scripts/operator_cli.py ota-validation run \
  --device-id <device-id> \
  --scenario good_release \
  --output ./system-image-validation-<device-id>.json
```
