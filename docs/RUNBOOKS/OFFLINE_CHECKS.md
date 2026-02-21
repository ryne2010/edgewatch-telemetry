# Offline checks

EdgeWatch treats "offline" as an operational signal:

- devices that have not reported telemetry recently should be visible quickly
- alerts should be created (and resolved) consistently

## How it works

- The API stores telemetry points with timestamps.
- The **offline check job** looks for devices whose latest telemetry timestamp is older than the configured threshold.
- When a device crosses the threshold, the job creates an `offline` alert.
- When telemetry resumes, the alert is resolved.

## Where the code lives

- Job entrypoint: `api/app/jobs/offline_check.py`
- Alert model + logic: `api/app/alerts.py`

## Running locally

### Docker Compose lane

```bash
make offline-check-local
```

### Host dev lane

Ensure the API can connect to Postgres (via your `.env` / `DATABASE_URL`), then:

```bash
uv run --locked python -m api.app.jobs.offline_check
```

## Running in GCP

The Terraform stack provisions a Cloud Run Job and (optionally) a Cloud Scheduler trigger.

Manual run:

```bash
make offline-check-gcp
```

## Tuning

Offline thresholds are controlled by the **edge policy contract**:

- `contracts/edge_policy/v1.yaml`

Typical approach:

- Use a longer threshold in production to avoid flapping during spotty networks.
- Use a shorter threshold in demo environments so the UI feels responsive.

## Troubleshooting

- If the job runs but no alerts appear:
  - verify devices have telemetry
  - verify timestamps are correct (UTC)
  - check Cloud Run job logs (`make logs-gcp`)
- If alerts flap frequently:
  - increase offline threshold
  - verify agent buffering is working (store-and-forward)

## Agent buffer diagnostics (Task 19)

The edge agent now emits buffer audit metrics in telemetry:

- `buffer_db_bytes`
- `buffer_queue_depth`
- `buffer_evictions_total`

Quick local checks on a device:

```bash
# Inspect queue depth + bytes directly from the buffer DB
uv run --locked python - <<'PY'
from agent.buffer import SqliteBuffer
buf = SqliteBuffer("./edgewatch_buffer.sqlite")
print(buf.metrics())
PY

# Check for corruption-recovery artifacts
ls -1 ./edgewatch_buffer.sqlite.corrupt-* 2>/dev/null || echo "no corruption backups"
```

If `buffer_evictions_total` is increasing, the device is dropping oldest buffered
points due quota/disk pressure. Increase `BUFFER_MAX_DB_BYTES` if retention needs
to be longer on that node.
