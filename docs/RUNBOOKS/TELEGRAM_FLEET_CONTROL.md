# Telegram fleet control runbook

## Purpose and current status

This is the operator path for controlling an EdgeWatch fleet without hosting
the EdgeWatch API. Telegram is the only operator interface. A single supervised
controller receives control-bot updates and reaches devices through pinned SSH:

- direct SSH while a device is on the home network;
- Hologram Spacebridge SSH after the device moves to the field.

The telemetry bot and control bot are separate. Devices keep only the telemetry
bot token used for outbound posts. The control bot token, controller SSH private
key, inventory, authorization policy, release catalog, SQLite state, and pinned
host keys stay on the controller host.

The implementation and provisioning support are in this repository, but this
controller is **not live merely because a Pi was provisioned**. It becomes live
only after an operator creates the controller configuration and secret files,
pins every SSH host key, starts the controller service, and completes the home
network checks below.

See the accepted
[Telegram fleet-control ADR](../DECISIONS/ADR-20260809-telegram-fleet-control.md)
for the security and delivery decisions.

## Topology

```text
operator -> Telegram control bot -> one fleet controller
                                      |-- direct pinned SSH (home)
                                      `-- Spacebridge + pinned device SSH (field)
                                                   |
                                           forced typed helper
                                                   |
                                             EdgeWatch agent

device -> Telegram telemetry bot -> telemetry channel
```

Telegram is not used as a device command queue. The controller is the one
consumer of the control bot's update stream and persists work before accepting
it. A separate supervised dispatch worker claims queued commands with a lease
and sends typed envelopes over SSH in bounded waves. This keeps Telegram polling
and reply delivery responsive while devices or Spacebridge are slow. Do not run
the same control bot token on multiple controllers at once.

## 1. Prepare the trust material

Create these as separate credentials:

1. **Telemetry bot token** — installed on each device for outbound telemetry.
2. **Control bot token** — stored only on the controller host.
3. **Operator SSH key** — ordinary human maintenance access.
4. **Controller SSH key** — device control only; first boot constrains it to the
   root-owned typed helper through an OpenSSH forced command.
5. **Spacebridge identity** — stored only on the controller when field access is
   enabled.
6. **OTA signing key pair** — the private RSA key remains offline or in CI
   secret storage; only the public key is provisioned to devices.

Use mode `0600` or stricter for the control-bot token and private keys. The
controller rejects permissive secret files. Never reuse the operator and
controller SSH key material.

Before provisioning cards, export the OTA public key from the signing key if it
does not already exist:

```bash
openssl pkey \
  -in "$PWD/secrets/edgewatch-ota-signing.pem" \
  -pubout \
  -out "$PWD/secrets/edgewatch-ota-release.pem"
```

The signing private key must not be copied into a provisioning bundle, onto an
SD card, or onto a Pi.

## 2. Provision each Pi

Use the reusable image and a unique per-device bundle. The generator requires
both SSH public keys and the OTA trust anchor:

```bash
make rpi-provision \
  DEVICE_ID=rpi-001 \
  TELEGRAM_CHAT_ID=-1001234567890 \
  TELEGRAM_BOT_TOKEN_FILE="$PWD/secrets/telemetry_bot_token" \
  SSH_PUBLIC_KEY_FILE="$HOME/.ssh/id_ed25519.pub" \
  CONTROL_SSH_PUBLIC_KEY_FILE="$PWD/secrets/controller_ed25519.pub" \
  OTA_PUBLIC_KEY_FILE="$PWD/secrets/edgewatch-ota-release.pem" \
  OTA_KEY_ID=edgewatch-release \
  OUTPUT_DIR="$PWD/dist/rpi-provision/rpi-001"
```

The generated `edgewatch/` directory contains:

- `bootstrap.env` — non-secret per-device configuration;
- `telegram_bot_token` — outbound telemetry credential;
- `authorized_key` — ordinary operator public key;
- `control_authorized_key` — separate controller public key;
- `ota_keys/edgewatch-release.pem` — OTA verification public key;
- `provisioning-manifest.json` — non-secret file map and trust-anchor hash.

First boot installs the operator key normally and installs the controller key
with a forced command. The controller key cannot request a shell, PTY, agent
forwarding, port forwarding, raw modem command, arbitrary file access, or an
alternate program. First boot also installs the OTA public key and removes the
boot-partition copies after all health gates pass.

Follow [Raspberry Pi zero-touch fleet bootstrap](../TUTORIALS/RPI_ZERO_TOUCH_BOOTSTRAP.md)
for the complete image, card, and first-boot procedure.

## 3. Create the controller configuration

Use immutable numeric Telegram chat and user IDs encoded as quoted strings.
Usernames and display names are not authorization identities. In a Telegram
forum, bind a fleet to its numeric topic ID as well.

The controller configuration is strict YAML. A minimal home-network example is:

```yaml
telegram:
  token_file: /etc/edgewatch-controller/control_bot_token
  poll_timeout_s: 30
  request_timeout_s: 40

