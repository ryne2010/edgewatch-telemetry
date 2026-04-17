from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def _default_update_state_path(device_id: str) -> Path:
    raw = (os.getenv("EDGEWATCH_UPDATE_STATE_PATH") or f"./edgewatch_update_state_{device_id}.json").strip()
    return Path(raw or f"./edgewatch_update_state_{device_id}.json")


def _default_stage_dir() -> Path:
    raw = (os.getenv("EDGEWATCH_SYSTEM_IMAGE_STAGE_DIR") or "/opt/edgewatch/system-image-staging").strip()
    return Path(raw or "/opt/edgewatch/system-image-staging")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def build_report(*, device_id: str, update_state_path: Path, stage_dir: Path) -> dict[str, Any]:
    update_state = _read_json(update_state_path)
    latest_metadata = _read_json(stage_dir / "latest.json")
    manifest_metadata = None
    if latest_metadata and isinstance(latest_metadata.get("manifest_id"), str):
        manifest_metadata = _read_json(stage_dir / str(latest_metadata["manifest_id"]) / "metadata.json")

    return {
        "device_id": device_id,
        "update_state_path": str(update_state_path),
        "stage_dir": str(stage_dir),
        "update_state_exists": update_state is not None,
        "latest_metadata_exists": latest_metadata is not None,
        "manifest_metadata_exists": manifest_metadata is not None,
        "last_applied_deployment_id": (update_state or {}).get("last_applied_deployment_id"),
        "last_healthy_tag": (update_state or {}).get("last_healthy_tag"),
        "last_failed_deployment_id": (update_state or {}).get("last_failed_deployment_id"),
        "pending_boot_health": (update_state or {}).get("pending_boot_health"),
        "latest_metadata": latest_metadata,
        "manifest_metadata": manifest_metadata,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect system-image OTA validation evidence")
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--update-state-path")
    parser.add_argument("--stage-dir")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    update_state_path = (
        Path(args.update_state_path) if args.update_state_path else _default_update_state_path(args.device_id)
    )
    stage_dir = Path(args.stage_dir) if args.stage_dir else _default_stage_dir()
    report = build_report(device_id=args.device_id, update_state_path=update_state_path, stage_dir=stage_dir)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"output": str(output_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
