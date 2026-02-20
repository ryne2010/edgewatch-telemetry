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

Replace `sensors/mock_sensors.py` with integrations like:
- GPIO / ADC sensors
- Modbus
- reading `/sys` or systemd status
- reading a serial device

Keep the output as a dict of metric keys → values.

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
