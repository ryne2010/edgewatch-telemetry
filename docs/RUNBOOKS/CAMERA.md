# Camera runbook (switched multi-camera capture)

This runbook covers practical bring-up for EdgeWatch camera capture.

Design assumption:
- **one camera active at a time** using a switched CSI multi-camera adapter

See ADR:
- `docs/DECISIONS/ADR-20260220-camera-switching.md`

## 1) Hardware checklist

- Camera ribbon cables are fully seated (both ends)
- Adapter board is powered and connected correctly
- Cameras are mounted securely (strain relief)

## 2) Validate the Pi camera stack

On Raspberry Pi OS, validate libcamera is working:

```bash
libcamera-hello --list-cameras
libcamera-still --camera 0 --nopreview --immediate -o /tmp/cam1-test.jpg
```

Confirm that `/tmp/cam1-test.jpg` is created and non-empty.

If the camera is not detected:
- confirm ribbon orientation
- confirm camera connector port (Pi 5 has multiple connectors)
- confirm I2C/camera interface is enabled

## 3) Multi-camera adapter behavior

Most CSI multi-camera adapters are **switched**:
- only one camera is presented to the Pi at a time
- selection is typically done by toggling GPIO or using the vendor helper

Operational consequences:
- snapshots are captured **sequentially**
- short clips are captured from **one camera at a time**
- the agent must enforce a capture mutex to prevent conflicts

## 4) EdgeWatch 12a validation (device-side capture + ring buffer)

Start API + DB lane:

```bash
make up
```

Run the agent with media enabled:

```bash
MEDIA_ENABLED=true \
CAMERA_IDS=cam1,cam2 \
MEDIA_SNAPSHOT_INTERVAL_S=300 \
MEDIA_RING_DIR=./edgewatch_media \
MEDIA_RING_MAX_BYTES=524288000 \
uv run python agent/edgewatch_agent.py
```

Expected behavior:
- agent logs periodic `media captured camera=... reason=scheduled ...`
- captures are serialized (only one camera capture active at a time)
- files are written under `MEDIA_RING_DIR/<device_id>/<camera_id>/<YYYY-MM-DD>/`
- each image has a JSON sidecar with:
  - `device_id`, `camera_id`, `captured_at`, `reason`, `sha256`, `bytes`, `mime_type`
- when disk usage exceeds `MEDIA_RING_MAX_BYTES`, oldest assets are evicted first

Manual capture command (operator diagnostic):

```bash
python -m agent.tools.camera cam1 \
  --device-id demo-well-001 \
  --reason manual \
  --media-dir ./edgewatch_media \
  --max-bytes 524288000
```

This prints JSON containing `asset_path`, `sidecar_path`, and persisted metadata.

## 5) API metadata + upload + view

The media pipeline uses these device-auth endpoints:

- `POST /api/v1/media`
- `PUT /api/v1/media/{media_id}/upload`
- `GET /api/v1/devices/{device_id}/media`
- `GET /api/v1/media/{media_id}`
- `GET /api/v1/media/{media_id}/download`

Storage backend config:

- local dev / compose:
  - `MEDIA_STORAGE_BACKEND=local`
  - `MEDIA_LOCAL_ROOT=/app/data/media` (compose volume-backed)
- Cloud Run + GCS:
  - `MEDIA_STORAGE_BACKEND=gcs`
  - `MEDIA_GCS_BUCKET=<bucket>`
  - optional `MEDIA_GCS_PREFIX=media`

Example local validation flow:

```bash
export EDGEWATCH_API_URL=http://localhost:8082
export DEVICE_TOKEN=dev-device-token-001
export DEVICE_ID=demo-well-001
export CAMERA_ID=cam1

ASSET_PATH="$(python -m agent.tools.camera "$CAMERA_ID" --device-id "$DEVICE_ID" --reason manual | jq -r '.asset_path')"
SIDECAR_PATH="${ASSET_PATH}.json"

MEDIA_ID="$(curl -sS \
  -H "Authorization: Bearer ${DEVICE_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "$(jq -c '. + {message_id: ("media-" + .sha256[0:24])}' "${SIDECAR_PATH}")" \
  "${EDGEWATCH_API_URL}/api/v1/media" | jq -r '.media.id')"

curl -sS -X PUT \
  -H "Authorization: Bearer ${DEVICE_TOKEN}" \
  -H "Content-Type: image/jpeg" \
  --data-binary @"${ASSET_PATH}" \
  "${EDGEWATCH_API_URL}/api/v1/media/${MEDIA_ID}/upload" | jq

curl -sS \
  -H "Authorization: Bearer ${DEVICE_TOKEN}" \
  "${EDGEWATCH_API_URL}/api/v1/devices/${DEVICE_ID}/media?limit=5" | jq
```

Expected behavior:

- metadata creation is idempotent by `(device_id, message_id, camera_id)`
- upload validates byte length + SHA-256 integrity
- media list is ordered by latest `captured_at`
- downloads require device auth and return original media bytes

## 6) Agent auto-upload behavior

When `MEDIA_ENABLED=true`, the agent now:
- captures scheduled snapshots into the local ring buffer
- captures alert-transition snapshots with reason `alert_transition` (cooldown controlled)
- uploads oldest pending assets to the API with retry backoff

Key env vars:
- `MEDIA_UPLOAD_RETRY_S`
- `MEDIA_UPLOAD_BACKOFF_MAX_S`
- `MEDIA_UPLOAD_TIMEOUT_S`
- `MEDIA_ALERT_TRANSITION_MIN_INTERVAL_S`

## 7) Field diagnostics to collect

If captures fail:
- camera stack test output
- adapter selection method used
- agent logs (capture exceptions, retries)
- disk usage and ring buffer status
- API responses for metadata/upload/list/download
