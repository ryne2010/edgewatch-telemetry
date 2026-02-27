# Tutorial: RPi Zero-Touch Bootstrap (Preformatted SD)

Goal: bring a new Raspberry Pi online with microphone + power telemetry using a preformatted SD card and minimal site work.

## 1) Pre-stage assets on the SD card

1. Flash Raspberry Pi OS Lite (64-bit).
2. Copy agent repo or deployment bundle.
3. Pre-create `agent/.env` with:
   - `EDGEWATCH_API_URL`
   - `EDGEWATCH_DEVICE_ID`
   - `EDGEWATCH_DEVICE_TOKEN`
   - `SENSOR_CONFIG_PATH=./agent/config/rpi.microphone.sensors.yaml`
4. Pre-create persistent paths:
   - `BUFFER_DB_PATH=/var/lib/edgewatch/telemetry_buffer.sqlite`
   - `EDGEWATCH_POLICY_CACHE_PATH=/var/lib/edgewatch/policy_cache_<device>.json`
   - `EDGEWATCH_POWER_STATE_PATH=/var/lib/edgewatch/power_state_<device>.json`
   - `EDGEWATCH_COMMAND_STATE_PATH=/var/lib/edgewatch/command_state_<device>.json`
5. Set shutdown guard explicitly:
   - default safe posture: `EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=0`

## 2) Hardware hookup at site

1. Insert SD card.
2. Connect regulated 5V rail fed from 12V lead-acid/solar chain.
3. Connect microphone + INA219/INA260 on I2C.
4. Connect USB LTE modem with active data SIM.

## 3) First boot validation

1. Confirm systemd service is running:
   - `sudo systemctl status edgewatch-agent`
2. Confirm policy fetch + ingest logs:
   - `journalctl -u edgewatch-agent -f`
3. Confirm device appears in UI with:
   - `microphone_level_db`
   - `power_input_v|a|w`
   - `power_*` flags

## 4) Remote control sanity check

1. Set device to `sleep` from UI/API.
2. Verify agent applies pending command on next policy fetch.
3. Verify command ack path succeeds and pending count clears.
4. If testing admin shutdown intent:
   - keep `EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=0` for safety first
   - confirm command is acknowledged and device remains logically disabled
   - enable `EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=1` only for controlled shutdown tests

## 5) Failure handling

- If LTE is not attached, agent buffers locally and flushes on reconnect.
- If power sensor reads fail, power metrics degrade to `None`/`unknown` without crashing ingestion.
- If control ack fails, agent retries using durable local command state.
- If shutdown intent is delivered while guard is off, agent logs guarded skip and stays disabled.
