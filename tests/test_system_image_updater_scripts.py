from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
UPDATER = REPO_ROOT / "scripts" / "ota" / "system_image_updater.py"
ROLLBACK = REPO_ROOT / "scripts" / "ota" / "system_image_rollback.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_system_image_updater_stages_artifact_and_metadata(tmp_path: Path) -> None:
    artifact = tmp_path / "image.img"
    artifact.write_bytes(b"edgewatch-image")
    stage_dir = tmp_path / "stage"
    env = {
        "EDGEWATCH_OTA_ARTIFACT_PATH": str(artifact),
        "EDGEWATCH_OTA_MANIFEST_ID": "manifest-1",
        "EDGEWATCH_OTA_ARTIFACT_SHA256": _sha256(artifact),
        "EDGEWATCH_SYSTEM_IMAGE_STAGE_DIR": str(stage_dir),
    }
    proc = subprocess.run(
        [sys.executable, str(UPDATER)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    metadata = json.loads((stage_dir / "manifest-1" / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["manifest_id"] == "manifest-1"
    assert metadata["artifact_sha256"] == _sha256(artifact)
    assert (stage_dir / "manifest-1" / artifact.name).exists()
    latest = json.loads((stage_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["status"] == "staged"


def test_system_image_rollback_marks_latest_metadata(tmp_path: Path) -> None:
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir(parents=True, exist_ok=True)
    latest_path = stage_dir / "latest.json"
    latest_path.write_text(
        json.dumps(
            {
                "manifest_id": "manifest-2",
                "artifact_path": str(tmp_path / "image.img"),
                "artifact_sha256": "a" * 64,
                "staged_at": "2026-01-01T00:00:00+00:00",
                "status": "staged",
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(ROLLBACK)],
        check=False,
        capture_output=True,
        text=True,
        env={"EDGEWATCH_SYSTEM_IMAGE_STAGE_DIR": str(stage_dir)},
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    assert latest["status"] == "rollback_requested"
    assert "rollback_requested_at" in latest
