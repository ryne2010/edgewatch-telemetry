# DOMAIN.md

## What are we building?

**EdgeWatch Telemetry** is a lightweight, local-first edge telemetry + alerting platform.

- **Problem:** Field/ops teams often need reliable *heartbeat + metric telemetry* from remote devices (ex: pumps/wells/equipment) under intermittent connectivity, without the overhead of a full IoT fleet product.
- **Users:** Operators and engineers who want a simple dashboard and an audit-friendly event trail; developers who want a reference implementation of patterns (idempotency, buffering, offline detection, Cloud Run demo posture).
- **Non-goals:**
  - Full IoT fleet manager (multi-tenant billing, device identity PKI, generic app marketplace, etc.)
  - High-throughput time-series warehouse
  - Multi-tenant SaaS (this repo is a reference implementation)

## Domain invariants

These are the rules that must always hold (and should be enforced mechanically).

1) **Idempotent ingestion**
- Re-sending the same telemetry payload must not create duplicates.
- Dedupe is by `message_id` (globally unique per point).

2) **Device identity is stable**
- `device_id` is a stable identifier.
- `device_id` is the join key for telemetry and alerts.

3) **Authentication tokens are never stored in plaintext**
- Server stores **only** a strong hash (PBKDF2) and a fingerprint (SHA-256) for lookup.

4) **Timestamps are treated as UTC**
- Persisted timestamps are timezone-aware.
- If a device sends a naive timestamp, it is assumed to be UTC and normalized.

5) **Alerts are stateful**
- Alerts may have an open/resolved lifecycle.
- Offline alerts should open once and resolve when the device returns.

6) **Per-device ownership is explicit**
- Non-admin users can only read/control devices they are explicitly granted.
- Admins bypass per-device grant checks for operations and recovery.

7) **Telegram control has a separate trust boundary**
- A dedicated control bot is held by one operator-controlled fleet controller;
  its token is never installed on devices.
- Numeric Telegram chat/user IDs and optional topic IDs, not usernames, define
  authorization.
- The ordinary operator SSH key and forced-command controller SSH key are
  distinct.

8) **OTA artifacts are immutable and signed**
- Telegram may select only a release alias from the controller's local catalog.
- Devices verify size, SHA-256, RSA/SHA-256 signature, key ID, compatibility,
  and version identity before apply.
- System-image application is not qualified until real-device reboot and
  bad-release rollback validation is complete.

9) **Camera sub-fleet media stays local**
- Satellites send only compact events, health, and metrics over LoRaWAN.
- Media, SSH, and OTA artifacts never cross the LoRaWAN application protocol.
- Event clips and daily stills remain in the bounded local evidence ring unless
  an operator explicitly retrieves them over the switched maintenance WLAN.

10) **Hardware power transitions fail closed**
- Gateway LTE electrical switching, SX1302/SX1303 ingress, and satellite MCU
  rail cutoff are explicit qualified adapters, not inferred from software state.
- A satellite result file or successful service exit is not permission for the
  MCU to remove power; the MCU waits for a board-qualified final-halt signal.

## Core workflows

1) **Register a device (admin)**
- Operator/engineer creates a device record with:
  - `device_id`, `display_name`
  - token hash + fingerprint
  - heartbeat/offline parameters

2) **Ingest telemetry (device → API)**
- Device agent buffers locally if offline.
- On reconnect, agent flushes buffered points.
- API accepts points, dedupes by `message_id`, updates `last_seen_at`.

3) **Compute online/offline status**
- Status is computed from `last_seen_at` vs `offline_after_s`.

4) **Generate alerts**
- Periodic job checks device last-seen and opens/resolves offline alerts.
- Metric threshold alerts (microphone level, water pressure, battery, signal) open/resolve based on values.
  - Microphone offline uses consecutive-sample sustain defaults (`2` low to open, `1` recover to resolve).
- Power lifecycle alerts open/resolve from telemetry flags:
  - `POWER_INPUT_OUT_OF_RANGE` / `POWER_INPUT_OK`
  - `POWER_UNSUSTAINABLE` / `POWER_SUSTAINABLE`

5) **Dashboard queries**
- UI queries:
  - devices list + status
  - telemetry (raw + bucketed)
  - alerts timeline

6) **Owner/operator controls**
- Owners/operators can mute alert notifications for planned windows (offseason/maintenance).
- Owners/operators can switch device operation mode:
  - `active`: normal cadence
  - `sleep`: long-cadence polling (default 7 days)
  - `disabled`: logical disable; local restart required to resume
