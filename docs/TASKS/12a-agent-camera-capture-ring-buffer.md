# Task 12a — Agent camera capture + ring buffer (one camera at a time)

🟢 **Status: Implemented (2026-02-21)**

## Objective

Implement the **device-side** camera capture pipeline:

- capture photo snapshots (MVP)
- serialize capture (one camera active at a time)
- persist assets to a local ring buffer with metadata sidecars
- provide stable interfaces so later tasks can add upload + UI

Related ADR:
- `docs/DECISIONS/ADR-20260220-camera-switching.md`

## Scope

### In-scope

- Create `agent/media/` module with:
  - capture primitives (photo first)
  - a capture mutex/lock
  - ring buffer storage with max disk usage and FIFO eviction
  - metadata sidecar per asset:

```json
{
  "device_id": "...",
  "camera_id": "cam1",
  "captured_at": "2026-02-21T...Z",
  "reason": "scheduled|alert_transition|manual",
  "sha256": "...",
  "bytes": 123456,
  "mime_type": "image/jpeg"
}
```

- Implement a camera backend strategy:
  - `libcamera` CLI capture (`libcamera-still`) is acceptable for MVP
  - keep it behind an interface so picamera2 can be swapped in

- Add a minimal trigger loop (MVP):
  - scheduled snapshot every N minutes (config)

### Out-of-scope

- Upload to Cloud (Task 12b).
- UI gallery (Task 12c).
- Video clips (can be added after photo lane is stable).

## Design notes

- Treat camera selection + capture as one critical section.
- Avoid holding the mutex while doing long IO if possible; but correctness > throughput.
- Ring buffer should be robust to partial writes:
  - write temp file, fsync, rename

## Acceptance criteria

- Agent can be configured with `MEDIA_ENABLED=true` and `CAMERA_IDS=cam1,cam2,...`.
- Capture lock prevents concurrency issues.
- Ring buffer enforces max size and evicts oldest assets.
- On non-RPi machines, module import should be safe; if capture isn’t supported, it should fail gracefully when enabled.

## Deliverables

- `agent/media/` modules + tests for ring buffer logic
- Docs updates:
  - `docs/RUNBOOKS/CAMERA.md` bring-up + manual capture commands

## Validation

```bash
make fmt
make lint
make typecheck
make test
```
