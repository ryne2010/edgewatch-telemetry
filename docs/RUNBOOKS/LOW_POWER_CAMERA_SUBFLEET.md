# Low-power camera sub-fleet runbook

This runbook brings up one Pi 4/5 field gateway and three to five MCU-supervised
Pi Zero 2 W camera satellites. It implements the accepted architecture in
[`ADR-20260809-low-power-camera-subfleet.md`](../DECISIONS/ADR-20260809-low-power-camera-subfleet.md).

The existing Telegram telemetry bot and channel remain unchanged. Control uses
a different bot and a new private Telegram group. Camera satellites have no
Telegram or LTE credential.

## 1. Hardware boundaries before provisioning

Do not turn on production power switching until each boundary has a reviewed
implementation:

- Gateway LTE: carrier-approved load switch/control that removes modem power,
  prevents back-feed, and is exposed only through the fixed
  `edgewatch-lte-power-on/off.service` units.
- Gateway radio: genuine US915 SX1302/SX1303 concentrator. Install a reviewed
  vendor ingress executable, record its SHA-256, and make it satisfy the strict
  status contract in `deploy/rpi/gateway/lorawan-radio-ingress.example.yaml`.
  EdgeWatch intentionally ships no unreviewed concentrator binary.
- Satellite power: an always-on MCU sentinel controls the Pi/camera rail. The
  MCU must wait for a board-qualified final Linux-halt signal before removing
  power. A result JSON or service exit is not a halt acknowledgement. Before
  energizing the rail for maintenance, it must also commit the authenticated
  wake `(command-token, nonce)` to nonvolatile replay state and echo the command
  token in its `maintenance_ready` frame.
- Maintenance WLAN: switched outdoor point-to-multipoint radio, private
  addressing, and pinned SSH host keys. Complete a site RF survey; the LoRa wake
  is not the bulk-data path.

ChirpStack, Redis, Mosquitto, and the EdgeWatch bridge do not by themselves
drive an RAK2287. First boot remains incomplete until the separately installed
radio adapter proves concentrator detection and bridge connectivity.

## 2. Build the two secret-free images

On the supported native ARM64 Linux image builder:

```bash
make rpi-image RPI_PROFILE=gateway RPI_DEVICE=rpi4 RPI_IMAGE_VERSION=pilot-1
make rpi-image RPI_PROFILE=camera-satellite RPI_DEVICE=rpizero2w RPI_IMAGE_VERSION=pilot-1
```

The gateway profile adds pinned ChirpStack SQLite and Paho MQTT artifacts. The
satellite profile adds FFmpeg and pinned LiteRT 2.1.6. Native dependencies are
base/system-image inputs and are never installed by routine application/model
OTA.

## 3. Provision the gateway

Prepare private mode-0600 files from the gateway examples:

- LoRaWAN gateway config
- DevEUI/OTAA registry (unique keys per satellite)
- radio ingress config and vendor adapter config
- gateway LTE power environment
- existing telemetry bot token

Generate the `edgewatch/` boot-partition subtree with the `gateway` profile.
The generator validates the closed configs, rewrites installed paths, and puts
only per-device inputs on the boot card. The reusable image contains no key,
token, APN credential, camera credential, or device authorization.

```bash
make rpi-provision \
  RPI_PROFILE=gateway \
  DEVICE_ID=gateway-001 \
  OTA_PUBLIC_KEY_FILE=/secure/ota-release.pub \
  OUTPUT_DIR=/media/bootfs \
  TELEGRAM_CHAT_ID=-1001234567890 \
  TELEGRAM_BOT_TOKEN_FILE=/secure/telemetry-bot.token \
  SSH_PUBLIC_KEY_FILE=/secure/operator.pub \
  LORAWAN_GATEWAY_CONFIG_FILE=/secure/lorawan-gateway.yaml \
  LORAWAN_REGISTRY_FILE=/secure/lorawan-registry.yaml \
  LORAWAN_RADIO_INGRESS_FILE=/secure/lorawan-radio-ingress.yaml \
  LORAWAN_VENDOR_CONFIG_FILE=/secure/vendor-radio.yaml \
  GATEWAY_POWER_ENV_FILE=/secure/gateway-power.env
```

