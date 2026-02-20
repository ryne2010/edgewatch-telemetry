# Pub/Sub Ingest Runbook

## Purpose

Enable optional event-driven ingest mode where API requests enqueue batches to Pub/Sub and a push worker endpoint persists telemetry.

Default posture remains `INGEST_PIPELINE_MODE=direct`.

## Enable (Terraform)

Set these vars in your profile or `TF_VAR_*`:

- `enable_pubsub_ingest=true`
- `pubsub_topic_name` (optional override)
- `pubsub_push_subscription_name` (optional override)

Then deploy:

```bash
make apply-gcp ENV=dev
```

## Runtime behavior

- `POST /api/v1/ingest` creates an `ingestion_batches` artifact immediately.
- In pubsub mode, the batch is queued (`processing_status="queued"`).
- Push worker endpoint: `POST /api/v1/internal/pubsub/push`.
- On worker success, batch status updates to `processing_status="completed"` and accepted/duplicate counts are finalized.

## Verification

- Check ingestion audit:

```bash
curl -s -H "X-Admin-Key: dev-admin-key" \
  http://localhost:8082/api/v1/admin/ingestions | jq
```

- Confirm Terraform outputs include topic/subscription names.

## Failure handling

- Failed deliveries route to the Pub/Sub DLQ topic.
- API remains functional in direct mode even if Pub/Sub is disabled.
