# Architecture

EdgeWatch is a lightweight **edge telemetry + alerting** platform.

It demonstrates staff-level patterns:
- device auth (token hashing) + admin auth
- idempotent ingestion with dedupe windows
- operational alerts with routing/throttling rules
- clear time-series query API for dashboards
- cloud-ready deploy (Cloud Run + Secret Manager) while remaining local-first

## Local reference architecture

```
Edge device (RPi)
  | HTTPS + Bearer token
  v
FastAPI ingest API
  | SQLAlchemy
  v
Postgres
  | background monitor job
  v
Alerts + notifications
```

See `docs/architecture.md` for the deeper breakdown.
