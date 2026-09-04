from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from scripts.camera_qualify import CameraEvidenceError, main, parse_camera_evidence


def _evidence() -> dict[str, object]:
    return {
        "schema_version": 1,
        "works_without_internet": True,
        "works_without_cloud_account": True,
        "local_credentials_supported": True,
        "video_codec": "h264",
        "audio_codec": "aac",
        "ingress_rating": "IP67",
        "power_interface": "poe",
        "first_media_seconds": [30.0] * 99,
        "successful_power_cycles": 99,
        "attempted_power_cycles": 100,
        "automatic_stream_recovery": True,
        "recovery_observation_hours": 24,
        "satellite_electronics_cost_usd": 199.99,
    }


def test_parser_rejects_inconsistent_or_open_evidence() -> None:
    inconsistent = _evidence()
    inconsistent["successful_power_cycles"] = 100
    with pytest.raises(CameraEvidenceError, match="one observation"):
        parse_camera_evidence(inconsistent)

    unknown = _evidence()
    unknown["cloud_password"] = "secret"
    with pytest.raises(CameraEvidenceError, match="unknown"):
        parse_camera_evidence(unknown)


def test_cli_writes_private_passing_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "camera-evidence.json"
    report = tmp_path / "camera-report.json"
    source.write_text(json.dumps(_evidence()), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["camera-qualify", "--input", str(source), "--output", str(report)],
    )

    assert main() == 0
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "passed"
    assert stat.S_IMODE(report.stat().st_mode) == 0o600


def test_cli_records_failed_gate_and_returns_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evidence = _evidence()
    evidence["works_without_internet"] = False
    source = tmp_path / "camera-evidence.json"
    report = tmp_path / "camera-report.json"
    source.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["camera-qualify", "--input", str(source), "--output", str(report)],
    )

    assert main() == 1
    persisted = json.loads(report.read_text(encoding="utf-8"))
    assert persisted["status"] == "failed"
    assert "camera requires Internet access" in persisted["failures"]
