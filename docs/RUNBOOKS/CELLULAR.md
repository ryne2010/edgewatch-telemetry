# Cellular Runbook (LTE modem + data SIM)

This runbook is for field bring-up and troubleshooting of Raspberry Pi EdgeWatch nodes using LTE.

Principle: Linux networking owns the link; EdgeWatch observes and reports link health.

Default deployment baseline:
- USB LTE modem + nano-SIM (BYO carrier data plan).
- eSIM is optional and only supported when modem firmware/carrier profile includes eUICC support.

Carrier prerequisites to confirm before site rollout:
- APN details (and credentials if required).
- Whether IMEI pre-registration/allow-listing is required.
- IPv4/IPv6 posture and CGNAT behavior.
- Roaming policy and throttling limits.
- Any port filtering that could block HTTPS egress to EdgeWatch endpoints.
- Idle timeout behavior that may force reconnect churn.

Non-requirements for EdgeWatch v1:
- inbound public IP is not required.
- static IP is not required.
- eSIM is optional; nano-SIM USB modem remains the baseline.

## 1) Hardware options

Use one of these patterns:

- LTE HAT (for example Sixfab + Quectel): tight integration, clean enclosure fit, good for fixed installs.
- USB LTE modem: fastest to prototype, easy swap in field, simplest replacement flow.
- External LTE router (Ethernet handoff to Pi): best radio/admin features, easiest remote troubleshooting, extra hardware cost.

Minimum physical checks before software setup:

- Stable power budget for Pi + modem + cameras (brownouts are common root cause).
- SIM seated correctly and activated by carrier.
- Main LTE antenna connected (and positioned away from metal shielding).
- USB/PCIe cabling seated and strain-relieved.

## 2) Fresh Pi prerequisites

Install and enable baseline modem tooling:

```bash
sudo apt-get update
sudo apt-get install -y modemmanager network-manager usb-modeswitch dnsutils jq
sudo systemctl enable --now ModemManager
sudo systemctl enable --now NetworkManager
```

Expected:

- `systemctl is-active ModemManager` returns `active`
- `systemctl is-active NetworkManager` returns `active`

## 3) Discover modem + SIM state

Confirm hardware is detected:

```bash
lsusb
```

Expected: a modem vendor appears (for example Quectel/Huawei/Sierra/Fibocom/ZTE).

List modems:

```bash
sudo mmcli -L
```

Expected: at least one modem path like `/org/freedesktop/ModemManager1/Modem/0`.

Inspect modem summary:

```bash
sudo mmcli -m 0
```

Important fields:

- `state`: should progress toward `registered`/`connected`
- `sim`: should not be `none`
- `access tech`: typically LTE/4G when attached

Inspect SIM details:

```bash
sudo mmcli -i 0
```

Expected:

- valid `imsi` and `operator id`
- `active: yes`
- lock state not requiring PIN/PUK

If SIM PIN is required:

```bash
sudo mmcli -i 0 --pin=1234
```

## 4) Configure APN with NetworkManager

Create a named LTE connection:

```bash
sudo nmcli con add type gsm ifname "*" con-name edgewatch-lte apn "<APN>"
sudo nmcli con modify edgewatch-lte connection.autoconnect yes ipv4.method auto ipv6.method ignore
```

If carrier requires credentials:

```bash
sudo nmcli con modify edgewatch-lte gsm.username "<USER>" gsm.password "<PASS>"
```

Bring connection up:

```bash
sudo nmcli con up edgewatch-lte
```

Expected: `Connection successfully activated`.

Verify connection status:

```bash
nmcli -f NAME,TYPE,DEVICE,STATE con show --active
```

Expected: `edgewatch-lte` in `activated` state on modem interface.

## 5) Registration, signal, DNS, and egress checks

Registration and signal:

```bash
sudo mmcli -m 0 --simple-status
sudo mmcli -m 0 --signal-get
```

Expected:

- `state: connected`
- `m3gpp registration state: home|roaming`
- usable signal metrics (quality and/or RSRP/RSRQ/SINR depending on modem support)

IP + route:

```bash
ip -4 addr
ip route
```

Expected: modem interface has IPv4 address and default route.

DNS + internet reachability:

```bash
dig +short google.com
ping -c 3 1.1.1.1
curl -fsS https://www.gstatic.com/generate_204 -o /dev/null && echo "egress ok"
```

Expected:

- `dig` returns an IP
- `ping` receives replies
- `egress ok` printed

## 6) Validate EdgeWatch over LTE