The paths above are examples. Keep every private input outside the repository.
The existing telemetry chat ID is reused here; it is not the control-group ID.

First boot must health-gate all of these before committing its completion
marker:

- public-key-only operator SSH;
- telemetry delivery to the existing channel;
- LoRa radio adapter, local ChirpStack bridge, and durable gateway service;
- gateway LTE scheduler in safe `observe` mode.

The gateway control SSH private key is created later on the gateway. It never
enters this provisioning bundle.

## 4. Initialize the separate Telegram control group

1. Create a new bot with BotFather and a new private group. Do not reuse the
   telemetry bot and never paste either token into chat.
2. On the gateway, store the new control-bot token in a root-readable mode-0600
   file.
3. Run:

```bash
make telegram-control-init \
  CONTROL_BOT_TOKEN_FILE=/root/edgewatch-control-bot.token \
  GATEWAY_DEVICE_ID=gateway-001
```

4. When prompted, send `/register@botname` in the new group.

The initializer discovers the numeric group and user IDs, assigns that user the
administrator role, generates the controller Ed25519 key locally, displays only
its public key/fingerprint, writes strict config/state, installs the service,
and executes a local typed status smoke test. The old telemetry channel ID is
not requested again.

## 5. Configure the external dead-man check

Create a hosted check with a one-hour period and a 2 hour 15 minute grace, then
enable its Telegram integration. Store its credential-bearing ping URL in a
root-owned mode-0600 file and point the controller at it with:

```text
EDGEWATCH_DEADMAN_HEARTBEAT_URL_FILE=/etc/edgewatch-controller/deadman-url
```

The check-in runs only during an LTE window. The controller holds the modem on
while the bounded request is in flight. Without this external observer, a dead
gateway cannot report its own failure.

