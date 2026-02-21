# Camera runbook (switched multi-camera capture)

This runbook covers practical bring-up for EdgeWatch camera capture.

Design assumption:
- **one camera active at a time** using a switched CSI multi-camera adapter

See ADR:
- `docs/DECISIONS/ADR-20260220-camera-switching.md`

> Note: implementation is tracked by `docs/TASKS/12-camera-capture-upload.md`.

## 1) Hardware checklist

- Camera ribbon cables are fully seated (both ends)
- Adapter board is powered and connected correctly
- Cameras are mounted securely (strain relief)

## 2) Validate the Pi camera stack

On Raspberry Pi OS, validate libcamera is working:

- Run a basic camera test command (varies by OS image)
- Confirm you can capture a still image successfully

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

## 4) EdgeWatch validation (planned)

End-to-end validation target:

- start stack (`make up`)
- run the agent with camera backend enabled
- trigger:
  - scheduled snapshots (interval)
  - alert-transition snapshots (water pressure low/recover)
- confirm:
  - local ring buffer grows and evicts oldest-first
  - upload succeeds (local filesystem or GCS demo)
  - UI shows the latest capture per camera

## 5) Field diagnostics to collect

If captures fail:
- camera stack test output
- adapter selection method used
- agent logs (capture exceptions, retries)
- disk usage and ring buffer status