Check agent health:

```bash
journalctl -u edgewatch-agent -n 100 --no-pager
```

Expected:

- no repeated ingest/auth failures
- successful policy fetch and ingest posts

If Task 13b cellular observability is enabled, verify agent env includes:

- `CELLULAR_METRICS_ENABLED=true`
- `CELLULAR_WATCHDOG_ENABLED=true`

Validate telemetry fields in UI/API:

- device remains online
- `signal_rssi_dbm` appears in telemetry stream
- `cellular_registration_state` appears and is typically `home` or `roaming`
- `link_ok` toggles based on real connectivity checks
- `link_last_ok_at` updates when connectivity succeeds
- when modem supports them: `cellular_rsrp_dbm`, `cellular_rsrq_db`, `cellular_sinr_db`
- daily counters increment: `cellular_bytes_sent_today`, `cellular_bytes_received_today`
- cost-cap audit metrics appear:
  - `cost_cap_active`
  - `bytes_sent_today`
  - `media_uploads_today`
- local buffer is not continuously growing

## 7) Common failures (with commands + expected output)

### A) Modem not detected

Run:

```bash
lsusb
sudo mmcli -L
dmesg | tail -n 80
```

Healthy output:

- modem appears in `lsusb`
- `mmcli -L` lists modem(s)

Failure indicators:

- no modem in `lsusb` and `mmcli -L` returns `No modems were found`
- kernel log shows USB resets/disconnect loops

Most likely causes:

- insufficient power
- bad USB cable/port
- modem not in data mode (usb-modeswitch issue)

### B) SIM not ready

Run:

```bash
sudo mmcli -m 0
sudo mmcli -i 0
```

Healthy output:

- `sim` path present
- SIM `active: yes`

Failure indicators:

- SIM missing/unknown
- PIN/PUK lock

Most likely causes:

- SIM not seated
- SIM not activated
- SIM locked by PIN
- APN profile not provisioned for IoT/data-only service

### C) Registered but no data session

Run:

```bash
sudo mmcli -m 0 --simple-status
nmcli con show edgewatch-lte
```

Healthy output:

- modem registered + connected
- connection profile APN matches carrier requirement

Failure indicators:

- `registration state: denied|searching`
- connection repeatedly fails to activate

Most likely causes:

- wrong APN
- carrier plan missing data attach
- weak/unsupported band coverage
- IMEI not allow-listed for modem SKU

### D) Connected but no DNS/egress

Run:

```bash
ip route
cat /etc/resolv.conf
dig +short google.com
curl -I https://www.gstatic.com/generate_204
```

Healthy output:

- default route exists
- nameserver present
- DNS lookup returns IP
- HTTP 204/200 returned

Failure indicators:

- no default route
- DNS lookup timeout
- curl timeout despite link up

Most likely causes:

- DNS misconfiguration
- captive/filtered carrier APN
- upstream carrier outage

### E) Link drops after a few minutes

Run:

```bash
journalctl -u ModemManager -n 200 --no-pager
vcgencmd get_throttled
```

Healthy output:

- no repeated modem disconnect/reconnect churn
- throttling state indicates no undervoltage events

Failure indicators:

- periodic modem resets in logs
- undervoltage/throttling flags set

Most likely causes:

- brownouts/thermal constraints
- poor RF placement (antenna/cabinet shielding)
- aggressive carrier idle timeout under CGNAT

## 8) Field checklist (before leaving site)

- Modem discovered and SIM active (`mmcli -L`, `mmcli -i 0`).
- APN profile saved and autoconnect enabled (`nmcli con show edgewatch-lte`).
- IP + default route + DNS + HTTPS egress verified.
- Agent running under `systemd` with clean logs for at least 10-15 minutes.
- `signal_rssi_dbm` visible in EdgeWatch telemetry.
- `link_ok` and `link_last_ok_at` visible in telemetry (if watchdog enabled).
- Reboot test completed and LTE reconnects automatically.
- Device can reach API and ingest points after reboot.

## 9) Diagnostics to capture for escalation

- Site name, timestamp, and modem model/firmware.
- Output of:
  - `sudo mmcli -m 0`
  - `sudo mmcli -m 0 --simple-status`
  - `sudo mmcli -m 0 --signal-get`
  - `nmcli con show edgewatch-lte`
  - `ip route`
  - `journalctl -u ModemManager -n 200 --no-pager`
  - `journalctl -u edgewatch-agent -n 200 --no-pager`
- Whether issue reproduces after reboot and after relocating antenna.
