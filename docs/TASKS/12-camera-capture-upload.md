# Task 12 (Epic) — Camera capture + media upload (up to 4 cameras)

🟡 **Status: Planned (decomposed into smaller Codex tasks)**

## Intent

Add a "media lane" to EdgeWatch so each Raspberry Pi node can support:

- up to 4 cameras (`cam1..cam4`)
- scheduled snapshots (photo)
- event-driven snapshots (ex: on alert transitions)
- short video clips (bounded duration/size)

Design assumptions (per ADR):

- **One camera active at a time** (switched CSI multi-camera adapter).

Related ADR:
- `docs/DECISIONS/ADR-20260220-camera-switching.md`

The design must respect real-world constraints:

- intermittent connectivity
- limited bandwidth (cellular data)
- storage limits on the device

## Implementation plan (Codex-friendly slices)

1) Device capture + ring buffer → `12a-agent-camera-capture-ring-buffer.md`
2) API metadata + storage (local+GCS) → `12b-api-media-metadata-storage.md`
3) Web UI gallery → `12c-web-media-gallery.md`

Video clips can be added after photo lane is stable.

## Non-goals

- Real-time streaming / WebRTC.
- Long-duration video archival.
- A full NVR feature set.

## Acceptance criteria (epic-level)

### Agent

- CSI cameras supported via libcamera/picamera2 (**switched**; serialized capture)
- Supports camera identifiers: `cam1`..`cam4`
- Enforces a **capture mutex/lock** so only one capture runs at a time
- Captures written to a **local ring buffer**:
  - max disk usage limit
  - oldest-first eviction
  - metadata sidecar
- Upload pipeline:
  - retries with backoff
  - idempotent upload keys
  - cost-aware send strategy (edge policy)

### API

- Media endpoints exist behind device auth.
- Storage:
  - local dev: filesystem (mounted volume)
  - cloud: GCS bucket

### UI

- Device detail includes a gallery:
  - latest photo per camera
  - open full-res asset
  - show capture time + reason

### Security

- Upload URLs (if used) are time-limited.
- No public bucket access for prod posture.

### Docs

- Runbook exists: `docs/RUNBOOKS/CAMERA.md`

## Validation plan

```bash
make fmt
make lint
make typecheck
make test
```
