from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _require_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise SystemExit(f"missing required env {name}")
    return value


def _stage_root() -> Path:
    raw = (os.getenv("EDGEWATCH_SYSTEM_IMAGE_STAGE_DIR") or "/opt/edgewatch/system-image-staging").strip()
    return Path(raw or "/opt/edgewatch/system-image-staging")


def main() -> int:
    artifact_path = Path(_require_env("EDGEWATCH_OTA_ARTIFACT_PATH"))
    manifest_id = _require_env("EDGEWATCH_OTA_MANIFEST_ID")
    expected_sha256 = _require_env("EDGEWATCH_OTA_ARTIFACT_SHA256").lower()
    if not artifact_path.exists():
        raise SystemExit(f"artifact does not exist: {artifact_path}")

    actual_sha256 = _sha256_file(artifact_path)
    if actual_sha256 != expected_sha256:
        raise SystemExit(f"artifact sha256 mismatch expected={expected_sha256} actual={actual_sha256}")

    stage_root = _stage_root()
    manifest_dir = stage_root / manifest_id
    manifest_dir.mkdir(parents=True, exist_ok=True)
    staged_artifact = manifest_dir / artifact_path.name
    shutil.copyfile(artifact_path, staged_artifact)

    metadata = {
        "manifest_id": manifest_id,
        "artifact_path": str(staged_artifact),
        "artifact_sha256": actual_sha256,
        "staged_at": _utcnow(),
        "status": "staged",
    }
    metadata_path = manifest_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    latest_path = stage_root / "latest.json"
    latest_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")

    hook_raw = (os.getenv("EDGEWATCH_SYSTEM_IMAGE_STAGE_HOOK") or "").strip()
    if hook_raw:
        env = os.environ.copy()
        env["EDGEWATCH_STAGED_ARTIFACT_PATH"] = str(staged_artifact)
        env["EDGEWATCH_STAGED_METADATA_PATH"] = str(metadata_path)
        proc = subprocess.run(
            shlex.split(hook_raw),
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        if proc.returncode != 0:
            raise SystemExit(f"stage hook failed: {(proc.stdout or proc.stderr or '').strip()[:240]}")

    print(json.dumps(metadata, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
