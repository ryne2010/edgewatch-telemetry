from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ota" / "collect_system_image_validation_evidence.py"


def test_collect_system_image_validation_evidence(tmp_path: Path) -> None:
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir(parents=True, exist_ok=True)
    update_state = tmp_path / "update-state.json"
    update_state.write_text(
        json.dumps(
            {
                "last_applied_deployment_id": "dep-1",
                "last_healthy_tag": "v1.2.3",
                "pending_boot_health": {"deployment_id": "dep-2"},
            }
        ),
        encoding="utf-8",
    )
    latest = {
        "manifest_id": "manifest-1",
        "artifact_sha256": "a" * 64,
        "status": "staged",
    }
    (stage_dir / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    manifest_dir = stage_dir / "manifest-1"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "metadata.json").write_text(json.dumps({"manifest_id": "manifest-1"}), encoding="utf-8")

    output = tmp_path / "report.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--device-id",
            "well-001",
            "--update-state-path",
            str(update_state),
            "--stage-dir",
            str(stage_dir),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr or proc.stdout
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["device_id"] == "well-001"
    assert report["update_state_exists"] is True
    assert report["latest_metadata_exists"] is True
    assert report["manifest_metadata_exists"] is True
    assert report["last_applied_deployment_id"] == "dep-1"
    assert report["last_healthy_tag"] == "v1.2.3"
    assert report["pending_boot_health"] == {"deployment_id": "dep-2"}