storage:
  database_path: /var/lib/edgewatch-controller/controller.sqlite

ssh:
  device_key_file: /etc/edgewatch-controller/controller_device_ed25519
  known_hosts_file: /etc/edgewatch-controller/known_hosts
  username: ryne
  connect_timeout_s: 10
  command_timeout_s: 60

authorization:
  allowed_chats: ["-1001234567890"]
  users:
    "123456789":
      role: admin
      fleets: [home-pilot]
    "234567890":
      role: operator
      fleets: [home-pilot]
    "345678901":
      role: viewer
      fleets: [home-pilot]

devices:
  rpi-001:
    fleet: home-pilot
    host: 192.168.1.42
    transport: direct
    enabled: true
    capabilities:
      - status
      - health
      - network
      - power
      - queue
      - version
      - ota
      - sample_now
      - sync_now
      - set_operation_mode
      - set_power_mode
      - deep_sleep
      - alerts_mute
      - alerts_unmute
      - agent_restart
      - reboot

fleets:
  home-pilot:
    devices: [rpi-001]
    canaries: [rpi-001]
    # topic_id: "77"

ota:
  catalog_file: /etc/edgewatch-controller/releases.json
  rollout_percentages: [10, 50, 100]
  failure_rate_threshold: 0.10
  defer_rate_threshold: 0.25

controller:
  confirmation_ttl_s: 120
  command_ttl_s: 300
  fleet_dispatch_concurrency: 4
  shutdown_enabled: false
```

An admin may omit `fleets` to administer all configured fleets. Viewer and
operator identities must be scoped to named fleets. The controller rejects
unknown configuration keys, unknown fleets/devices, malformed numeric IDs, and
permissive secret-file modes.

The maintained
[controller configuration template](../../deploy/telegram-controller/controller.example.yaml)
contains the complete direct/Spacebridge example.

### Pin device host keys

Pin the key observed during the trusted home-network bring-up. Verify its
fingerprint locally before accepting it; do not use `StrictHostKeyChecking=no`.
The controller uses `HostKeyAlias=<device_id>`, so a known-hosts entry can stay
stable when the direct IP address or Spacebridge endpoint changes.

For Spacebridge, also pin the gateway as `[tunnel.hologram.io]:999`; the outer
Spacebridge SSH service uses port `999`.

For a nonstandard device SSH port, set `metadata.port`. If needed, set
`metadata.host_key_alias` to the exact alias used in the pinned known-hosts
file. Do not use inventory metadata to pass arbitrary SSH options.

## 4. Start and verify on the home network

Start the single controller process under the repository's managed Python
environment:

```bash
uv run --locked python -m scripts.telegram_fleet_controller \
  --config /etc/edgewatch-controller/controller.yaml
