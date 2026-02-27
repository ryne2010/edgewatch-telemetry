# Deploying the Edge Agent to Raspberry Pi

This guide deploys the **EdgeWatch agent** on a Raspberry Pi as a `systemd` service.

The agent:

- Authenticates with the API using a **device token**
- Fetches **device policy** from `GET /api/v1/device-policy` (ETag + Cache-Control cached)
- Samples sensors (real or simulated), applies **delta suppression**, buffers locally, and ships batches to the API
- Evaluates **local alert thresholds** from the policy (microphone level, water/oil pressure, oil levels, oil life, battery, signal) for faster detection

## Target environment

- Raspberry Pi OS Lite (64-bit) recommended
- Python 3.10+ (3.11+ preferred)
- Network access to your API (Cloud Run URL or local dev)

## Zero-touch first boot (preformatted SD)

For fastest field startup:

1. Preload SD card with Raspberry Pi OS + agent `.env` + systemd unit.
2. Set `SENSOR_CONFIG_PATH=./agent/config/rpi.microphone.sensors.yaml`.
3. Insert SD card, connect 12V-to-5V regulated power path, boot device.
4. Device fetches policy, applies pending control command (if any), and starts telemetry automatically.

## 1) Create the device on the server

You need a `device_id` and a **device token**. The token is stored hashed server-side.

Recommended options:

- Use the **Admin UI** on your *admin service* (fastest).
- Or create the device via the admin API (scriptable).

### Which URL do I use?

Admin endpoints are optional and may be deployed in one of these patterns:

- **Single service (dev/private):** `/api/v1/admin/*` is mounted on the same base URL.
- **Split-admin (recommended for IoT):** public ingest service has `ENABLE_ADMIN_ROUTES=0`, and a separate **private admin service** has `ENABLE_ADMIN_ROUTES=1`.

If you used Terraform split-admin profiles, fetch URLs with:

```bash
make url-gcp       # public ingest service
make url-gcp-admin # private admin service
```

### Auth mode

- If the admin service is running with `ADMIN_AUTH_MODE=key`, you must send `X-Admin-Key`.
- If the admin service is running with `ADMIN_AUTH_MODE=none`, the service should be protected by Cloud Run IAM/IAP, and you typically invoke it with an **identity token**.

### Create device via curl

From your laptop (or anywhere with network access to the admin service):

```bash
export ADMIN_BASE_URL="https://YOUR-ADMIN-SERVICE-URL"  # may be the same as the public URL in dev

export DEVICE_ID="rpi-001"
export DEVICE_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

#### Option A: Admin key mode

```bash
export ADMIN_KEY="..."  # matches ADMIN_API_KEY on the server

curl -sS -X POST "$ADMIN_BASE_URL/api/v1/admin/devices" \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d @- <<'JSON' | jq
{
  "device_id": "${DEVICE_ID}",
  "display_name": "RPi #1",
  "token": "${DEVICE_TOKEN}",
  "heartbeat_interval_s": 60,
  "offline_after_s": 600,
  "enabled": true
}
JSON
```

#### Option B: IAM-perimeter mode

```bash
export ID_TOKEN="$(gcloud auth print-identity-token)"

curl -sS -X POST "$ADMIN_BASE_URL/api/v1/admin/devices" \
  -H "Authorization: Bearer $ID_TOKEN" \
  -H "Content-Type: application/json" \
  -d @- <<'JSON' | jq
{
  "device_id": "${DEVICE_ID}",
  "display_name": "RPi #1",
  "token": "${DEVICE_TOKEN}",
  "heartbeat_interval_s": 60,
  "offline_after_s": 600,
  "enabled": true
}
JSON
```

Keep `DEVICE_TOKEN` secret.

## 2) Prepare the Raspberry Pi

Install OS packages:

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip alsa-utils i2c-tools
```

(Optional) If you use I2C sensors, enable I2C (`raspi-config`) and reboot.

## 3) Install the agent

Clone the repo:

```bash
cd ~
git clone https://YOUR_GIT_REMOTE/edgewatch-telemetry.git
cd edgewatch-telemetry
```

Create a minimal venv for the agent:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r agent/requirements.txt
pip install smbus2
```

## 4) Configure the agent

Create an env file:

```bash
cd ~/edgewatch-telemetry/agent
cp .env.example .env
nano .env
```

Minimum required values:

```bash
EDGEWATCH_API_URL=https://YOUR-CLOUD-RUN-URL
EDGEWATCH_DEVICE_ID=rpi-001
EDGEWATCH_DEVICE_TOKEN=PASTE_DEVICE_TOKEN_HERE
SENSOR_CONFIG_PATH=./agent/config/rpi.microphone.sensors.yaml
```

Recommended production values:

```bash
# Persisted buffer (survives reboots)
BUFFER_DB_PATH=/var/lib/edgewatch/telemetry_buffer.sqlite

