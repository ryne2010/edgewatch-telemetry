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

## 5) Field diagnostics to collect

If captures fail:
- camera stack test output
- adapter selection method used
- agent logs (capture exceptions, retries)
- disk usage and ring buffer status
