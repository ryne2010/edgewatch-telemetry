# BOM: Raspberry Pi Microphone + Power (v1)

This bill of materials is the field-first hardware list for the current EdgeWatch
v1 profile:

- microphone + power telemetry only
- 10-minute default poll (`600s`)
- offline microphone alert threshold default (`60 dB`) with sustain logic
- one SIM per device (no hub in v1)

Your starting inventory assumption:

- you already have Raspberry Pi 4B boards
- you already have small 12V lead-acid batteries and well motor 12V batteries

## Locked v1 standard stack

This is the recommended production-standard hardware stack for the current
EdgeWatch branch:

1. Compute: existing `Raspberry Pi 4B`
2. Cellular modem: `Sixfab 4G/LTE Modem Kit`
3. Modem SKU: `Telit LE910C4-NF (North America)`
4. SIM/provider: `Hologram` physical SIM
5. Audio input: `NowTH USB lavalier microphone` (`B0929CQSX4`) on a short external protected mount
6. Power telemetry: `INA260`
7. Power input: fused `12V -> 5V` buck converter from well battery or local SLA

Why this is locked for v1:

1. It matches the current software/runtime model:
   - Raspberry Pi OS
   - Python agent
   - `systemd`
   - local SQLite buffer/state
   - Linux modem tooling (`ModemManager`, `NetworkManager`)
   - OTA/reporting flow already implemented in repo
2. `Telit LE910C4-NF` is the preferred North America modem option.
3. `Hologram` pricing is favorable for the expected mic+power telemetry profile.
4. `NowTH USB lavalier microphone` (`B0929CQSX4`) avoids GPIO/HAT conflicts with the Sixfab modem stack
   and is a better fit for the short external protected mount because it already includes a
   `6.56 ft / 2 m` cable.
5. The standard pilot mount is a short external protected microphone mount rather than
   placing the mic loose inside the sealed enclosure.
6. `eco` runtime power mode is the first recommended optimization; true `deep_sleep` remains optional per node.

Platform note:

1. `Raspberry Pi 4B` and `Raspberry Pi 5` are the locked standard SBCs for this project.
2. `Raspberry Pi Zero 2 W` is not part of the standard build and would require a separate,
   more constrained Linux hardware profile.
3. `Raspberry Pi Pico` is not supported by the current EdgeWatch runtime and would require a
   separate microcontroller firmware product line.

## Qty 1 pilot checkout list

This list assumes you already own:

- `1x Raspberry Pi 4B`
- `1x 12V battery source`

Buy now:

1. `1x` Sixfab 4G/LTE Modem Kit for Raspberry Pi
   - choose modem option: `Telit LE910C4-NF (North America)`
   - target cost: `~$125`
2. `1x` Hologram physical SIM
   - target cost: `~$3`
3. `1x` Samsung PRO Endurance `128GB` microSD
   - target cost: `~$27`
4. `1x` `NowTH USB lavalier microphone` (`B0929CQSX4`)
   - target cost: `~$10-15`
5. `1x` short USB extension cable for microphone mount (optional only if the included mic lead is not enough)
   - target cost: `~$8-15`
6. `1x` small protected microphone hood/bracket or sheltered mount hardware
   - target cost: `~$8-20`
7. `1x` INA260 current/voltage/power monitor
   - target cost: `~$10`
8. `1x` waterproof `12V -> 5V` buck converter, `>=5A`
   - target cost: `~$10-20`
9. `1x` weatherproof enclosure, about `8x6x4 in`
   - target cost: `~$40-120`
10. `1x` cable gland kit
   - target cost: `~$10-20`
11. `1x` fuse/wiring pack
   - inline fuse holder
   - `5A` and `7.5A` blade fuses
   - ring terminals, ferrules, heat-shrink, wire
   - target cost: `~$15-35`

Optional for standalone solar-backed nodes:

1. `1x` `Newpowa 50W` 12V monocrystalline panel
   - locked recommended solar panel for standalone v1 installs
   - target cost: `~$76`
2. `1x` `Newpowa 10A PWM` charge controller
   - locked recommended low-cost controller for the `50W` panel
   - target cost: `~$22`
3. `1x` MC4 cable/connectors set
   - target cost: `~$15-40`

Pilot-node spend estimate:

1. Core node using your existing Pi and battery: `~$255-365` before taxes/shipping
2. With locked solar add-on: `~$368-503` before taxes/shipping

## Per-node BOM (incremental spend)

### Required

1. Storage
- High-endurance microSD, 64-128GB
- Target: `$18-35`

2. Microphone
- `NowTH USB lavalier microphone` (`B0929CQSX4`) on a short external protected mount
- Do not rely on a loose USB mic inside a sealed enclosure for threshold-based monitoring
- Target: `$10-15`

3. Microphone mounting accessories
- Short USB extension cable, small hood/bracket, wind protection, strain relief
- Target: `$8-20`

4. Power telemetry sensor
- INA219 (budget) or INA260 (higher current range/integration)
- Target: `$3-20`

5. 12V to 5V conversion
- Waterproof buck converter, `12V -> 5V`, `>=5A` continuous
- Target: `$10-20`

6. Protection + wiring
- Inline fuse holder + blade fuses (5A/7.5A), ring terminals, heat-shrink,
  ferrules, wire, strain relief
- Target: `$15-35`

