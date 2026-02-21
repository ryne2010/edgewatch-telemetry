# Tutorial: Add a new telemetry metric safely

This repo treats new telemetry metrics as a **data-contract change**, not "just another JSON key".

The goal is to keep the system production-friendly:
- predictable ingest
- type-safe time-series queries
- drift visibility (unknown keys) without blocking additive evolution

## 0) Decide what kind of change this is

- **Additive** (safe): a new key that didn't exist before.
- **Breaking** (unsafe): changing the meaning/type of an existing key.

EdgeWatch accepts *unknown* keys by default (additive drift), but if you want the UI + downstream
logic to rely on a metric, you should add it to the contract.

## 1) Update the telemetry contract

Edit:

- `contracts/telemetry/v1.yaml`

Add a new metric entry:

```yaml
metrics:
  oil_pressure_psi:
    type: number
    unit: psi
    description: Oil pressure at the sensor.
```

Notes:
- Keep keys `snake_case`.
- If you need a breaking change, create a new contract version file (e.g. `v2.yaml`) and update
  `TELEMETRY_CONTRACT_VERSION` in your environment.

## 2) Run repo-quality gates

```bash
make fmt
make lint
make typecheck
make test
```

## 3) Validate locally (end-to-end)

Bring up the stack:

```bash
make up
make demo-device
make simulate
```

Inspect the active contract:

```bash
curl -s http://localhost:8082/api/v1/contracts/telemetry | jq
```

Inspect ingestion batches (admin-only):

```bash
curl -s -H "X-Admin-Key: dev-admin-key" http://localhost:8082/api/v1/admin/ingestions | jq
```

## 4) Update the UI (optional but recommended)

If the UI has a metric picker, add the new key there so it becomes discoverable.

If you rely on a metric for alerts, update the backend alerting logic and add tests.

## 5) Deploy to GCP (demo or prod lane)

```bash
make deploy-gcp-demo
# or
make deploy-gcp-prod
```

If migrations changed:

```bash
make migrate-gcp ENV=dev
make verify-gcp-ready ENV=dev
```

## 6) Monitor drift

If devices start sending a new key **before** the contract includes it, ingestion will still succeed,
but the unknown key will show up in `unknown_metric_keys` in the ingestion batches.

That is the intended posture: *accept additive drift, but make it visible*.