See [Healthchecks.io](https://healthchecks.io/about/) and its
[Telegram integration](https://healthchecks.io/integrations/telegram/).

## 6. Qualify LTE power and energy

Install the carrier-specific fixed on/off hooks, then run the 100-cycle
qualification on a freshly booted Pi with throttle flags at `0x0`:

```bash
sudo /opt/edgewatch/app/.venv/bin/python -m scripts.gateway_lte_qualify \
  --cycles 100 --interface wwan0
```

It powers off first and last, proves HTTPS through the cellular interface on
every cycle, records attach time, rejects any current/sticky undervoltage or
throttling bit, and writes a private durable report.

Measure `pi_only`, `lte_registered_idle`, `lte_transfer`, and
`lte_electrically_off` with an inline meter. Collect one 24-hour sample for the
initial benchmark and at least seven daily samples for production sizing. Run:

```bash
make gateway-energy-report \
  GATEWAY_ENERGY_INPUT=measurements.json \
  GATEWAY_ENERGY_REPORT=qualification.json
```

The report rejects a P95 no-camera average above 5 W and calculates seven-day
battery nameplate energy plus the minimum 1.5x daily solar-energy target. Select
panel watts from the deployment coordinates and worst-month
[NREL PVWatts](https://pvwatts.nrel.gov/). Use LiFePO4 only with a qualified
low-temperature charge block/heater.

## 7. Qualify and provision one camera satellite

Pilot local-only outdoor IP cameras, starting with the
[ANNKE C500P/C500D family](https://www.annke.com/products/c500p) and then
[TP-Link VIGI C340/C440](https://www.tp-link.com/us/business-networking/vigi-network-camera/vigi-c340/).
Block Internet access during qualification. The evaluator requires:

- H.264 RTSP substream plus actual AAC or G.711 audio;
- local credentials, no mandatory cloud account, IP67 or better, and 12 V/PoE;
- first usable audio/video within 90 seconds;
- at least 99 successful starts over 100 power cycles;
- automatic recovery over a 24-hour interruption test;
- satellite electronics cost below $200, excluding battery and solar.

Persist those observations as JSON and validate them with:

```bash
make camera-qualification-report \
  CAMERA_QUALIFICATION_INPUT=camera-evidence.json \
  CAMERA_QUALIFICATION_REPORT=camera-qualification.json
```

The input is closed and requires one first-media observation for every
successful start, preventing a summary from hiding slow successful cycles.

Provision the `camera-satellite` profile with a private RTSP credential file,
camera runtime environment, model verification public key, and initial signed
model bundle. The initial bundle is required because the reusable secret-free
image deliberately contains no site model. The profile rejects Telegram/API/LTE
values and begins in shadow mode.

After control initialization has generated the gateway controller key, copy
only its displayed public key into a file and provision each satellite:

```bash
make rpi-provision \
  RPI_PROFILE=camera-satellite \
  DEVICE_ID=camera-001 \
  OTA_PUBLIC_KEY_FILE=/secure/ota-release.pub \
  OUTPUT_DIR=/media/bootfs \
  CONTROL_SSH_PUBLIC_KEY_FILE=/secure/gateway-controller.pub \
  CAMERA_RUNTIME_ENV_FILE=/secure/camera-001.env \
  CAMERA_CREDENTIALS_FILE=/secure/camera-001.credentials \
  MODEL_PUBLIC_KEY_FILE=/secure/model-release.pub \
  INITIAL_MODEL_BUNDLE_FILE=/secure/model-initial.tar.gz \
  OTA_GATEWAY_CACHE_URL=http://10.42.0.1:8091
```

Use only the wake units from the MCU:

```bash
systemctl start edgewatch-camera-satellite-wake@event.service
systemctl start edgewatch-camera-satellite-wake@daily.service
```

The `@check` unit is reserved for first boot and signed-model readiness. It
never captures evidence or requests shutdown.

## 8. Build and roll out a signed model bundle

Training happens off-device. The release source contains exactly two fully
quantized signed-integer INT8 `.tflite` models and four JSON contracts: labels,
preprocessing, thresholds, and known-answer cases.

```bash
make model-release \
  MODEL_SOURCE_DIR=model-release-src \
  MODEL_PRIVATE_KEY_FILE=/secure/model-signing-key.pem \
  MODEL_ARTIFACT_URI=https://artifacts.example/models/model-1.tar.gz \
  MODEL_VERSION=1.0.0 \
  OUTPUT_DIR=dist/model-1
```

The signed outer asset release enters the existing Telegram OTA catalog. Stage
every frozen target, apply one canary, then promote 10/50/100%. The satellite
validates both signatures/digests, compatibility, signed INT8 tensor types and
exact shapes, and known-answer results. Readiness failure atomically restores
the prior model.

The gateway downloads a release once, validates it, and stores it by SHA-256.
Satellites fetch that immutable object over maintenance Wi-Fi and independently
verify its signed manifest, size, digest, and signature. Cache object count,
total bytes, minimum free space, HTTP concurrency, and socket timeouts are
bounded in the controller configuration. A download holds the LTE window only
through its configured deadline and never beyond the absolute held-window cap.

Start with a 14-day shadow trial. Live promotion additionally requires at least
95% held-out alert precision and no more than one false alert per device-day.
Routine clips remain on SD and are retrieved only explicitly over maintenance
Wi-Fi or physically.

## 9. Pilot acceptance

Do not promote remote alerts/OTA until all are true:

- 1,000 LoRa uplinks over the intended line of sight with at least 99% eventual
  delivery;
- gateway outage/replay and duplicate suppression proven;
- 50 event-to-Telegram trials with P95 below five minutes;
- maintenance wake, pinned SSH, signed canary, interrupted transfer, and
  rollback proven;
- seven days without solar ending with at least 20% battery reserve;
- every camera, modem, radio, and power-latch hardware qualification report is
  retained with the deployed cohort record.

Normal Class A control may wait up to one hour. An authenticated fault/event
uplink opens LTE immediately; that path carries the five-minute objective.
