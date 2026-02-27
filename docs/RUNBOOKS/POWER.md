# Power Management Runbook (Solar + 12V)

## Purpose

Operate Raspberry Pi nodes safely on solar or 12V irrigation-battery input with:

- input-range monitoring
- sustained-unsustainable-load detection
- automatic saver-mode degradation (`warn + degrade`, no auto-shutdown)
- hybrid disable support:
  - owner/operator logical disable
  - admin one-shot shutdown intent (device-side guard required for OS shutdown)

Baseline power profile:
- 12V lead-acid input path
- recharge via solar controller or well-motor battery charging path

## Scope

Applies to the v1 power path:

- `agent/sensors/backends/rpi_power_i2c.py` (INA219/INA260)
- `agent/power_management.py`
- ingest-driven alert lifecycle (`POWER_INPUT_OUT_OF_RANGE`, `POWER_UNSUSTAINABLE`)

## Prerequisites

Hardware:

- INA219 or INA260 wired on I2C bus
- stable 5V regulator for Pi from the well battery/solar chain
- fuse + surge protection in enclosure

Software:

```bash
sudo apt-get install -y i2c-tools alsa-utils
pip install smbus2
```

## Recommended Sensor Config

Use composite microphone + power profile:

`agent/config/rpi.microphone.sensors.yaml`

Key fields:

- `rpi_power_i2c.sensor`: `ina219` or `ina260`
- `rpi_power_i2c.bus`: typically `1`
- `rpi_power_i2c.address`: typically `0x40`
- `rpi_power_i2c.source_solar_min_v`: default `13.2`

## Policy Defaults (12V lead-acid baseline)

From `contracts/edge_policy/v1.yaml`:

- warn range: `11.8V` to `14.8V`
- critical range: `11.4V` to `15.2V`
- sustainable input: `15W` over `900s`
- battery drop fallback: `0.25V` over `1800s`
- saver cadence: sample `1200s`, heartbeat `1800s`

## Bring-up Checklist

1. Confirm I2C device is visible:

```bash
i2cdetect -y 1
```

2. Start agent with composite config:

```bash
SENSOR_CONFIG_PATH=agent/config/rpi.microphone.sensors.yaml uv run python agent/edgewatch_agent.py
```

3. Verify telemetry includes power keys:

- `power_input_v`, `power_input_a`, `power_input_w`
- `power_source`
- `power_input_out_of_range`, `power_unsustainable`, `power_saver_active`

4. Confirm durable state file exists:

- `edgewatch_power_state_<device_id>.json` (or `EDGEWATCH_POWER_STATE_PATH`)

## Calibration Procedure

1. Measure real bus voltage/current with a trusted multimeter.
2. Compare with telemetry from API/device logs.
3. Adjust:
- sensor configuration (`shunt_ohms`, `source_solar_min_v`)
- policy thresholds (`input_warn_*`, `input_critical_*`, `sustainable_input_w`)
4. Re-run for both:
- solar-charging daytime state
- battery-dominant low-input state

## Alert Validation

1. Force out-of-range condition (controlled test fixture):
- expect `POWER_INPUT_OUT_OF_RANGE` open
- clear condition; expect `POWER_INPUT_OK`

2. Force sustained high load:
- exceed `sustainable_input_w` for at least `unsustainable_window_s`
- expect `POWER_UNSUSTAINABLE`
- reduce load; expect `POWER_SUSTAINABLE`

## Seasonal operations

When field operation is paused:

1. Mute notifications (offseason reason) to suppress delivery noise.
2. Move device to `sleep` mode with a long poll cadence (default 7 days).
3. Use `disabled` only when the site accepts manual restart requirements.
4. Control changes are queued durably for up to 180 days; devices apply on next policy refresh and ack.
5. Admin-only remote shutdown requires explicit local opt-in:
   - `EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=1`
   - otherwise shutdown intent degrades to logical disable only.

## Troubleshooting

- Missing power metrics:
  - check `smbus2` install, I2C wiring, bus/address, and sensor selection.
- Repeated `power_source=unknown`:
  - inspect sensor read failures in agent logs; validate INA connectivity.
- Saver mode always active:
  - input voltage is genuinely unstable or thresholds are too strict for site profile.
- Alert flapping:
  - increase windows (`unsustainable_window_s`, `battery_trend_window_s`) and validate sensor noise floor.
