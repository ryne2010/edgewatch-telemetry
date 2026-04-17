from __future__ import annotations

import json
import os
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stage_root() -> Path:
    raw = (os.getenv("EDGEWATCH_SYSTEM_IMAGE_STAGE_DIR") or "/opt/edgewatch/system-image-staging").strip()
    return Path(raw or "/opt/edgewatch/system-image-staging")


def main() -> int:
    stage_root = _stage_root()
    latest_path = stage_root / "latest.json"
    if not latest_path.exists():
        raise SystemExit(f"missing staged system image metadata: {latest_path}")
    metadata = json.loads(latest_path.read_text(encoding="utf-8"))
    metadata["rollback_requested_at"] = _utcnow()
    metadata["status"] = "rollback_requested"
    latest_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")

    hook_raw = (os.getenv("EDGEWATCH_SYSTEM_IMAGE_ROLLBACK_HOOK") or "").strip()
    if hook_raw:
        env = os.environ.copy()
        env["EDGEWATCH_SYSTEM_IMAGE_LATEST_METADATA_PATH"] = str(latest_path)
        proc = subprocess.run(
            shlex.split(hook_raw),
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        if proc.returncode != 0:
            raise SystemExit(f"rollback hook failed: {(proc.stdout or proc.stderr or '').strip()[:240]}")

    print(json.dumps(metadata, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
