from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ota" / "evaluate_system_image_validation.py"


def test_evaluate_system_image_validation_good_release(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "device_id": "well-001",
                "update_state_exists": True,
                "latest_metadata_exists": True,
                "manifest_metadata_exists": True,
                "last_applied_deployment_id": "dep-1",
                "last_healthy_tag": "v1.2.3",
                "last_failed_deployment_id": None,
                "pending_boot_health": None,
                "latest_metadata": {"status": "staged"},
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--scenario", "good_release", "--evidence-json", str(evidence)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    report = json.loads(proc.stdout)
    assert report["evidence_complete"] is True
    assert report["missing_checks"] == []


def test_evaluate_system_image_validation_rollback_drill(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "device_id": "well-002",
                "update_state_exists": True,
                "latest_metadata_exists": True,
                "manifest_metadata_exists": True,
                "last_applied_deployment_id": "dep-2",
                "last_healthy_tag": "v1.2.2",
                "last_failed_deployment_id": "dep-3",
                "pending_boot_health": None,
                "latest_metadata": {"status": "rollback_requested"},
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--scenario", "rollback_drill", "--evidence-json", str(evidence)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    report = json.loads(proc.stdout)
    assert report["evidence_complete"] is True
    assert report["missing_checks"] == []
