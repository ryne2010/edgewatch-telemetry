# Task 12b — API: media metadata + storage (local + GCS)

🟡 **Status: Planned**

## Objective

Add a production-grade **media pipeline** on the API side:

- store media metadata in Postgres
- store bytes in:
  - local dev: filesystem volume
  - cloud: GCS bucket
- support **idempotent uploads** and safe listing for the UI

This task intentionally ships the backend lane first; UI comes in Task 12c.

## Scope

### In-scope

- New SQLAlchemy model + migration:
  - `media_objects` table with:
    - `device_id`, `camera_id`, `captured_at`, `reason`
    - `sha256`, `bytes`, `mime_type`
    - storage pointer (`gcs_uri` or `local_path`)
    - `message_id` correlation

- New endpoints (device-auth):
  - `POST /api/v1/media` (create metadata record; returns upload instructions)
  - `PUT  /api/v1/media/{id}/upload` (direct upload for local dev)
  - `GET  /api/v1/devices/{device_id}/media` (list recent)
  - `GET  /api/v1/media/{id}` (metadata)
  - `GET  /api/v1/media/{id}/download` (signed URL or proxied download)

- Storage strategy:
  - local dev: store under a mounted directory (e.g., `/data/media/...`)
  - Cloud Run: use GCS bucket, with IAM least privilege

- Idempotency:
  - deterministic object path: `<device_id>/<camera_id>/<YYYY-MM-DD>/<message_id>.<ext>`
  - uniqueness constraint on `(device_id, message_id, camera_id)`

### Out-of-scope

- Thumbnails + transcoding (future follow-up).

## Design notes

- Prefer "metadata-first" upload:
  - API returns a signed upload URL (cloud)
  - the device uploads bytes
  - API finalizes state

- For MVP, direct upload endpoint is acceptable for local dev.

## Acceptance criteria

- Local dev path works with Docker Compose.
- Cloud path works on Cloud Run with GCS.
- Media list endpoint returns the latest per device ordered by capture time.
- No public bucket access required for prod posture.

## Deliverables

- `api/app/models.py` updates + migration
- `api/app/routes/media.py` (or similar)
- `docs/CONTRACTS.md` updated with media endpoints
- `docs/RUNBOOKS/CAMERA.md` updated with end-to-end “capture → upload → view” steps

## Validation

```bash
make fmt
make lint
make typecheck
make test

# smoke
make up
# run agent with MEDIA_ENABLED and confirm media rows exist
```
