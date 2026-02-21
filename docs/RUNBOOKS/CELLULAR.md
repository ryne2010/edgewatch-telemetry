# Cellular Runbook (LTE data SIM)

This runbook covers practical bring-up and troubleshooting when an EdgeWatch node
uses a cellular modem + data SIM for internet.

> Principle: the OS owns the modem connection; EdgeWatch observes + reports link health.

## 1) Bring-up checklist

1) Verify hardware
- Modem powered (and gets adequate current)
- SIM inserted
- Antennas attached

2) Verify OS sees the modem
- Check USB / PCIe device presence
- If using ModemManager, confirm it discovers a modem

3) Configure APN
- Carrier APN varies (check your SIM provider)
- Save configuration in NetworkManager/ModemManager

4) Confirm IP connectivity
- Resolve DNS
- Reach the EdgeWatch API URL

5) Verify EdgeWatch telemetry
- Confirm `signal_rssi_dbm` is being reported
- Confirm the device can ingest points (no buffering growth)

## 2) Common failure modes

### "No network" / "No service"

- Antenna missing / wrong band
- SIM not activated
- APN wrong
- Insufficient power to modem

### Works briefly, then drops

- Brownout (power supply)
- Thermal shutdown
- Weak signal; consider higher-gain antenna or different placement

### High data usage

- Snapshot/video upload frequency too high
- Telemetry cadence too frequent
- Consider adding policy caps (see `docs/TASKS/13-cellular-connectivity.md`)

## 3) Field diagnostics to collect

- Timestamp + location
- Signal strength metrics (RSSI; optionally RSRP/RSRQ/SINR)
- IP address / carrier
- Any modem logs
- EdgeWatch agent logs and buffer size

## 4) Escalation

- If multiple nodes fail in the same area, suspect carrier outage.
- If a single node fails, suspect hardware/power/antenna.
