# ADR: Raspberry Pi zero-touch provisioning via fleet image and first boot

Date: 2026-04-18
Status: Accepted

## Context

EdgeWatch needs a repeatable Raspberry Pi fleet lane that minimizes field work
without placing reusable credentials in an SD-card image. Device identity,
Telegram credentials, and carrier details vary per node. SIM activation,
antenna placement, and power validation remain physical operator tasks.

## Decision

Build `fleet-image-v1` with Raspberry Pi's official `rpi-image-gen`, pinned to a
full upstream commit and an ARM64 Raspberry Pi OS Bookworm base. Production
assembly runs on a capable ARM64 Linux builder because the builder requires a
private mount namespace and elevated mount capability.

The boundary is:

### Baked into the reusable image

- the stable EdgeWatch application and system-site-packages virtual environment
  at `/opt/edgewatch/app`;
- the agent, first-boot bootstrap, and identity-generation systemd units;
- a locked `ryne` operator account with passwordless sudo and public-key-only
  SSH enabled, but no authorized key;
- NetworkManager, ModemManager, ALSA, I2C, and Python runtime dependencies;
- a disabled hardware-watchdog policy that operators may enable only for a
  validated hardware cohort;
- an empty `/boot/firmware/edgewatch/` provisioning directory.

The image contains no device token, Telegram token, LTE credential, Tailscale
key, operator public key, private key, per-device configuration, machine ID,
random seed, or SSH host key. Machine identity and SSH host keys are generated
on first boot.

### Supplied per device on the boot partition

`scripts/rpi_provision_device.py` creates an `edgewatch/` subtree containing:

- `bootstrap.env` with device ID, Telegram destination, LTE and runtime policy;
- a separate mode-`0600` Telegram bot-token file;
- one validated OpenSSH public key as `authorized_key`;
- a non-secret provisioning manifest.

The generator requires `--device-id`, `--telegram-chat-id`, `--bot-token-file`,
`--ssh-public-key-file`, and `--output-dir`. It rejects private-key material and
multi-key files. It defaults to `BOOTSTRAP_SSH_USER=ryne`, the Hologram APN,
continuous power, `SENSOR_BACKEND=none`, SQLite `synchronous=FULL`, batched
Telegram delivery, and a disabled cellular watchdog.

The boot partition's FAT filesystem does not enforce Unix mode bits. The
generator's local `0600` mode reduces accidental exposure on filesystems that
honor it, but physical custody is the pre-boot security boundary. First boot
imports the token into root-owned storage and durably removes both credential
staging copies before recording completion.

### Completed on first boot

The retrying first-boot service:

1. imports the Telegram token to `/var/lib/edgewatch/` and installs the operator
   public key as `ryne`'s `authorized_keys`;
2. sets the hostname from the device ID;
3. installs and starts the agent service;
4. creates and activates the LTE profile;
5. health-gates completion on the agent, LTE connection, and a Telegram
   provisioning receipt;
6. durably removes the consumed Telegram token and public-key staging files
   from the boot partition and redacts consumed credentials from `bootstrap.env`;
7. records the bootstrap report;
8. writes the completion marker last.

An optional downloaded application bundle is verified before extraction and
activated by an atomic directory replacement with restoration on swap failure.
The default fleet-image flow uses the already-baked application and does not
require a first-boot application download.

## Consequences

- One signed/checksummed image can be reused while each card retains unique
  identity and credentials.
- Failed first boot remains retryable and does not mark the device complete
  before network and delivery health are proven.
- Continuous power is the bring-up posture; `eco` is appropriate after a soak.
  True `deep_sleep` depends on supported RTC or supervisor hardware.
- Telegram batching reduces radio and Bot API overhead. Routine telemetry uses
  at-least-once gzip JSONL batches; startup and alert traffic flushes
  immediately.
- Persisted `wwan` transmit counters are preferred for daily byte-budget
  enforcement when available.
- Telegram-exclusive nodes do not receive EdgeWatch API policy/control, API OTA
  reporting, server-side alert lifecycle, or dashboard storage. A separately
  configured external controller may provide the narrower typed control and
  signed application-bundle OTA path defined by
  [ADR-20260809](ADR-20260809-telegram-fleet-control.md); that capability does
  not come from the telemetry bot or transport.
- Telegram alone does not generate an alarm when a node stops sending, and a
  shared bot token proves bot authorization rather than physical-device
  provenance. Fleet deployments that require those properties need distinct
  bot trust boundaries plus an external heartbeat watcher, or API transport.
- SIM activation, SIM PIN state, antennas, and input-power validation remain
  operator responsibilities.

## Alternatives considered

- **Bake secrets into the image:** rejected because a reusable artifact must not
  expose or reuse device credentials.
- **Clone/install the application on every first boot:** rejected as the default
  because it adds a network dependency before the stable agent can start.
- **Manual SSH provisioning:** retained as a development fallback, not the fleet
  default, because it is slow and inconsistent at scale.

## Validation

The lane is accepted when contract tests prove that the image inputs are pinned
and secret-free, provisioning tests prove unique protected device bundles, and
first-boot tests prove retry, token consumption, hostname, LTE, agent, Telegram,
health-gate, and atomic activation behavior.