- Owners/operators can independently select runtime power behavior:
  - `continuous`: always-on Linux loop
  - `eco`: software-only network duty cycling
  - `deep_sleep`: true between-sample halt/power-off when supported
- Admins can additionally issue a one-shot remote shutdown intent:
  - command payload still latches `disabled`
  - actual OS shutdown only runs on devices that explicitly allow it via local env guard
- Control changes are enqueued as durable per-device commands (default TTL 180 days) and applied by agents
  on next policy fetch; devices ack application.

6b) **Typed remote procedures**
- Operators can invoke pre-declared typed procedures against devices.
- Procedure delivery is durable and device-auth result reporting is explicit.
- Procedures are distinct from telemetry and from owner/control mode changes.

6c) **Device state and events**
- Devices can report latest state/variables as snapshots.
- Devices can publish append-only operational events for operator visibility and integrations.

6d) **Fleet governance**
- Devices can belong to fleets that act as governance and release scope boundaries.
- Fleet access grants expand operator visibility/control across the devices in a fleet.
- Fleets are not customer/tenant abstractions; they are operational groupings.

7) **Fleet OTA deployments**
- Admins publish release manifests (tag + commit + signature metadata).
- Admins start staged deployments (`1% -> 10% -> 50% -> 100%`) for target selectors (`all|cohort|labels|explicit_ids`).
- Device policy carries a pending update command for in-scope devices and stages.
- Devices report update transitions (`downloading` to `healthy|rolled_back|failed`) and converge after reconnect.
- Deployments auto-halt when stage failure-rate exceeds configured thresholds.

8) **Telegram fleet control without the EdgeWatch API**
- One supervised controller consumes the dedicated control bot's updates.
- Viewer/operator/admin authorization is based on immutable numeric Telegram
  IDs, fleet membership, and optional topic scope.
- The controller persists commands, frozen fleet targets, confirmations,
  replies, audit state, and OTA deployment state before dispatch.
- Direct pinned SSH is used during home bring-up; Hologram Spacebridge carries
  the same typed protocol in the field.
- Devices accept only allowlisted typed operations through the forced helper and
  return the original result when a command ID is replayed.
- Signed application-bundle OTA follows explicit stage, canary, one-tranche
  promote, and abort steps without depending on the EdgeWatch API.

9) **Low-power camera sub-fleet**
- One always-on gateway maps the closed DevEUI inventory to stable device IDs,
  validates compact LoRaWAN v1 frames, and reconstructs canonical telemetry.
- Event/fault uplinks open an immediate bounded LTE window; routine control,
  heartbeat, and queued telemetry use the hourly window.
- An authenticated, expiring LoRaWAN downlink may request only a maintenance
  wake. Bulk work waits for the satellite's pinned-key maintenance WLAN.
- Satellites capture and infer locally, commit a bounded machine-readable result,
  then request a clean Linux shutdown before their MCU removes electrical power.
- Signed model bundles use the same staged fleet rollout shape as application
  OTA, with independent known-answer/readiness validation and rollback.

## Vocabulary

- **Agent:** software running on the edge device (ex: Raspberry Pi) that buffers and sends telemetry.
- **Device:** a registered entity that can authenticate and send telemetry.
- **Telemetry point:** a time-stamped measurement payload (`ts`, `metrics`, `message_id`).
- **Heartbeat:** a periodic signal indicating the device is alive.
- **Offline:** `now - last_seen_at > offline_after_s`.
- **Sleep:** device intentionally uses long-cadence polling; offline lifecycle is suppressed.
- **Disabled:** device is logically disabled and requires on-device restart to resume telemetry.
- **Runtime power mode:** device-side power behavior layered on top of operation mode (`continuous|eco|deep_sleep`).
- **Deep-sleep backend:** applied hardware path for true between-sample low power (`none|pi5_rtc|external_supervisor`).
- **Hybrid disable:** owner/operator disable is logical-only; admin shutdown intent can request one-shot OS shutdown,
  but device-side execution remains opt-in.
- **Alert:** an operational event derived from telemetry or offline checks.
- **Control command:** a durable, per-device control snapshot delivered via policy and acknowledged by device.
- **Telegram fleet controller:** the single operator-controlled consumer of a
  dedicated control bot that authorizes, persists, and dispatches typed device
  work without the EdgeWatch API.
