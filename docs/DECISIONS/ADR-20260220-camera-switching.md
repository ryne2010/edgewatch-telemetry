# ADR: Switched multi-camera strategy (one active camera at a time)

Date: 2026-02-20  Status: Accepted

## Context

EdgeWatch nodes should support **up to 4 cameras** per Raspberry Pi for periodic
snapshots and short diagnostic clips. The deployment environment also includes:

- intermittent connectivity (LTE data SIM)
- constrained power and storage
- a preference for **production-friendly** hardware/software patterns that are realistic
  for field monitoring (not a full NVR)

Most CSI multi-camera adapters for Raspberry Pi are **switched**: they route one
camera onto the CSI interface at a time, which is well-suited to snapshot capture.

## Decision

We will implement camera support assuming:

- **CSI cameras + a switched multi-camera adapter** (e.g., Arducam multi-camera adapter)
- Capture is **one camera at a time** (`cam1..cam4`)
- The agent enforces a **capture lock** so concurrent capture requests serialize
- The product experience emphasizes:
  - scheduled snapshots
  - event-driven snapshots (alert transitions)
  - short clips (bounded duration / size)
- **Real-time streaming is out of scope** for this repo

We will optionally support USB/UVC cameras as an alternative backend, but the
first-class path is the switched CSI approach.

## Consequences

- ✅ Lower cost and wiring complexity vs multiple compute nodes
- ✅ Better image quality and stability vs many low-end USB cameras
- ✅ Aligns with cellular data constraints (snapshot-first is practical)
- ❌ No simultaneous multi-camera video capture
- ❌ Video capture is limited to one camera at a time

Operationally, the "media lane" must remain cost-aware (caps, throttling, retries)
and must not block telemetry flush loops.

## Alternatives considered

- **USB cameras (UVC)** for concurrent capture
  - Pros: potentially concurrent streams
  - Cons: higher power/bandwidth, more cables, more tuning and failure modes
- **Multiple Raspberry Pis (one per camera pair)**
  - Pros: concurrency and redundancy
  - Cons: cost and operational complexity
- **Different compute platforms (Jetson / NVR)**
  - Pros: purpose-built video pipelines
  - Cons: scope creep; not aligned with this repo's constraints

## Rollout / migration plan

1. Implement camera backend abstraction (`agent/camera/*`) with a CSI (libcamera)
   provider and optional USB provider.
2. Implement local ring buffer + upload pipeline (GCS for demo).
3. Add API endpoints for media metadata + uploads.
4. Add UI gallery on device detail.

## Validation

- Capture a snapshot from each camera (`cam1..cam4`) in sequence.
- Verify the capture lock prevents concurrent capture conflicts.
- Verify local ring buffer eviction behavior.
- Verify upload retries + idempotent object keys.
- Measure daily data usage for snapshot/clip policies.
