# Tutorial: RPi Flash, Assemble, and Launch Checklist

Goal: go from blank hardware to first field telemetry with OTA-ready software posture.

## Phase A: Software readiness

1. Run migrations and keep OTA dark:
   - apply DB migration through `0014_release_deployments_ota`
   - deploy API with `ENABLE_OTA_UPDATES=0`
2. Verify baseline services:
   - ingest, policy, controls, alerts, and dashboard all healthy
3. Enable OTA in stage:
   - `ENABLE_OTA_UPDATES=1`
   - create one manifest + one tiny deployment (pilot-only)
4. Pilot in dry-run:
   - device env `EDGEWATCH_ENABLE_OTA_APPLY=0`
   - verify device update report transitions and power deferrals
5. Pilot real apply:
   - set `EDGEWATCH_ENABLE_OTA_APPLY=1` on a tiny cohort only
   - validate rollback behavior with a deliberate bad release test

## Phase B: SD flash

1. Flash Raspberry Pi OS Lite (64-bit) to microSD.
2. Preload repo/bundle and agent service unit.
3. Preconfigure `agent/.env`:
   - `EDGEWATCH_API_URL`
   - `EDGEWATCH_DEVICE_ID`
   - `EDGEWATCH_DEVICE_TOKEN`
   - `SENSOR_CONFIG_PATH=./agent/config/rpi.microphone.sensors.yaml`
   - `BUFFER_DB_PATH=/var/lib/edgewatch/telemetry_buffer.sqlite`
   - `EDGEWATCH_POLICY_CACHE_PATH=/var/lib/edgewatch/policy_cache_<device>.json`
   - `EDGEWATCH_POWER_STATE_PATH=/var/lib/edgewatch/power_state_<device>.json`
   - `EDGEWATCH_COMMAND_STATE_PATH=/var/lib/edgewatch/command_state_<device>.json`
   - `EDGEWATCH_UPDATE_STATE_PATH=/var/lib/edgewatch/update_state_<device>.json`
   - `EDGEWATCH_LOW_POWER_STATE_PATH=/var/lib/edgewatch/low_power_state_<device>.json`
   - `EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=0`
   - `EDGEWATCH_ENABLE_OTA_APPLY=0` (until rollout approval)
   - choose `RUNTIME_POWER_MODE=continuous|eco|deep_sleep`
   - for Pi 4 true deep sleep only: `DEEP_SLEEP_BACKEND=external_supervisor`

## Phase C: Hardware assembly

1. Mount Pi in weatherproof enclosure with cable glands.
2. Install 12V-to-5V regulated buck converter.
3. Power path options:
   - small 12V SLA battery + solar charge controller
   - well motor 12V battery feed (with fuse and protection)
4. Mount the USB microphone on a short external protected run.
   - keep the main enclosure sealed
   - add strain relief and a drip loop
   - use a hood or downward-facing sheltered mount
5. Connect INA219/INA260 on I2C for power telemetry.
6. Install USB LTE modem + SIM and antenna.
7. Add inline fuse and strain relief on power and modem cabling.
8. Optional low-power hardware:
   - Pi 5: RTC wakealarm path only
   - Pi 4: external RTC/power-latch supervisor if using `deep_sleep`

## Phase D: First boot and validation

1. Boot unit and verify service:
   - `sudo systemctl status edgewatch-agent`
2. Stream logs:
   - `journalctl -u edgewatch-agent -f`
3. Confirm in dashboard:
   - `microphone_level_db`
   - `power_input_v`, `power_input_a`, `power_input_w`
   - `power_input_out_of_range`, `power_unsustainable`
4. Confirm ownership controls:
   - mute/sleep/disable work as expected
   - `runtime_power_mode` and `deep_sleep_backend` controls round-trip in UI/API
5. Confirm OTA dry-run pipeline:
   - create deployment for pilot device
   - verify update report states appear in admin deployment detail

## Phase E: Go-live guardrails

1. Keep remote shutdown guarded by default:
   - only set `EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=1` on explicitly approved nodes
2. Use sleep mode for offseason and long intermissions.
3. Use notification mute for planned quiet periods without deleting alert history.
4. Promote OTA rollout gradually (`1/10/50/100`) and stop on failure budget breaches.
