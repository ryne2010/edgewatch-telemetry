# Roadmap

This roadmap is organized into **milestones**. The repo is intentionally built as a
**teachable, production-minded demo**: it runs locally on a laptop, but the same
patterns scale to GCP.

## Current milestone: MVP telemetry + alerts (DONE)

✅ Edge agent + simulator
- Device policy fetch + caching (ETag / max-age)
- Offline buffering with durable sqlite queue
- Cost-aware send strategy (delta + heartbeat + alert transitions)

✅ API + storage
- Contract-enforced ingest endpoint
- Postgres storage (JSONB metrics)
- Lineage artifacts: `ingestion_batches` table + payload/contract hashes

✅ Alerting
- Monitor loop for offline + low water pressure
- Alert history APIs

✅ UI
- Basic dashboard + charts

✅ Harness engineering
- Make targets
- Pre-commit hooks
- Repo hygiene scripts
- GitHub Actions CI + Terraform workflows

## Next milestone: “Job-app aligned” production features

These map well to GCP platform / data engineering roles.

### Observability + operations
- OpenTelemetry traces + metrics from API
- SLO dashboards + alert routing (paging vs email)
- Structured logs and log-based metrics

### Data platform integration
- Stream ingest to Pub/Sub
- Batch/stream transforms (Dataflow / Spark)
- Warehouse sink (BigQuery) + partitioning strategy
- Data quality checks (Great Expectations / dbt tests)

### Security + tenancy
- Multi-tenant device orgs
- Fine-grained RBAC
- Key rotation and device enrollment flows

### Edge optimizations
- Per-alert cadence profiles (critical vs non-critical)
- On-device summarization (min/max/avg buckets)
- Optional compression and binary payloads

## Stretch milestone: anomaly detection

- Baseline modeling per device
- Alert on anomalies (e.g., pressure decay, unusual pump cycles)
- Backtesting + alert fatigue controls
