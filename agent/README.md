# EdgeWatch Agent (Raspberry Pi / edge device)

This folder contains a Python "edge agent" that:

- reads sensors (mocked by default)
- **optimizes battery & data usage** by only sending when needed
  - immediate send on alert transitions
  - periodic heartbeat for keepalive
  - delta-threshold send for meaningful changes
- buffers locally to SQLite when offline
- flushes buffered points when connectivity returns

The agent is designed to be realistic for constrained field devices:
- low chatter when healthy
- burst send when something changes
- ETag-cached policy/config so devices don't re-download settings
- dead-letter handling so a single bad point doesn't block offline flush

## Setup

```bash
# From the repo root:
uv sync
cp agent/.env.example agent/.env
uv run python agent/edgewatch_agent.py
```

## Raspberry Pi deployment

For a production-ish Raspberry Pi setup (venv + systemd + logs), see:

- `docs/DEPLOY_RPI.md`

## Device policy (energy & data optimization)

Devices fetch their policy from:

- `GET /api/v1/device-policy` (authenticated)

The API serves the policy with `ETag` and `Cache-Control: max-age=...`.
The agent caches the last successful policy to a small local JSON file
(`./edgewatch_policy_cache.json` by default).

The policy lives in:

- `contracts/edge_policy/v1.yaml`

Tune it to trade off alert latency vs battery/data usage.

## Real sensors

The agent now uses a pluggable backend interface under `agent/sensors/`.

Default behavior remains `mock` (no hardware required).

Backend selection:

- `SENSOR_CONFIG_PATH` points to a YAML config file
- `SENSOR_BACKEND` optionally overrides the selected backend at runtime

Example config:

- `agent/config/example.sensors.yaml`

Supported backend names in this stage:

- `mock`
- `composite`
- `rpi_i2c` (BME280 temperature + humidity via I2C; requires `smbus2` on Pi)
- `rpi_adc` (ADS1115 pressures/levels via I2C; requires `smbus2` on Pi)
- `derived` (runtime oil-life model with durable local state + manual reset)

For Raspberry Pi I2C:

```bash
pip install smbus2
SENSOR_BACKEND=rpi_i2c uv run python agent/edgewatch_agent.py
```

For Raspberry Pi ADC (ADS1115):

```bash
pip install smbus2
SENSOR_BACKEND=rpi_adc uv run python agent/edgewatch_agent.py
```

Oil life reset tool (device-local):

```bash
python -m agent.tools.oil_life reset --state ./agent/state/oil_life_state.json
python -m agent.tools.oil_life show --state ./agent/state/oil_life_state.json
```

## Cellular metrics + link watchdog

Enable optional cellular observability on Raspberry Pi nodes with ModemManager:

```bash
CELLULAR_METRICS_ENABLED=true \
CELLULAR_WATCHDOG_ENABLED=true \
CELLULAR_INTERFACE=wwan0 \
uv run python agent/edgewatch_agent.py
```

When enabled, the agent adds best-effort metrics such as:
- `signal_rssi_dbm`
- `cellular_rsrp_dbm`, `cellular_rsrq_db`, `cellular_sinr_db` (if modem reports them)
- `cellular_registration_state`
- `cellular_bytes_sent_today`, `cellular_bytes_received_today`
- `link_ok`, `link_last_ok_at`

Notes:
- On non-Pi hosts (or when `mmcli` is absent), the agent remains runnable.
- Watchdog checks are observation-only (DNS + HTTP HEAD); they do not restart networking.

## Cost-cap enforcement (Task 13c)

Devices enforce daily UTC caps from `GET /api/v1/device-policy` (`cost_caps`):
- `max_bytes_per_day`
- `max_snapshots_per_day`
- `max_media_uploads_per_day`

Behavior:
- telemetry switches to heartbeat-only once byte cap is reached
- scheduled media captures are skipped once snapshot/upload caps are reached
- audit metrics are emitted in telemetry:
  - `cost_cap_active`
  - `bytes_sent_today`
  - `media_uploads_today`
  - `snapshots_today`

Durable counters are stored in:
- `EDGEWATCH_COST_CAP_STATE_PATH` (default: `./edgewatch_cost_caps_<device_id>.json`)

## Camera snapshots + local ring buffer (MVP)

Enable scheduled photo snapshots with a local disk ring buffer:

```bash
MEDIA_ENABLED=true \
CAMERA_IDS=cam1,cam2 \
MEDIA_SNAPSHOT_INTERVAL_S=300 \
uv run python agent/edgewatch_agent.py
```

Notes:
- capture backend: `libcamera-still` (Raspberry Pi camera stack)
- capture is serialized with a lock (one active camera at a time)
- assets + sidecar metadata are stored under `MEDIA_RING_DIR` and oldest assets are evicted when `MEDIA_RING_MAX_BYTES` is exceeded

Manual capture helper:

```bash
python -m agent.tools.camera cam1 --device-id demo-well-001 --reason manual
```

## Simulator

From the repo root:

```bash
make simulate
```

You can also simulate offline operation:

```bash
uv run python agent/simulator.py --simulate-offline-after-s 60 --resume-after-s 180
```

## Replay/backfill from buffer

Replay buffered history by time range (preserves stable `message_id` values):

```bash
uv run python -m agent.replay \
  --since 2026-01-01T00:00:00Z \
  --until 2026-01-02T00:00:00Z \
  --batch-size 100 \
  --rate-limit-rps 2
```
