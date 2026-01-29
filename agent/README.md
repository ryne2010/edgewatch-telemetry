# EdgeWatch Agent (Raspberry Pi / edge device)

This folder contains a simple Python agent that:
- reads sensors (mocked by default)
- sends telemetry points to the API
- buffers locally to SQLite if offline
- flushes buffered points when connectivity returns

## Setup

```bash
# From the repo root:
uv sync
cp agent/.env.example agent/.env
uv run python agent/edgewatch_agent.py
```

## Real sensors

Replace `sensors/mock_sensors.py` with integrations like:
- GPIO / ADC sensors
- Modbus
- reading `/sys` or systemd status
- reading a serial device

Keep the output as a dict of metric keys → values.
