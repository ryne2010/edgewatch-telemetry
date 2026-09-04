# Deploying the Edge Agent to Raspberry Pi

This guide deploys the **EdgeWatch agent** on a Raspberry Pi as a `systemd` service.

In API mode, the agent:

- Authenticates with the API using a **device token**
- Fetches **device policy** from `GET /api/v1/device-policy` (ETag + Cache-Control cached)
- Samples sensors (real or simulated), applies **delta suppression**, buffers locally, and ships batches to the API
- Evaluates **local alert thresholds** from the policy (microphone level, water/oil pressure, oil levels, oil life, battery, signal) for faster detection

## Target environment

- Raspberry Pi OS Lite (64-bit) recommended
- Ubuntu is best-effort only and is not the primary tested low-power path for v1
- Python 3.10+ (3.11+ preferred)
- Network access to your API (Cloud Run URL or local dev)

In Telegram-exclusive mode, the agent uses local policy and does not require
EdgeWatch API credentials.

## Recommended fleet-image-v1 lane

Use the pinned, secret-free image for repeatable fleet staging:

1. On a capable native ARM64 Linux builder, run
   `make rpi-image RPI_DEVICE=rpizero2w`. The pinned official
   `rpi-image-gen` lane emits `*.img.xz`, a SHA-256 file, and a manifest under
   `dist/rpi-image/`.
2. Verify and flash the compressed image. It contains the stable application at
   `/opt/edgewatch/app`, but no device secrets, configuration, machine identity,
   SSH host keys, or operator public key. The image creates a locked `ryne`
   account with passwordless sudo and public-key-only SSH; first boot supplies
   its authorized key.
3. Generate a unique boot bundle:

   ```bash
   make rpi-provision \
     DEVICE_ID=rpi-001 \
     TELEGRAM_CHAT_ID=-1001234567890 \
     TELEGRAM_BOT_TOKEN_FILE="$PWD/secrets/telegram_bot_token" \
     SSH_PUBLIC_KEY_FILE="$HOME/.ssh/id_ed25519.pub" \
     CONTROL_SSH_PUBLIC_KEY_FILE="$PWD/secrets/controller_ed25519.pub" \
     OTA_PUBLIC_KEY_FILE="$PWD/secrets/edgewatch-ota-release.pem" \
     OTA_KEY_ID=edgewatch-release \
     OUTPUT_DIR="$PWD/dist/rpi-provision/rpi-001"
   ```

4. Copy the generated `edgewatch/` directory to the flashed boot partition.
5. Insert the SIM and boot. First boot installs the operator key, installs the
   different controller key as a forced typed command, installs the OTA public
   trust anchor, imports the Telegram telemetry token, removes the consumed boot
   copies, sets the hostname, activates LTE, starts the agent, sends a Telegram
   provisioning receipt, and writes `/var/lib/edgewatch/bootstrap-report.json`
   only after the agent, LTE, and Telegram health gates pass. The systemd unit
   retries failed attempts.

The generated directory contains `bootstrap.env`, `telegram_bot_token`,
`authorized_key`, `control_authorized_key`,
`ota_keys/<OTA_KEY_ID>.pem`, and `provisioning-manifest.json`. It never contains
the controller SSH private key, OTA signing private key, or Telegram control-bot
token. Operator and controller SSH keys must use different key material.

The FAT boot partition does not enforce the generator's local Unix file modes.
Treat the flashed card as credential-bearing and keep it physically controlled
until first boot imports the Telegram token into root-owned storage and durably
removes the token and public-key staging copies before marking provisioning
complete.

The generator defaults to the Hologram APN, `SENSOR_BACKEND=none`, continuous
power, SQLite `synchronous=FULL`, Telegram batching, and a disabled cellular
watchdog. Use continuous power for bring-up; move to `eco` after a successful
soak. `deep_sleep` remains hardware-dependent.

See [Raspberry Pi zero-touch fleet bootstrap](TUTORIALS/RPI_ZERO_TOUCH_BOOTSTRAP.md)
for the full workflow.

Provisioning prepares the device side of API-free control and signed OTA, but
does not start a controller. Configure the dedicated control bot, numeric
chat/user RBAC, device inventory, pinned host keys, controller state, release
catalog, and controller supervisor by following
[Telegram fleet control](RUNBOOKS/TELEGRAM_FLEET_CONTROL.md).

The manual install below remains available for development and API-connected
devices.

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

## 2b) Optional: Tailscale operator overlay

Use this when you want private operator access from your MacBook to edge devices without changing EdgeWatch's normal hosted posture.

- Keep `EDGEWATCH_API_URL` pointed at the existing public ingest URL. Tailscale is for private operator access, not telemetry transport.
- On the MacBook, keep the current `Tailscale.app` install or switch to the standalone macOS variant only if you need the CLI-specific features documented by Tailscale.
- In the Tailscale admin console:
  - enable MagicDNS if your tailnet does not already have it
  - generate a **one-off**, **pre-approved**, **tagged** auth key for edge nodes
  - use `tag:edgewatch-device` as the baseline tag and add a site tag only when you need location-scoped policy

