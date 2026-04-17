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
- **Release manifest:** immutable release metadata (`git_tag`, `commit_sha`, signature, key id, constraints).
- **Deployment:** staged rollout of one release manifest with pause/resume/abort lifecycle.
- **Deployment target:** per-device deployment state row tied to a deployment.

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

## Acceptance criteria patterns

- **Correctness:** no duplicate telemetry rows for the same `message_id`.
- **Reliability:** offline/online transitions produce predictable alert behavior.
- **Security:** secrets/tokens are never logged and never stored in plaintext.
- **Operability:** local stack starts with `make up` and has clear runbooks.