7. Cellular modem (data SIM)
- USB LTE modem or LTE HAT kit
- Target: `$60-140`

8. External antenna(s)
- LTE antenna (and extension cable if enclosure mount requires it)
- Target: `$15-40`

9. Weatherproof enclosure
- Polycarbonate or metal enclosure, roughly `8x6x4 in` minimum
- Target: `$40-120`

10. Cable glands + mounting hardware
- IP67 cable glands and mounting plate/standoffs
- Target: `$10-30`

### Optional but recommended

1. Solar maintenance charging path (for standalone battery nodes)
- `Newpowa 50W` 12V panel: `~$76`
- `Newpowa 10A PWM` controller: `~$22`
- MC4 cable + branch/connectors: `$15-40`

2. Brownout protection
- Low-voltage disconnect module or UPS-capable path
- Target: `$20-60`

3. Better thermal management
- Heatsink/fan kit if enclosure heat is high
- Target: `$10-20`

## Estimated per-node cost

Using your existing Pi 4B and batteries:

1. Battery-fed node (no solar panel): about `$180-440` + SIM plan
2. Battery + solar top-off node: about `$270-680` + SIM plan

If you buy new compute:

1. Add Raspberry Pi 4B board cost (market-variable)
2. Add Raspberry Pi 5 only if you need more local compute for media/AI workflows

## Amazon quick links (search-first)

Use these as direct purchase shortcuts:

1. High-endurance microSD:
   - `https://www.amazon.com/s?k=Samsung+PRO+Endurance+128GB+microSD`
2. Microphone options:
   - `https://www.amazon.com/s?k=ReSpeaker+2-Mics+Pi+HAT`
   - `https://www.amazon.com/s?k=USB+microphone+for+raspberry+pi`
3. Power telemetry modules:
   - `https://www.amazon.com/s?k=INA219+current+sensor+module`
   - `https://www.amazon.com/s?k=INA260+current+sensor+module`
4. Cellular modem options:
   - `https://www.amazon.com/s?k=SIM7600G-H+Raspberry+Pi`
   - `https://www.amazon.com/s?k=Sixfab+LTE+Raspberry+Pi`
5. 12V to 5V conversion:
   - `https://www.amazon.com/s?k=12V+to+5V+5A+buck+converter+waterproof`
6. Enclosure + install:
   - `https://www.amazon.com/s?k=NEMA+4X+polycarbonate+enclosure+8x6x4`
   - `https://www.amazon.com/s?k=IP67+cable+gland+kit`
7. Solar top-off path:
   - `https://www.amazon.com/s?k=Renogy+50W+12V+solar+panel`
   - `https://www.amazon.com/s?k=Renogy+Wanderer+10A+charge+controller`

## Data plan sizing (mic + power profile)

At 10-minute telemetry cadence with ETag policy pulls and no continuous media:

1. Typical steady state: `~80-250 MB/month` per node
2. Weak signal + retries: `~250-700 MB/month` per node
3. OTA updates: add burst usage per rollout window (depends on release delta)

Practical guidance:

1. `1 GB/month` can work for steady telemetry + careful OTA cadence
2. If coverage is weak or OTA cadence is frequent, `2-3 GB/month` is safer

## Solar sizing guidance

`50W` is not a hard requirement in all cases.

Use this rule:

1. If the node is powered from the well battery and that battery is already kept charged by the well system,
   separate solar is optional and often unnecessary.
2. If solar is only there to float-maintain a small battery during offseason or sleep-heavy operation,
   `20W` can be enough.
3. If the node must run year-round from its own dedicated battery while the Pi and LTE modem stay on,
   `50W` is the safer default.
4. If the node is configured for true `deep_sleep`, smaller panels become more realistic because the Pi is not fully on between samples.

Sizing rationale:

1. A Pi 4B + LTE modem node is a continuous load, not a motion-triggered or deep-sleep sensor.
2. Real panel output is well below nameplate after controller, battery, temperature, and weather losses.
3. `20W` or `30W` works only when the energy budget is very favorable or the node is using `eco`/`deep_sleep`.

## Microphone mounting guidance

For the locked Adafruit enclosure path:

1. Do not assume a USB mic placed loose inside the sealed box will represent outside sound reliably.
2. Standardize on a short external protected mic mount.
3. Keep the USB run short and protected with strain relief and a drip loop.
4. Mount the mic under a small hood or downward-facing sheltered bracket to reduce rain and direct sun exposure.
5. Use normal cable-gland penetrations only; do not add a dedicated acoustic vent path to the enclosure for the pilot build.

## BYO carrier requirements (must confirm before purchase)

1. APN and any credentials
2. Data-only SIM activation state
3. IMEI allowlist policy
4. Roaming/throttling policy
5. CGNAT and idle timeout behavior

See:

- `docs/RUNBOOKS/CELLULAR.md`
- `docs/TUTORIALS/BYO_CELLULAR_PROVIDER_CHECKLIST.md`

## Fast launch sequence

1. Flash + preload SD:
   - `docs/TUTORIALS/RPI_FLASH_ASSEMBLE_LAUNCH_CHECKLIST.md`
2. Agent deployment details:
   - `docs/DEPLOY_RPI.md`
3. First-boot minimal flow:
   - `docs/TUTORIALS/RPI_ZERO_TOUCH_BOOTSTRAP.md`
