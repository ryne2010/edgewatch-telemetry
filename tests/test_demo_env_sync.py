from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_demo_env_sync.py"


def _run_script(
    *, example: Path, current: Path, label: str, keys: list[str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--example",
            str(example),
            "--current",
            str(current),
            "--label",
            label,
            "--keys",
            *keys,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_demo_env_sync_is_silent_when_current_matches_example(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    current = tmp_path / ".env"
    example.write_text("DEMO_DEVICE_ID=baxter-1\nDEMO_FLEET_SIZE=11\n", encoding="utf-8")
    current.write_text("DEMO_DEVICE_ID=baxter-1\nDEMO_FLEET_SIZE=11\n", encoding="utf-8")

    completed = _run_script(
        example=example,
        current=current,
        label=".env",
        keys=["DEMO_DEVICE_ID", "DEMO_FLEET_SIZE"],
    )

    assert completed.returncode == 0
    assert completed.stdout == ""


def test_demo_env_sync_reports_drift_for_tracked_keys(tmp_path: Path) -> None:
    example = tmp_path / "agent.env.example"
    current = tmp_path / "agent.env"
    example.write_text(
        "EDGEWATCH_DEVICE_ID=baxter-1\nEDGEWATCH_DEVICE_TOKEN=dev-device-token-001\n", encoding="utf-8"
    )
    current.write_text(
        "EDGEWATCH_DEVICE_ID=demo-well-001\nEDGEWATCH_DEVICE_TOKEN=dev-device-token-001\n",
        encoding="utf-8",
    )

    completed = _run_script(
        example=example,
        current=current,
        label="agent/.env",
        keys=["EDGEWATCH_DEVICE_ID", "EDGEWATCH_DEVICE_TOKEN"],
    )

    assert completed.returncode == 0
    assert "NOTE: preserving existing agent/.env" in completed.stdout
    assert "EDGEWATCH_DEVICE_ID=demo-well-001 (example: baxter-1)" in completed.stdout
