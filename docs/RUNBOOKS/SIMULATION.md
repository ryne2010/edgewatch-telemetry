# Runbook: Synthetic telemetry (simulation)

This repo supports a simulation lane so you can validate **UI/UX + alerting + contracts** without physical hardware.

There are two modes:

1) **Local**: run the edge simulator against your local API
2) **Cloud** (dev/stage/prod opt-in): a Cloud Run Job + Cloud Scheduler trigger that periodically generates synthetic telemetry

---

## Local simulation

Start the stack:

```bash
make up
```

Then in another terminal:

```bash
make simulate
```

To point the simulator at a different API URL:

```bash
EDGEWATCH_API_URL=http://localhost:8082 make simulate
```

Notes:

- The simulator adheres to `contracts/telemetry/*`.
- Default profile is `rpi_microphone_power_v1` (microphone + power keys only).
- Legacy full-metric payloads are opt-in via:

```bash
SIMULATION_PROFILE=legacy_full make simulate
```

---

## Cloud simulation (dev + staging + prod opt-in)

Terraform can optionally provision:

- Cloud Run Job: `edgewatch-simulate-telemetry-<env>`
- Cloud Scheduler job: `edgewatch-simulate-telemetry-<env>` (cron)

### Enable

Set Terraform variables:

- `enable_simulation=true`
- `simulation_schedule="*/1 * * * *"`
- `simulation_points_per_device=1`
- Production-only acknowledgement: `simulation_allow_in_prod=true`

Runtime guard:

- `SIMULATION_ALLOW_IN_PROD` defaults to `false`.
- When `APP_ENV=prod` and this flag is not set, the simulation job exits without generating telemetry.
- Optional runtime profile:
  - `SIMULATION_PROFILE=rpi_microphone_power_v1` (default)
  - `SIMULATION_PROFILE=legacy_full` (opt-in)

The provided profiles already enable this:

- `infra/gcp/cloud_run_demo/profiles/dev_public_demo.tfvars`
- `infra/gcp/cloud_run_demo/profiles/stage_private_iam.tfvars`

Production profiles keep simulation disabled by default and require explicit opt-in.

### Manual trigger

```bash
make simulate-gcp ENV=dev   PROJECT_ID=... REGION=...
make simulate-gcp ENV=stage PROJECT_ID=... REGION=...
```

### Disable

Set `enable_simulation=false` and `terraform apply`.

---

## Troubleshooting

### I see no data in the UI

- Local: ensure `make simulate` is running and `EDGEWATCH_API_URL` points at the correct API.
- Cloud: ensure the Cloud Scheduler job exists and is running; check logs for the simulation job:

```bash
make logs-gcp ENV=dev
```

### The job runs, but no devices are present

The job can bootstrap the demo fleet (using the demo env vars) so this should be rare.
If it happens, verify `bootstrap_demo_device=true` for dev/stage or ensure demo env vars are set.