```

Run it under the supplied
[systemd deployment](../../deploy/telegram-controller/README.md) or another
supervisor for normal operation. Protect and back up the configuration, SQLite
database, known-hosts file, controller SSH key, Spacebridge identity, and
release catalog together.

From the authorized Telegram chat or fleet topic, verify read-only commands
first:

```text
/device rpi-001 status
/device rpi-001 health
/device rpi-001 network
/device rpi-001 power
/device rpi-001 queue
/device rpi-001 version
/device rpi-001 ota status
/fleet home-pilot status
```

Then verify bounded mutations:

```text
/device rpi-001 sample now
/device rpi-001 sync now
/device rpi-001 mode sleep 3600
/device rpi-001 mode active
/device rpi-001 power eco
/device rpi-001 power continuous
/device rpi-001 alert mute 2026-08-10T18:00:00Z maintenance
/device rpi-001 alert unmute
/device rpi-001 agent restart
```

Alert-mute expiry is strict RFC3339 UTC and must end in `Z`.

Every accepted device command is durably queued; the Telegram update loop does
not wait for SSH. The supervised dispatch worker atomically claims one command,
leases it, and sends targets in bounded concurrent waves. It renews the lease
between waves and checks expiry before starting another wave. After a controller
restart, an expired lease is reclaimed and the same stable per-device command
IDs are replayed safely. The controller writes the terminal command state and a
deduplicated completion reply in one transaction, so recovery cannot create a
second completion reply. Progress and completion replies remain independently
retryable if Telegram delivery fails.

Every fleet command, including read-only commands, freezes its concurrency,
attempt, timeout, backoff, and maximum-duration policy when the command is
accepted. Its command expiry is calculated from that frozen policy. A mutating
fleet command first returns the complete frozen target and exclusion review,
its full SHA-256 hash, the confirmation and command expiries, and the same
bounded dispatch policy. Large reviews are split into Telegram-safe pages;
pagination does not truncate the target list. The controller persists the
ordered targets, exclusions, OTA canaries, arguments, expiries, and dispatch
policy in an immutable SQLite preview before sending any page. Pages are
durably chained: a later page, including the confirmation page, is not eligible
for delivery until its predecessor is marked sent. Confirm it from the same
actor, chat, and topic before its default two-minute expiry:

```text
/fleet home-pilot sync now
/fleet home-pilot confirm <confirmation-id>
```

The confirmation is one-use. It changes the persisted command to queued work;
it does not synchronously contact every device. The controller rechecks
authorization before confirmation queues the dispatch. The worker then uses the
persisted concurrency/attempt/timeout/backoff policy shown in the preview and
does not silently add devices that joined the fleet after preview creation.
Review every page and the full hash before confirming.

`sample now` and `sync now` have a two-step result. `accepted` means the forced
helper durably recorded a pending local request; it does not mean the agent has
sampled or synchronized yet. The agent claims the request, marks it `completed`
only after the sample is durable or the network sync succeeds, and releases a
failed or stale claim for another attempt. The controller keeps an accepted
target pending and resumes it after restart until the same stable command ID
returns `applied` or expires.

For a Spacebridge target, the frozen expiry budget includes each attempt's
tunnel connection timeout, device-command timeout, four-second tunnel cleanup
allowance, retry backoff, and the number of bounded dispatch waves. The worker
does not start another wave after that deadline.

`reboot`, bounded deep sleep, and OTA mutations require `admin`. Deep sleep
requires a duration from 60 seconds through 365 days, for example:

```text
/device rpi-001 power deep-sleep 30m
```

Single-device `shutdown` is also admin-only, remains disabled in controller
configuration by default, and still requires the Pi's local shutdown guard.
Fleet shutdown is not supported.

## 5. Move a device to Spacebridge

After all home checks pass, keep the same `device_id`, controller key, and pinned
device host key. Change only the device transport and Spacebridge connection
configuration:

```yaml
ssh:
  device_key_file: /etc/edgewatch-controller/controller_device_ed25519
  known_hosts_file: /etc/edgewatch-controller/known_hosts
  username: ryne
  spacebridge_identity_file: /etc/edgewatch-controller/spacebridge_rsa
  spacebridge_host: tunnel.hologram.io
  spacebridge_user: htunnel
  spacebridge_port: 999

devices:
  rpi-001:
    fleet: field-pilot
    host: link999999
    transport: spacebridge
    enabled: true
    metadata:
      host_key_alias: rpi-001
