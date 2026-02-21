# Hardware recommendations (EdgeWatch node)

This repo is software-first, but the intended deployment target is an **edge node**
installed near remote equipment (pumps/wells/engines) with intermittent connectivity.

This document proposes a **practical, readily-available hardware bill of materials**
that matches the requested scope:

- temperature
- humidity
- oil pressure (0–100 psi)
- oil level (%)
- oil life (%) (manual reset; runtime-derived)
- drip oil level (%)
- water pressure (0–100 psi)
- up to 4 cameras (photo + short video; one camera active at a time)
- LTE data SIM connectivity

> Note: exact part numbers evolve quickly. Treat this as a "known good" starting
> point; adjust to your environmental constraints (temperature, cable length,
> lightning/surge exposure, hazardous area ratings).

## Decisions captured as ADRs

- **Camera strategy:** switched multi-camera capture (one camera active at a time)  
  See `docs/DECISIONS/ADR-20260220-camera-switching.md`.
- **Pressure ranges:** default to **0–100 psi** for water and oil  
  See `docs/DECISIONS/ADR-20260220-pressure-range.md`.
- **Oil life model:** runtime-derived with **manual reset**  
  See `docs/DECISIONS/ADR-20260220-oil-life-manual-reset.md`.

## Recommended base platform

### Compute

- **Raspberry Pi 5 (8GB)** for best IO + headroom
  - strong CPU for image processing + compression
  - modern camera stack (libcamera)
  - PCIe for future NVMe storage

If you need lower power/cost:

- **Raspberry Pi 4 (4GB/8GB)** still works well for telemetry + periodic images.

### Storage

- Industrial microSD (high endurance)
- Optional: NVMe (Pi 5) if you expect lots of media buffering while offline

### Enclosure and power

- IP65+ outdoor enclosure (DIN rail is nice)
- 12V/24V → 5V buck converter sized for Pi + peripherals
- Fusing + surge protection (especially near pumps / long sensor runs)
- Optional: UPS HAT or small 12V SLA/LiFePO4 backup

## Suggested bill of materials (per node)

This list is intentionally "boring and available" — you can swap vendors, but keep
interfaces consistent (I2C + 4–20 mA/voltage into an ADC).

### Core

- Raspberry Pi 5 (8GB)
- Official power supply (or regulated 5V rail sized for Pi + modem + cameras)
- High-endurance microSD (or NVMe for heavy media buffering)
- IP65+ enclosure + cable glands + strain relief
- Heatsink/fan (Pi 5) for hot environments

### Telemetry sensors

Digital (I2C):

- Temp/humidity: BME280 (I2C) or SHT31 (I2C)

Analog (ADC):

- ADC: ADS1115 (I2C, 16-bit)

Industrial analog sensors (recommended for long runs):

- Water pressure: **0–100 psi**, 4–20 mA (2-wire)
- Oil pressure: **0–100 psi**, 4–20 mA (2-wire)
- Oil tank level: continuous level transmitter, 4–20 mA
  - choose float/capacitive/ultrasonic based on tank geometry and fluid

Drip oiler (small reservoir):

- Load cell + HX711 amplifier board (weight-based level)

### Cameras

- Camera modules: Raspberry Pi Camera Module 3 (standard or wide; NoIR optional)
- Multi-camera adapter: Arducam Multi Camera Adapter (4x CSI; **switched**)
  - design assumption: **one camera active at a time**

### Cellular

- Sixfab LTE Base HAT + mini PCIe LTE modem module (Quectel EC25/EG25 class)
- LTE antenna(s) (and GNSS antenna if your module supports it)
- Optional: external router if you need Wi-Fi AP sharing or stronger LTE management

## Sensors

### Temperature + humidity

**I2C sensor (digital)**

- BME280 (temp/humidity/pressure) *or* SHT31 (temp/humidity)
- Connect via I2C; minimal wiring; easy calibration

### Pressure sensors (water + oil)

For field wiring reliability, prefer **industrial transducers**.

Default assumption:

- **0–100 psi**
- **4–20 mA** output (2-wire)

**Why 4–20 mA?** Better noise immunity and cable-length tolerance than raw voltage.

### Level sensors (oil + drip oil)

Options depend on tank geometry and required accuracy:

- Oil tank level: continuous level transmitter (often 4–20 mA)
- Drip oiler: smallest reliable option is usually:
  - load cell (weight-based) + HX711 amplifier
  - or a float switch (binary) if "low" is sufficient

### Oil life (%)

Oil life is treated as a **derived value** in this repo:

- Oil life decreases as equipment runtime accumulates.
- A **manual reset** returns oil life to ~100% after maintenance.

See `docs/DECISIONS/ADR-20260220-oil-life-manual-reset.md` for the specific model.

### ADC / input conditioning

Raspberry Pi has no analog inputs.

Recommended:

- ADS1115 (I2C, 16-bit ADC) for analog voltage inputs

If using **4–20 mA sensors**, convert current → voltage with a precision resistor.

A practical mapping for 3.3V ADC inputs:

- Use **165 Ω** (0.1% preferred, ≥0.25W) to map:
  - 4 mA → 0.66 V
  - 20 mA → 3.30 V

> Keep wiring safe: 2-wire transmitters often require a 12–24V loop supply.
> Plan grounding, fusing, and (if needed) isolation for noisy environments.

## Cameras

Target: **up to 4 cameras per node** (photo + short clips).

### Approach A (recommended): CSI cameras + switched multi-camera adapter

- Use 4 Raspberry Pi Camera Module 3 units with an Arducam (or similar) multi-camera adapter
- Pros: better image quality + low CPU overhead
- Cons: adapter is **switched** (one active camera at a time)
  - great for periodic snapshots
  - for video: one stream at a time

### Approach B: USB cameras (optional backend)

- Use up to 4 UVC USB cameras
- Pros: straightforward; can capture concurrently (within bandwidth)
- Cons: higher bandwidth/power; more cables; more tuning

## Cellular connectivity

Goal: "data SIM" internet without relying on nearby Wi‑Fi.

Recommended patterns:

- LTE modem HAT for Raspberry Pi (Quectel-based) **or** a USB LTE modem
- Use ModemManager / NetworkManager on Raspberry Pi OS for connection management
- Expose `signal_rssi_dbm` (already supported) and optionally add:
  - `cellular_rsrp_dbm`, `cellular_rsrq_db`, `cellular_sinr_db`
  - data usage counters per day (for cost hygiene)

See runbook: `docs/RUNBOOKS/CELLULAR.md`.

## Wiring and calibration notes

- Prefer shielded cable and common grounding practices for long runs.
- Keep analog sensor lines away from motor power.
- Document per install:
  - sensor range and units
  - scaling constants (e.g., 4–20 mA → psi)
  - tank geometry for level conversion
- Consider adding "sensor health" metrics:
  - open/short detection
  - out-of-range values

## Software mapping

Contracted metric keys live in:

- `contracts/telemetry/v1.yaml`

Edge cadence/delta thresholds live in:

- `contracts/edge_policy/v1.yaml`

Implementation work is tracked in:

- `docs/TASKS/11-edge-sensor-suite.md`
- `docs/TASKS/12-camera-capture-upload.md`
- `docs/TASKS/13-cellular-connectivity.md`
