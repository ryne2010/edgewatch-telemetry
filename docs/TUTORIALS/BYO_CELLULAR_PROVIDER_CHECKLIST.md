# Tutorial: BYO Cellular Provider Checklist

Use this checklist before field rollout with a customer-managed data plan.

## Required provider inputs

1. APN name (and username/password if required).
2. SIM activation status and data-only plan confirmation.
3. IMEI registration requirements (if carrier enforces allow-listing).
4. Roaming policy and throttling limits (including daily/monthly shaping profile).
5. IPv4/IPv6 behavior under CGNAT.
6. Expected network mode (LTE/5G NSA) and fallback behavior.

## Deployment assumptions

- EdgeWatch requires outbound HTTPS only.
- Inbound public IP is not required (CGNAT is acceptable).
- Static IP is not required for current device-pull + HTTPS POST model.
- Default hardware baseline is USB LTE modem + nano-SIM.
- eSIM is optional and depends on modem firmware + carrier eUICC support.
- eSIM is not required for v1 GA.

## Common deployment blockers

1. Carrier blocks unknown IMEI/SKU until allow-listed.
2. APN profile is not provisioned for data-only IoT plans.
3. Provider idle timeout is aggressive and causes reconnect churn.
4. Hard throttling drops throughput below heartbeat/telemetry budget.

## Validation commands on device

```bash
sudo mmcli -L
sudo mmcli -m 0 --simple-status
nmcli con show --active
dig +short google.com
curl -fsS https://www.gstatic.com/generate_204 -o /dev/null && echo ok
```

## Go-live acceptance

1. Device ingests telemetry for at least 10-15 minutes without reconnect churn.
2. `signal_rssi_dbm` and cellular telemetry are visible.
3. Buffer depth does not increase continuously.
4. Reboot test confirms automatic modem reconnection and resumed ingest.
