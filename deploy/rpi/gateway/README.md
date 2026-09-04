# Gateway LTE electrical-power integration

The controller's hourly network scheduler is hardware-independent. It calls
only the fixed `edgewatch-lte-power-on.service` and
`edgewatch-lte-power-off.service` units. These template units deliberately do
not include a GPIO, USB-hub, or carrier command: the correct transition depends
on the selected modem carrier, load switch, discharge path, and back-feed
protection.

Before changing `EDGEWATCH_GATEWAY_LTE_POWER_MODE` from `observe` to `systemd`:

1. Install root-owned, non-writable executables at
   `/usr/local/libexec/edgewatch-lte-power-on` and
   `/usr/local/libexec/edgewatch-lte-power-off` using the carrier-approved
   design. They must use fixed arguments and must not evaluate shell input.
2. Prove with an inline meter that the off transition removes modem power, not
   merely the data session, and that it does not back-feed the Pi.
3. Run 100 complete power, attach, transfer, detach, and power-off cycles. Every
   cycle must attach successfully and `vcgencmd get_throttled` must remain
   `0x0` after a fresh boot.
4. Install these two systemd units and the exact controller sudo rules. Never
   grant the controller generic `systemctl` or shell access.

`observe` mode is useful for a timing trial but must never be reported as an
energy-saving or electrically duty-cycled result.

`EDGEWATCH_GATEWAY_LTE_MAX_WINDOW_S` bounds an ordinary window.
`EDGEWATCH_GATEWAY_LTE_MAX_HELD_WINDOW_S` (default four hours) is the separate
hard ceiling when a signed OTA download or active command holds LTE online.
The held ceiling prevents stuck work from keeping the modem powered forever.

## Energy measurement and sizing gate

Use an inline USB/DC energy meter to record these four modes independently:

- `pi_only`
- `lte_registered_idle`
- `lte_transfer`
- `lte_electrically_off`

Then collect whole-gateway daily energy. The initial benchmark may contain one
24-hour sample; production qualification requires at least seven daily samples.
Create a JSON input like this (replace every example reading with meter data):

```json
{
  "schema_version": 1,
  "mode_measurements": [
    {"mode": "pi_only", "duration_hours": 1, "energy_wh": 3.2},
    {"mode": "lte_registered_idle", "duration_hours": 1, "energy_wh": 8.5},
    {"mode": "lte_transfer", "duration_hours": 1, "energy_wh": 11.2},
    {"mode": "lte_electrically_off", "duration_hours": 1, "energy_wh": 3.8}
  ],
  "daily_energy_wh": [92, 94, 93, 96, 95, 91, 90],
  "cold_derating": 0.7,
  "conversion_efficiency": 0.85
}
```

Run:

```bash
make gateway-energy-report \
  GATEWAY_ENERGY_INPUT=measurements.json \
  GATEWAY_ENERGY_REPORT=qualification.json
```

For the initial single-day benchmark only, add
`GATEWAY_ENERGY_MINIMUM_DAYS=1`. The durable report uses nearest-rank P95,
requires a no-camera average at or below 5 W, and calculates:

```text
battery Wh = P95 daily Wh * 7 / (0.8 * cold derating * conversion efficiency)
minimum daily solar generation = P95 daily Wh * 1.5
```

The solar result is an energy requirement, not a panel-watt recommendation.
Choose the panel from the deployment coordinates and worst-month PVWatts yield.