Install Tailscale on the Raspberry Pi:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --auth-key="$TAILSCALE_AUTH_KEY" --hostname="$DEVICE_ID"
```

Optional: enable Tailscale SSH on the device when you want identity-based SSH instead of plain SSH over the tailnet:

```bash
sudo tailscale set --ssh
```

Recommended policy intent:

- Use Tailscale grants, not legacy ACL-first policy design.
- Allow only your operator identity to reach `tag:edgewatch-device` on SSH and any explicitly approved device-local ports.
- Do not grant broad all-port access to edge nodes by default.

Verification from the MacBook:

```bash
ping <device-magicdns-name>
ssh <device-magicdns-name>
```

Reference docs:

- [Install Tailscale on macOS](https://tailscale.com/docs/install/mac)
- [MagicDNS](https://tailscale.com/kb/1081/magicdns)
- [Auth keys](https://tailscale.com/kb/1085/auth-keys)
- [Access control](https://tailscale.com/kb/1393/access-control)
- [Install Tailscale on Linux](https://tailscale.com/docs/install/linux)
- [Tailscale SSH](https://tailscale.com/kb/1193/tailscale-ssh)
- Repo runbook: `docs/RUNBOOKS/TAILSCALE_OPERATOR.md`

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

For API transport, configure:

```bash
EDGEWATCH_API_URL=https://YOUR-CLOUD-RUN-URL
EDGEWATCH_DEVICE_ID=rpi-001
EDGEWATCH_DEVICE_TOKEN=PASTE_DEVICE_TOKEN_HERE
SENSOR_CONFIG_PATH=./agent/config/rpi.microphone.sensors.yaml
```

For Telegram-exclusive bring-up, API URL and device token are not required. The
bot must be a channel admin with permission to post:

```bash
EDGEWATCH_TELEMETRY_TRANSPORT=telegram
EDGEWATCH_DEVICE_ID=rpi-home-001
TELEGRAM_CHAT_ID=-1001234567890
TELEGRAM_BOT_TOKEN_FILE=/var/lib/edgewatch/telegram_bot_token
TELEGRAM_BATCH_ENABLED=true
TELEGRAM_BATCH_MAX_POINTS=100
TELEGRAM_BATCH_MAX_BYTES=1000000
TELEGRAM_BATCH_MAX_AGE_S=3600
SENSOR_BACKEND=none
MEDIA_ENABLED=false
BUFFER_MAX_POINTS=10000
BUFFER_MAX_AGE_S=2592000
BUFFER_MAX_DB_BYTES=104857600
```

Create the bot-token file after `/var/lib/edgewatch` exists. Enter the actual
token locally on the Pi; do not commit it or paste it into service logs:

```bash
sudo install -d -m 0750 -o "$USER" -g "$USER" /var/lib/edgewatch
umask 077
read -rsp 'Telegram bot token: ' edgewatch_telegram_token
printf '\n'
printf '%s\n' "$edgewatch_telegram_token" > /var/lib/edgewatch/telegram_bot_token
unset edgewatch_telegram_token
chmod 600 /var/lib/edgewatch/telegram_bot_token
```

In this mode, the local fallback-policy variables below are authoritative. The
agent makes no EdgeWatch API calls; API policy/control, API OTA
delivery/reporting, server-side alerts/dashboard storage, and API media uploads
are unavailable. A separately deployed Telegram fleet controller can still
provide the repository's allowlisted typed controls and signed
application-bundle OTA through pinned SSH/Spacebridge. The telemetry bot itself
does not provide this control path, and the controller is not live until it is
configured and supervised.
Routine points are sent oldest-first as gzip JSONL batches. The current startup,
heartbeat, state/alert transition, or alert snapshot point is durably enqueued
and sent directly, without first draining older routine rows. Below the routine
daily cap, one independently bounded backlog request may follow; at the cap,
only the configured urgent reserve is available. Successful Bot API
acknowledgement removes included rows from SQLite. Delivery remains at least once.
The example outbox limits retain up to 30 days/10,000 points subject to the
100 MB disk cap; oldest undelivered points are evicted if any bound is exceeded.
Use `BUFFER_SQLITE_SYNCHRONOUS=FULL` on field devices for stronger committed-write
durability across sudden power loss (at the cost of additional storage I/O).

Telegram does not provide an independent missing-heartbeat alarm: a Pi that
loses power or connectivity simply stops posting. A shared bot token identifies
the bot, not the physical sender, so it is not strong per-device provenance.
Use separate bots per trust boundary and an external heartbeat monitor when
those properties matter.

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

# Persist durable OTA command/apply state.
EDGEWATCH_UPDATE_STATE_PATH=/var/lib/edgewatch/update_state_rpi-001.json

# Telegram-controller OTA uses a separate local state file and immutable
# release/cache/key paths. fleet-image-v1 provisioning sets these automatically.
EDGEWATCH_LOCAL_OTA_STATE_PATH=/var/lib/edgewatch/local_ota_rpi-001.json
EDGEWATCH_OTA_CACHE_DIR=/opt/edgewatch/update-cache
EDGEWATCH_OTA_KEYRING_DIR=/opt/edgewatch/keys
EDGEWATCH_RELEASES_ROOT=/opt/edgewatch/releases
EDGEWATCH_CURRENT_SYMLINK=/opt/edgewatch/current
EDGEWATCH_RUNTIME_DEPENDENCY_PATH=/opt/edgewatch/current/agent/requirements.txt
EDGEWATCH_OTA_POWER_EVIDENCE_MAX_AGE_S=300

# Persist wake bookkeeping for eco/deep-sleep runtime.
EDGEWATCH_LOW_POWER_STATE_PATH=/var/lib/edgewatch/low_power_state_rpi-001.json

# Persist actual cellular-interface usage across restarts. When available,
# wwan transmit totals are preferred for daily byte-budget enforcement.
CELLULAR_USAGE_STATE_PATH=/var/lib/edgewatch/cellular_usage_rpi-001.json

# Persist daily cap counters and reserve up to 256 KiB/day beyond the routine
# byte cap for bounded startup/heartbeat/state/alert telemetry.
EDGEWATCH_COST_CAP_STATE_PATH=/var/lib/edgewatch/cost_caps_rpi-001.json
EDGEWATCH_COST_CAP_URGENT_RESERVE_BYTES=262144

# Optional runtime power defaults (device policy remains the source of truth).
# RUNTIME_POWER_MODE=continuous
# DEEP_SLEEP_BACKEND=auto

# Hybrid-disable guard (default safe posture):
# keep remote OS shutdown disabled unless explicitly approved for this device.
# EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=0

# OTA apply guard (safe default is dry-run/stage-only behavior).
# This flag gates both API-delivered OTA apply and Telegram-controller local
# application/asset/system-image activation. Enable it only on validated cohorts.
# EDGEWATCH_ENABLE_OTA_APPLY=0

# Application-bundle OTA currently changes reviewed code only. Its signed
# requirements fingerprint must match the installed runtime; dependency changes
# require a new base/system image until dependency-aware activation is qualified.

# Telegram-controller system-image apply remains disabled until real-hardware
# reboot and rollback qualification. Application bundles are the initial path.
# EDGEWATCH_ENABLE_SYSTEM_IMAGE_APPLY=0
# EDGEWATCH_SYSTEM_IMAGE_HARDWARE_QUALIFIED=0

# Optional: write permanently-failed payloads for later inspection
# EDGEWATCH_DEADLETTER_PATH=/var/lib/edgewatch/deadletter_rpi-001.jsonl
```

