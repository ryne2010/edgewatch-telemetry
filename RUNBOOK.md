# Runbook

## Local operations

Start / stop:

```bash
make up
make down
```

Tail logs:

```bash
make logs
```

Apply migrations:

```bash
make db-migrate
```

Create a demo device:

```bash
make demo-device
```

Run the edge simulator:

```bash
make simulate
```

Replay buffered history (agent-side):

```bash
uv run python -m agent.replay --since 2026-01-01T00:00:00Z --until 2026-01-02T00:00:00Z
```

Check device status / alerts:

```bash
make devices
make alerts
```

---

## Cloud Run demo (optional)

### One-time / per-project

```bash
make init PROJECT_ID=YOUR_PROJECT REGION=us-central1
make auth
make doctor-gcp

make db-secret
make admin-secret
```

### Deploy

```bash
# Recommended safe deploy: deploy, run migrations job, then readiness verify
make deploy-gcp-safe ENV=dev
```

Verify + logs:

```bash
make verify-gcp ENV=dev
make verify-gcp-ready ENV=dev
make logs-gcp ENV=dev
```

Manually run optional jobs:

```bash
make offline-check-gcp ENV=dev
make analytics-export-gcp ENV=dev
```

### Rollback

Deploy a previous image tag:

```bash
make deploy-gcp ENV=dev TAG=v2026-01-29-1
```
