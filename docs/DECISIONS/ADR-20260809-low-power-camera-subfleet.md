# ADR: Low-power camera sub-fleet

- Status: Accepted
- Date: 2026-08-09

## Context

An always-awake Raspberry Pi 4 and USB LTE modem consume too much energy for a
small solar field station. Camera satellites also need local video/audio
inference and evidence retention, but routine media must not traverse LTE.
Telegram remains the human control and telemetry surface during the pilot.

## Decision

EdgeWatch will use a star-of-stars field topology:

- One Pi 4 gateway runs the private Telegram controller and a local ChirpStack
  LoRaWAN network. The Pi and a genuine SX1302/SX1303 concentrator remain on.
- The gateway opens one bounded LTE window per hour and on an authenticated
  LoRa alert. Production mode is valid only when carrier-approved hardware
  electrically removes modem power between windows. Application batching alone
  must not be described as LTE power cycling.
- Three to five camera satellites use an always-on low-power MCU sentinel. The
  MCU switches the Pi Zero 2 W, camera, and maintenance radio. Linux performs a
  clean shutdown before the MCU removes power.
- Satellites use US915 LoRaWAN Class A for compact events, metrics, health, and
  authenticated maintenance-wake requests. LoRaWAN never carries media, SSH,
  application/model artifacts, or arbitrary commands.
- Bulk maintenance uses a switched, private, point-to-multipoint WLAN with
  pinned SSH host keys. A LoRa wake must complete before the controller attempts
  maintenance SSH.

Telegram telemetry and control remain separate security domains. The existing
telemetry bot/channel is unchanged. A different bot and private group handle
commands. The gateway generates the controller Ed25519 private key locally; it
never enters a boot bundle or leaves the gateway. Registration authorizes one
numeric Telegram user ID as administrator and records the numeric private-group
chat ID. Usernames and display names are never authorization identities.

The camera lane uses a bounded FFmpeg RTSP backend and one-thread,
fully-quantized INT8 LiteRT inference. Vision and audio scores are fused
deterministically, with `unknown` preferred over a low-confidence guess. Models
are trained off-device. Event evidence and one daily still remain in a bounded
30-day local ring. No routine media upload is permitted.

Application and model releases are independent signed artifacts. Native
FFmpeg/LiteRT dependencies belong to the golden/system image. The gateway
downloads each artifact once, caches it by digest, and distributes it over the
maintenance WLAN. Model bundles include models, labels, preprocessing contract,
thresholds, compatibility, and a known-answer vector. Canary and staged rollout
must restore the prior active bundle when readiness fails. MCU/radio firmware is
manual during the pilot.

Human-facing Telegram text may contain at most one severity/state emoji and one
subsystem emoji. Machine-readable telemetry and command envelopes remain ASCII
JSON/binary contracts without emoji.

## Safety and operational boundaries

- Hardware-specific modem switching and MCU power control are explicit adapter
  boundaries. The repository supplies fixed service contracts and qualification
  tools, not an unreviewed GPIO polarity or USB back-power assumption.
- Gateway provisioning starts LTE scheduling in `observe` mode. Operators may
  select electrical `systemd` mode only after installing and validating the
  carrier-specific on/off hooks.
- A managed external dead-man endpoint receives an hourly gateway check-in. A
  2 hour 15 minute grace period is configured at that service. Without an
  external observer, a dead gateway cannot alert through Telegram.
- Dangerous device actions remain typed, idempotent, role-gated, expiring, and
  confirmation-gated. There is no arbitrary shell command surface.
- Secrets, OTAA keys, RTSP credentials, Telegram authorization, and controller
  private keys are never baked into the reusable image.

## Qualification gates

Before production rollout:

1. Measure Pi-only, LTE registered-idle, LTE transfer, and LTE-electrically-off
   energy with an inline meter. The gateway no-camera average must be at most
   5 W before solar sizing.
2. Complete 100 modem power/attach cycles without Pi undervoltage.
3. Qualify one local-only H.264+audio IP camera over 100 power cycles, with at
   least 99 successful starts, first media within 90 seconds, and recovery from
   a 24-hour interruption.
4. Run inference in shadow mode for 14 days. Alerts require at least 95% held-out
   precision and at most one false alert per device per day.
5. Demonstrate at least 99% eventual delivery over 1,000 LoRa uplinks at the
   intended site, P95 event-to-Telegram latency below five minutes across 50
   trials, signed interrupted OTA recovery, and a seven-day no-solar battery
   run ending with at least 20% reserve.

Solar and storage hardware sizing must use measured P95 daily energy, cold
derating, conversion efficiency, and the accepted depth of discharge. The pilot
uses LiFePO4 only with low-temperature charge blocking or controlled heating.

## Consequences

The topology substantially reduces satellite and LTE duty cycle, but adds a
gateway availability dependency, local radio infrastructure, MCU firmware, and
two maintenance paths. One-hour normal control latency is accepted. Event alerts
open LTE immediately and retain a five-minute latency objective. Camera choice,
radio range, electrical modem isolation, and solar capacity remain hardware
qualification results rather than software claims.
