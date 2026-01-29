# Optional GCP deployment (mapping)

EdgeWatch is local-first, but the architecture maps cleanly to GCP services.

## Recommended mapping

- **API**: Cloud Run (FastAPI)
- **Database**: Cloud SQL for Postgres
- **Secrets**: Secret Manager (admin key, device tokens)
- **Monitoring**: Cloud Logging + Cloud Monitoring alert policies
- **Edge security**: Cloud Armor and/or Cloudflare in front of Cloud Run

## Notes

- Cloud SQL has a cost even at low usage.
- If you want a near-$0 demo, keep the stack local or use a free-tier VM where appropriate.

## If you want a pure-serverless pattern

For higher scale, you could:
- Ingest to Pub/Sub (HTTP push or direct publish)
- Process in Cloud Run jobs/workers
- Store in BigQuery (cheap analytics) and optionally retain “hot” state in Postgres/Redis

This repo intentionally keeps the deploy story simple and self-hostable.
