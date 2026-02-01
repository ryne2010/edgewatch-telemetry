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

Create a demo device:

```bash
make demo-device
```

Run the edge simulator:

```bash
make simulate
```

Check device status / alerts:

```bash
make devices
make alerts
```

---

## Cloud Run demo (optional)

Deploy:

```bash
make deploy-gcp
```

Add secret versions (required):

```bash
make db-secret
make admin-secret
```

Verify:

```bash
make verify-gcp
make logs-gcp
```

Rollback:

```bash
make deploy-gcp TAG=v2026-01-29-1
```