```

`devices.<id>.host` is the Spacebridge device link/profile identifier, not the
ICCID, device display name, or Spacebridge gateway. The dispatcher opens a
supervised loopback tunnel, sends the same typed request through the forced
helper, and then removes the tunnel. A failed
tunnel, host-key mismatch, or device timeout must not fall back to an unpinned
connection.

Repeat `status`, `health`, `network`, `queue`, `sample now`, and `sync now` over
Spacebridge before treating the field move as complete.

## Roles and allowed commands

| Role | Allowed operations |
| --- | --- |
| Viewer | `status`, `health`, `network`, `power`, `queue`, `version`, `ota status` |
| Operator | Viewer operations plus `sample now`, `sync now`, `mode active`, `mode sleep [seconds]`, `power continuous`, `power eco`, alert mute/unmute, agent restart |
| Admin | Operator operations plus `reboot`, `power deep-sleep <duration>`, and OTA stage/canary/promote/abort |
| Guarded | Single-device shutdown only when both controller and device guards are enabled |

No role can request arbitrary shell, raw AT/modem commands, file reads or
writes, environment access, credential display, user-supplied artifact URLs,
destructive data operations, or fleet shutdown.

## OTA through Telegram

The controller accepts only a release key or reviewed alias from its local
catalog. Operators cannot provide an artifact URL, digest, signature, key ID,
or shell command in Telegram. The generated catalog initially exposes the exact
Git tag as its release key (for example `v1.2.3`) and contains no alias. Add an
alias only as a separately reviewed catalog change; never rewrite the generated
tag key into a convenience name.

1. Build and publish a signed immutable application bundle and catalog as
   described in [OTA Updates](OTA_UPDATES.md).
2. Put the reviewed catalog on the controller host and update `ota.catalog_file`.
3. Ensure the fleet has at least one explicit canary.
4. Stage every frozen target:

   ```text
   /ota home-pilot stage v1.2.3
   /ota home-pilot confirm <confirmation-id>
   ```

   The preview displays the exact signed release version, Git tag, commit,
   artifact digest, runtime-dependency digest, and manifest identity. Those
   fields are frozen with the command; changing or removing the catalog alias
   after preview does not change what the confirmed deployment dispatches.

5. Read the returned deployment ID and controller state:

   ```text
   /ota home-pilot status
   ```

   Status reads the durable controller snapshot only; it does not fan out a
   status request to every device.

6. On the validated canary only, set `EDGEWATCH_ENABLE_OTA_APPLY=1` in the
   agent environment and restart the agent. Provisioning leaves this flag at
   `0`, which permits signed staging but rejects activation.

7. Apply the configured canary set, then promote exactly one tranche at a time:

   ```text
   /ota home-pilot canary <deployment-id>
   /ota home-pilot confirm <confirmation-id>
   /ota home-pilot promote <deployment-id>
   /ota home-pilot confirm <confirmation-id>
   ```

8. Repeat `promote` only after the prior tranche satisfies the configured
   health, failure, and defer gates.

To stop targets that have not started, use:

```text
/ota home-pilot abort <deployment-id>
/ota home-pilot confirm <confirmation-id>
```

Abort does not claim to roll back devices that already applied a release.
Application bundles are extracted into immutable release directories, activated
with an atomic `current` symlink change, and checked with a fresh agent-owned
readiness receipt. A durable apply journal preserves the original and intended
targets across an abrupt restart until active state and command outcome commit.
Failed readiness restores the previous symlink and restarts the agent.

System-image apply remains disabled until the real-Pi reboot, boot-health, and
bad-release rollback qualification gate passes. Do not represent Telegram
system-image OTA as production-ready before that validation.

## Delivery and recovery semantics

- Telegram update IDs, commands, frozen targets, confirmations, deployments,
  audit records, and outbound replies are persisted in SQLite.
- Every controller command and device target has a stable ID and expiry.
- The device stores an applied-command ledger. Replaying the same ID with the
  same input returns the original result instead of applying it twice.
- `sample now` and `sync now` are first persisted as local requests. An
  `accepted` reply remains durable and resumable until agent completion produces
  `applied`; accepted work is not reported as already applied.
- Transport failures and the explicit `ota_retryable` device result use the
  frozen bounded policy: three attempts per target by default, fixed per-attempt
  timeout, and short exponential backoff, all under the same command ID.
  Transient OTA failures are not committed to the device command ledgers, so a
  retry can perform the pending work. Authorization, validation, pinned-host
  mismatch, compatibility, and signature failures do not retry as if transient.
- A Telegram reply failure does not undo already accepted or applied device
  work; replies have their own durable retry state.
- If the controller is offline, device-to-channel telemetry continues. Telegram
  controls and OTA wait until the controller returns.
- Telegram telemetry still has no independent missing-heartbeat detector. An
  external watcher is required to alert when a device stops posting entirely.

After a controller restart, check its service log and request read-only status
before issuing new mutations. Restore the SQLite database and catalog as one
consistent operational set; do not delete the database merely to clear a stuck
command, because it is the confirmation, audit, and replay boundary.

## Home-to-field acceptance checklist

- [ ] Telemetry and control use different bots and token files.
- [ ] Operator and controller SSH keys use different key material.
- [ ] Control-bot token and private keys are mode `0600` or stricter.
- [ ] Numeric chat/user IDs and optional topic IDs are explicitly allowlisted.
- [ ] Every device host key is verified and pinned under its stable alias.
- [ ] Read-only and mutation commands succeed over direct home-network SSH.
- [ ] Every fleet preview page shows the complete intended frozen targets and
      exclusions, the persisted dispatch policy, and the expected expiry/hash.
- [ ] Sample/sync first show `accepted` when pending and later converge to
      `applied`, including across an agent/controller restart.
- [ ] Unauthorized user, chat, topic, shell text, URL, and stale confirmation
      attempts are rejected.
- [ ] Signed OTA stage succeeds; bad digest/signature/key cases fail closed.
- [ ] Canary apply and application rollback are proven on the home device.
- [ ] Spacebridge status/sample/sync tests pass after moving to LTE.
- [ ] `shutdown_enabled` and system-image apply remain false unless separately
      qualified and explicitly approved.