Microphone + power backend prerequisites:

```bash
# should already be installed above, listed here for clarity:
sudo apt-get install -y alsa-utils i2c-tools
pip install smbus2
```

Microphone mounting guidance:

```text
- Use a short external protected mic mount.
- Add strain relief and a drip loop on the mic cable.
- Prefer a small hood or downward-facing sheltered location.
- Do not rely on a loose USB mic sitting inside the sealed enclosure.
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

Low-power deployment tiers:

1. `continuous`
   - simplest default
   - full-time connectivity
   - best for pilot bring-up and debugging
2. `eco`
   - no extra hardware
   - batches routine application transmissions to heartbeat windows
   - keeps the LTE bearer attached by default for reliable alert latency
   - recommended first power optimization step on Pi 4 and Pi 5
3. `deep_sleep`
   - Pi 5: use onboard RTC wakealarm path
   - Pi 4: requires optional external RTC/power-latch supervisor
   - commands and OTA apply on wake, not continuously

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

- selected transport (`api` or `telegram`)
- API mode: policy fetch (HTTP 200 or 304)
- Telegram mode: local-policy notice and a successful `sent` line
- sampling loop
- API mode: batch post to `/api/v1/ingest`
- Telegram mode: a gzip JSONL document in the configured channel (urgent
  startup/alert delivery may contain a partial batch)

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
  - `runtime_power_mode` (`continuous|eco|deep_sleep`)
  - `deep_sleep_backend` (`auto|pi5_rtc|external_supervisor|none`)
- `POST /api/v1/admin/devices/{device_id}/controls/shutdown` (admin-only)
  - queues one-shot `disabled + shutdown_requested` command
  - device executes OS shutdown only when `EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=1`

Recommended operator posture:

- offseason: set `sleep` + long mute window reasoned as `offseason`
- service outage/maintenance: use alert mute without changing operation mode
- lower power without extra hardware: use `runtime_power_mode=eco`
- true between-sample halt:
  - Pi 5: `runtime_power_mode=deep_sleep`, `deep_sleep_backend=pi5_rtc`
  - Pi 4: `runtime_power_mode=deep_sleep`, `deep_sleep_backend=external_supervisor`
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
