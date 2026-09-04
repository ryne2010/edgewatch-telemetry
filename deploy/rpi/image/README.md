# EdgeWatch fleet-image-v1

This lane builds a secret-free, ARM64 Raspberry Pi OS Bookworm Lite-class image
with Raspberry Pi's official
[`rpi-image-gen`](https://github.com/raspberrypi/rpi-image-gen). The builder is
pinned to a full upstream commit in `pins.env`; the OS suite, architecture, and
default device layer are pinned there as well.

The image contains:

- the EdgeWatch agent, contracts, OTA helpers, and first-boot bootstrap;
- Debian-managed Python runtime dependencies, NetworkManager, ModemManager,
  ALSA tools, and I2C support;
- enabled first-boot and agent-provisioning services;
- an opt-in systemd hardware-watchdog policy under `/usr/share/edgewatch/`;
- an empty `/boot/firmware/edgewatch/` provisioning directory;
- no device token, Telegram token, LTE credential, Tailscale key, operator or
  controller SSH public key, OTA trust anchor, SSH host key, machine ID, or
  per-device configuration.

The stock image does not install Tailscale. Hologram Spacebridge can reach its
public-key-only OpenSSH service over the cellular link. If a customized image
adds Tailscale, first boot treats requested enrollment as a required health
gate; it will remain retryable rather than silently completing when the CLI or
tailnet connection is unavailable.

The watchdog drop-in is deliberately shipped with a `.disabled` suffix because
hardware support varies across fleet boards. After validating `/dev/watchdog` on
a hardware cohort, copy it to
`/etc/systemd/system.conf.d/90-edgewatch-watchdog.conf` and run
`systemctl daemon-reexec`. It configures a 30-second runtime watchdog and a
two-minute reboot watchdog.

`rpi-image-gen` removes package-generated SSH host keys. The EdgeWatch layer
also empties the machine ID, removes random seeds and host keys, then regenerates
machine identity and SSH host keys under `ConditionFirstBoot=yes`. The static
hostname is intentionally non-unique until fleet provisioning assigns the
device's operational identity.

## Build

The supported production builder is a dedicated native ARM64 Debian Bookworm or
Raspberry Pi OS host. The upstream tool uses a private mount namespace and needs
`CAP_SYS_ADMIN` or an equivalent host capability. Ordinary pull-request checks
therefore validate this lane's contract without running the privileged image
assembly. The manual GitHub workflow targets a labelled ARM64 self-hosted runner.

```bash
deploy/rpi/image/build.sh --install-deps --device rpizero2w
```

Supported device layers are `rpizero2w`, `rpi3`, `rpi4`, and `rpi5`. Each uses
the official ARM64 Raspberry Pi kernel/firmware layer appropriate to the board.
Pass `--image-version` for a human release identifier. Otherwise the version is
derived from the EdgeWatch source commit.

The output directory contains:

- `*.img.xz` — flashable compressed SD-card image;
- `*.img.xz.sha256` — SHA-256 verification file;
- `*.manifest.json` — image, source, builder, board, and reproducibility inputs.

The application archive is created from the selected Git commit, not from
untracked files. Build from a committed release revision so the wrapper, image
layer, first-boot service, and archived application describe the same reviewed
source. Both the source commit timestamp and single-threaded XZ settings are
fixed. Package resolution remains tied to the pinned Raspberry Pi OS Bookworm
suite at build time. Retain the emitted manifest with every promoted artifact
and rebuild intentionally for security updates. This wrapper does not currently
export or attest an SBOM, so the manifest must not be represented as one.

## Provision a device

1. Verify the `.sha256` file and flash the same image to each SD card.
2. Generate the complete role-aware `edgewatch/` boot subtree with
   `make rpi-provision RPI_PROFILE=...`; do not hand-edit `bootstrap.env`.
3. Copy the generated `edgewatch/` directory to `/boot/firmware/edgewatch/` on
   that card's boot partition. Never commit or reuse it across devices.
4. Insert the SIM and boot. The one-shot service installs the device-specific
   environment and the services required by its image profile.

The baked application root is `/opt/edgewatch/app`, with
`/opt/edgewatch/current` as the stable runtime symlink used by application OTA.
Application OTA is intentionally code-only: the signed
`agent/requirements.txt` fingerprint must match the installed runtime. Releases
that change Python dependencies require a newly qualified base/system image.
`RPI_PROFILE=standalone` provisions the original direct-to-Telegram agent.
`RPI_PROFILE=gateway` provisions the telemetry gateway, LoRaWAN registry/radio
contracts, and LTE power-window configuration; its controller private key is
generated later by guided control initialization and never enters the boot
bundle. `RPI_PROFILE=camera-satellite` provisions local camera/model runtime,
the required initial signed model, the gateway controller public key, and no
Telegram, API, LTE, or cloud secret.
See the exact commands in
[`LOW_POWER_CAMERA_SUBFLEET.md`](../../../docs/RUNBOOKS/LOW_POWER_CAMERA_SUBFLEET.md).

First boot installs the operator key when provided, constrains the controller
key to the root-owned typed helper, installs OTA/model public trust anchors,
imports private inputs into protected persistent storage, and removes consumed
staging copies durably before writing the completion marker. No signing or SSH
private key and no Telegram control-bot token is placed on a card.

On Raspberry Pi, signed OTA stage/apply also requires fresh durable power-state
evidence. On a no-sensor device, `vcgencmd get_throttled` must return
`throttled=0x0`;
sticky undervoltage or throttling flags block the update until the power issue is
corrected and a clean boot is validated.

The boot partition is FAT, so the generator's local `0600` mode is advisory and
is not the secret security boundary. Keep provisioned cards physically
controlled until first boot imports the token into root-owned storage and
consumes the staging copies.

Telegram-only operation is intentionally a field-validation lane. Telegram does
not independently detect a device that stops sending heartbeats, and a bot token
shared across devices cannot prove which physical device originated a post.
Use a distinct bot per trust boundary and add an external heartbeat monitor when
those properties are required.

An external Telegram fleet controller can provide typed control and signed
application-bundle OTA without the EdgeWatch API. It uses a separate control bot
and the forced controller SSH key over direct SSH or Hologram Spacebridge. It is
not live until its configuration, numeric RBAC, pinned host keys, credentials,
release catalog, and supervisor have been installed and verified; see
[`docs/RUNBOOKS/TELEGRAM_FLEET_CONTROL.md`](../../../docs/RUNBOOKS/TELEGRAM_FLEET_CONTROL.md).
