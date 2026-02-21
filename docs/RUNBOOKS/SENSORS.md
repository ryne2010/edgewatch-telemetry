# Sensors runbook (edge node bring-up)

This runbook is a practical checklist for bringing up a new EdgeWatch node with
real sensors on a Raspberry Pi.

Scope (planned/target):
- temp + humidity (I2C)
- pressures + levels (ADC)
- oil life % (runtime-derived; manual reset)

> Note: the "real sensor" implementation is tracked by `docs/TASKS/11-edge-sensor-suite.md`.
> This runbook is written ahead of time so field bring-up has a target procedure.

## 1) Pre-flight checklist

- Raspberry Pi OS installed and booted successfully
- Power is stable (Pi + modem + cameras can brown out under load)
- Enclosure + cable glands installed (strain relief matters)

## 2) Enable and validate I2C

1. Enable I2C in raspi-config (or via config file).
2. Install I2C tooling and Python runtime:

```bash
sudo apt-get update
sudo apt-get install -y i2c-tools python3-pip
pip install smbus2
```

3. Wire BME280 (3.3V only):
   - Pi pin 1 (3V3) -> BME280 VIN
   - Pi pin 6 (GND) -> BME280 GND
   - Pi pin 3 (GPIO2/SDA) -> BME280 SDA
   - Pi pin 5 (GPIO3/SCL) -> BME280 SCL
4. Scan the bus (typical bus is `1` on modern Pi boards):

```bash
i2cdetect -y 1
```

Expected:
- BME280 should appear at `0x76` or `0x77` (strap dependent)
- ADS1115 should appear (commonly 0x48 by default)

If nothing shows up:
- confirm SDA/SCL wiring
- confirm pull-ups
- confirm the sensor is powered (3.3V)

### BME280 backend sanity check

Run the agent with the I2C backend and verify `temperature_c` and `humidity_pct` are present in telemetry:

```bash
SENSOR_BACKEND=rpi_i2c uv run python agent/edgewatch_agent.py
```

Optional explicit YAML:

```yaml
backend: rpi_i2c
rpi_i2c:
  sensor: bme280
  bus: 1
  address: 0x76
  warning_interval_s: 300
```

## 3) Validate analog channels (ADS1115)

- Confirm ADS1115 reads stable voltages (use a known reference voltage first).
- Only then connect pressure / level channels.

### 4–20 mA conditioning sanity check

If you convert current → voltage using a resistor:

- Ensure the voltage stays **within the ADC input range** (0–3.3V for a 3.3V system).
- For a 165 Ω resistor:
  - 4 mA ≈ 0.66 V
  - 20 mA ≈ 3.30 V

Before connecting a sensor, verify:
- loop supply voltage is correct (often 12–24V)
- grounds are correct (or use isolation hardware)

## 4) Calibrate scaling constants

The edge agent should convert raw ADC readings into contract units:

- `water_pressure_psi`
- `oil_pressure_psi`
- `oil_level_pct`
- `drip_oil_level_pct`

Calibration plan:
- record raw voltage at known points (ex: 0 psi, 50 psi, 100 psi)
- compute slope/intercept
- store constants in the sensor config file (`agent/config/...`)

## 5) Validate EdgeWatch end-to-end

Once sensors are reading locally:

```bash
make up
make demo-device
make simulate
```

Then open the UI and verify:
- metrics arrive and chart correctly
- alerts trigger/recover when you apply controlled input changes

## 6) Oil life reset procedure (planned)

Oil life is runtime-derived and should be reset after maintenance.

Planned behavior (see ADR):
- device stores `oil_life_reset_at` and `oil_life_runtime_s` durably
- a local reset command sets oil life back to ~100%

Tracking:
- `docs/DECISIONS/ADR-20260220-oil-life-manual-reset.md`
- `docs/TASKS/11-edge-sensor-suite.md`

## 7) Field diagnostics to collect

If sensor values look wrong, capture:
- raw I2C scan results
- raw ADC channel voltages
- scaling constants used
- agent logs (sensor read errors, None metrics)
- a photo of wiring (seriously: it saves time)
