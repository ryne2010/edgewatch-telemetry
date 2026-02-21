# DOMAIN.md

## What are we building?

**EdgeWatch Telemetry** is a lightweight, local-first edge telemetry + alerting platform.

- **Problem:** Field/ops teams often need reliable *heartbeat + metric telemetry* from remote devices (ex: pumps/wells/equipment) under intermittent connectivity, without the overhead of a full IoT fleet product.
- **Users:** Operators and engineers who want a simple dashboard and an audit-friendly event trail; developers who want a reference implementation of patterns (idempotency, buffering, offline detection, Cloud Run demo posture).
- **Non-goals:**
  - Full IoT fleet manager (device provisioning at scale, OTA updates, device identity PKI, etc.)
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
- Metric threshold alerts (water pressure, battery, signal) open/resolve based on values.

5) **Dashboard queries**
- UI queries:
  - devices list + status
  - telemetry (raw + bucketed)
  - alerts timeline

## Vocabulary

- **Agent:** software running on the edge device (ex: Raspberry Pi) that buffers and sends telemetry.
- **Device:** a registered entity that can authenticate and send telemetry.
- **Telemetry point:** a time-stamped measurement payload (`ts`, `metrics`, `message_id`).
- **Heartbeat:** a periodic signal indicating the device is alive.
- **Offline:** `now - last_seen_at > offline_after_s`.
- **Alert:** an operational event derived from telemetry or offline checks.

## Canonical metric keys (contracted)

EdgeWatch intentionally allows additive evolution (unknown keys are accepted), but the
demo environment uses an explicit "known keys" contract for discoverability.

See `contracts/telemetry/v1.yaml` for the full list.

Common operational metrics:
- `water_pressure_psi`
- `oil_pressure_psi`
- `temperature_c`
- `humidity_pct`
- `oil_level_pct`
- `oil_life_pct`
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
  - unique by `message_id` to enforce idempotency
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