# Persist device policy cache (saves bandwidth + speeds cold starts)
EDGEWATCH_POLICY_CACHE_PATH=/var/lib/edgewatch/policy_cache_rpi-001.json

# Persist power management rolling-window state.
EDGEWATCH_POWER_STATE_PATH=/var/lib/edgewatch/power_state_rpi-001.json

# Persist durable control-command apply/ack state.
EDGEWATCH_COMMAND_STATE_PATH=/var/lib/edgewatch/command_state_rpi-001.json

# Hybrid-disable guard (default safe posture):
# keep remote OS shutdown disabled unless explicitly approved for this device.
# EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=0

# Optional: write permanently-failed payloads for later inspection
# EDGEWATCH_DEADLETTER_PATH=/var/lib/edgewatch/deadletter_rpi-001.jsonl
```

Microphone + power backend prerequisites:

```bash
# should already be installed above, listed here for clarity:
sudo apt-get install -y alsa-utils i2c-tools
pip install smbus2
```

Optional sensor tuning in `agent/.env`:

```bash
# SENSOR_CONFIG_PATH=./agent/config/rpi.microphone.sensors.yaml
# POWER_MGMT_ENABLED=true
# POWER_MGMT_MODE=dual
# POWER_INPUT_WARN_MIN_V=11.8
# POWER_INPUT_WARN_MAX_V=14.8
# POWER_SUSTAINABLE_INPUT_W=15.0
```

Create the buffer directory:

```bash
sudo mkdir -p /var/lib/edgewatch
sudo chown -R $USER:$USER /var/lib/edgewatch
```

## 5) Run the agent manually (first boot test)

```bash
cd ~/edgewatch-telemetry/agent
source ../.venv/bin/activate
python edgewatch_agent.py
```

You should see logs for:

- policy fetch (HTTP 200 or 304)
- sampling loop
- batch post to `/api/v1/ingest`

Check the UI:

- Devices page should show your Pi device
- Device detail should show telemetry points

## 6) Install as a systemd service

Create a service file:

```bash
sudo tee /etc/systemd/system/edgewatch-agent.service > /dev/null <<'UNIT'
[Unit]
Description=EdgeWatch Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/pi/edgewatch-telemetry/agent
EnvironmentFile=/home/pi/edgewatch-telemetry/agent/.env
ExecStart=/home/pi/edgewatch-telemetry/.venv/bin/python /home/pi/edgewatch-telemetry/agent/edgewatch_agent.py
Restart=always
RestartSec=5

# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/lib/edgewatch

[Install]
WantedBy=multi-user.target
UNIT
```

Enable + start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now edgewatch-agent
sudo systemctl status edgewatch-agent
```

Tail logs:

```bash
journalctl -u edgewatch-agent -f
```

## Offseason / long intermission controls

Use device controls from the dashboard or API:

- `PATCH /api/v1/devices/{device_id}/controls/alerts`
  - mute notifications only (alerts still open/resolve server-side)
- `PATCH /api/v1/devices/{device_id}/controls/operation`
  - `sleep` for low-duty polling (`sleep_poll_interval_s`, default 7 days)
  - `disabled` for logical disable; on-device restart required to resume
- `POST /api/v1/admin/devices/{device_id}/controls/shutdown` (admin-only)
  - queues one-shot `disabled + shutdown_requested` command
  - device executes OS shutdown only when `EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=1`

Recommended operator posture:

- offseason: set `sleep` + long mute window reasoned as `offseason`
- service outage/maintenance: use alert mute without changing operation mode
- hard stop without remote power-off: use owner/operator `disabled`
- hard stop with one-shot remote power-off (admin only): use shutdown endpoint on devices
  explicitly configured with `EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=1`

## Troubleshooting

- **401/403**: token mismatch; confirm the device exists and the token matches what you created.
- **No telemetry in UI**: confirm `EDGEWATCH_API_URL` points to the API base URL (no trailing `/api/v1`).
- **Buffer errors**: ensure the buffer path directory exists and is writable.
- **Clock skew**: set NTP/timezone correctly; timestamps matter for “last seen”.
- **Power sensor warnings**: verify INA219/INA260 wiring, I2C bus/address, and `smbus2` install.
- **Frequent saver mode activation**: check source input stability and tune `power_management` thresholds in `contracts/edge_policy/v1.yaml`.
- **Power alert churn**: validate sensor calibration and follow `docs/RUNBOOKS/POWER.md`.