- **Frozen target set:** the exact eligible device IDs captured in a fleet
  mutation preview; later inventory changes do not change that command.
- **Typed device helper:** the forced SSH command that validates a bounded JSON
  envelope and maps it to an allowlisted local operation; it is not a shell.
- **Controller command:** an expiring, stably identified Telegram-requested
  operation with per-target result and audit state.
- **Release manifest:** immutable release metadata (`git_tag`, `commit_sha`, signature, key id, constraints).
- **Deployment:** staged rollout of one release manifest with pause/resume/abort lifecycle.
- **Deployment target:** per-device deployment state row tied to a deployment.
- **Camera satellite:** an MCU-supervised Pi Zero 2 W plus local camera/audio
  inference, LoRaWAN Class A radio, and switched maintenance WLAN.
- **Field gateway:** the always-on Pi 4/5 that hosts Telegram control, the local
  LoRaWAN services, durable uplink/outbox state, and electrically duty-cycled LTE.
- **Radio ingress adapter:** separately reviewed and SHA-256-pinned executable
  that proves SX1302/SX1303 detection and the local ChirpStack bridge; the repo
  does not ship a vendor concentrator binary.
- **Model bundle:** signed immutable vision/audio models, labels, preprocessing,
  thresholds, compatibility, and known-answer vectors activated independently
  from application code.

## Canonical metric keys (contracted)

EdgeWatch intentionally allows additive evolution (unknown keys are accepted), but the
demo environment uses an explicit "known keys" contract for discoverability.

See `contracts/telemetry/v1.yaml` for the full list.

Common operational metrics:
- `microphone_level_db`
- `power_input_v`
- `power_input_a`
- `power_input_w`
- `power_source`
- `power_input_out_of_range`
- `power_unsustainable`
- `power_saver_active`
- `power_runtime_mode`
- `power_sleep_backend`
- `wake_reason`
- `network_duty_cycled`
- `water_pressure_psi`
- `oil_pressure_psi`
- `temperature_c`
- `humidity_pct`
- `oil_level_pct`
- `oil_life_pct`
- `oil_life_reset_at`
- `drip_oil_level_pct`
- `battery_v`
- `signal_rssi_dbm`
- `cellular_rsrp_dbm`
- `cellular_rsrq_db`
- `cellular_sinr_db`
- `cellular_registration_state`
- `cellular_bytes_sent_today`
- `cellular_bytes_received_today`
- `link_ok`
- `link_last_ok_at`
- `cost_cap_active`
- `bytes_sent_today`
- `media_uploads_today`
- `snapshots_today`
- `lorawan_message_type`
- `lorawan_sequence`
- `lorawan_dev_eui`
- `equipment_state`
- `visual_confidence`
- `audio_anomaly_score`
- `low_battery`
- `sentinel_triggered`
- `camera_ok`
- `audio_ok`
- `maintenance_ready`
- `degraded`
- `model_version_digest`
- `maintenance_command_token`

## Data model overview

- `devices`
  - source of truth for device config + auth
  - `last_seen_at` tracks newest observed telemetry timestamp
- `telemetry_points`
  - append-only time series points
  - idempotency enforced by server-side dedupe key `(device_id, message_id)`
- `alerts`
  - operational events
  - may be open (`resolved_at is null`) or resolved

## Edge cases and failure modes

- **Intermittent connectivity:** agent buffers, flushes later.
- **Duplicate sends:** must be safe (idempotent insert).
- **Out-of-order telemetry:** `last_seen_at` should not move backwards.
- **Clock skew:** naive timestamps assumed UTC; future improvements may include server-side receipt time.
- **DB unavailability:** API should fail clearly; future improvements may include a queue.
- **Controller unavailability:** device telemetry continues through the
  telemetry bot, but Telegram control and OTA wait for the single controller to
  return.
- **Spacebridge unavailability:** field control delivery fails closed and may
  retry transient transport errors; it never falls back to an unpinned host.
- **Control reply loss:** accepted device work remains recorded even if the
  Telegram reply must be retried separately.

## Acceptance criteria patterns

- **Correctness:** no duplicate telemetry rows for the same `message_id`.
- **Reliability:** offline/online transitions produce predictable alert behavior.
- **Security:** secrets/tokens are never logged and never stored in plaintext.
- **Operability:** the local stack starts with canonical `make run` (`make up` remains a compatibility alias) and has clear runbooks.
