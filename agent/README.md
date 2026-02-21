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
- `derived` (placeholder, emits `None` metrics until Task 11d lands)

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
