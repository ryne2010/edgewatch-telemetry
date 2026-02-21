from __future__ import annotations

import argparse
import json

from agent.media.capture import LibcameraStillBackend, MediaCaptureService
from agent.media.storage import MediaRingBuffer


def main() -> None:
    parser = argparse.ArgumentParser(description="EdgeWatch manual camera capture tool")
    parser.add_argument("camera_id", help="camera id (for example: cam1)")
    parser.add_argument("--device-id", default="demo-well-001", help="device id")
    parser.add_argument(
        "--reason",
        default="manual",
        choices=("manual", "scheduled", "alert_transition"),
        help="capture reason to persist in sidecar metadata",
    )
    parser.add_argument(
        "--media-dir",
        default="./edgewatch_media",
        help="root directory for local media ring buffer",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=500 * 1024 * 1024,
        help="max ring buffer size in bytes",
    )
    parser.add_argument(
        "--capture-timeout-s",
        type=float,
        default=15.0,
        help="libcamera capture timeout in seconds",
    )
    parser.add_argument(
        "--lock-timeout-s",
        type=float,
        default=5.0,
        help="capture lock timeout in seconds",
    )
    args = parser.parse_args()

    ring_buffer = MediaRingBuffer(args.media_dir, max_bytes=args.max_bytes)
    capture = MediaCaptureService(
        device_id=args.device_id,
        backend=LibcameraStillBackend(),
        ring_buffer=ring_buffer,
        capture_timeout_s=args.capture_timeout_s,
        lock_timeout_s=args.lock_timeout_s,
    )
    result = capture.capture_snapshot(camera_id=args.camera_id, reason=args.reason)

    print(
        json.dumps(
            {
                "asset_path": str(result.asset_path),
                "sidecar_path": str(result.sidecar_path),
                "metadata": {
                    "device_id": result.metadata.device_id,
                    "camera_id": result.metadata.camera_id,
                    "captured_at": result.metadata.captured_at,
                    "reason": result.metadata.reason,
                    "sha256": result.metadata.sha256,
                    "bytes": result.metadata.bytes,
                    "mime_type": result.metadata.mime_type,
                },
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
