from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_report(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise SystemExit("evidence json must decode to an object")
    return parsed


def evaluate(*, scenario: str, report: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []

    if not report.get("update_state_exists"):
        missing.append("update_state_exists")
    if not report.get("latest_metadata_exists"):
        missing.append("latest_metadata_exists")
    if not report.get("manifest_metadata_exists"):
        missing.append("manifest_metadata_exists")

    pending_boot_health = report.get("pending_boot_health")
    latest_metadata = report.get("latest_metadata") or {}

    if scenario == "good_release":
        if not report.get("last_applied_deployment_id"):
            missing.append("last_applied_deployment_id")
        if not report.get("last_healthy_tag"):
            missing.append("last_healthy_tag")
        if pending_boot_health:
            missing.append("pending_boot_health_cleared")
    elif scenario == "rollback_drill":
        if not report.get("last_failed_deployment_id"):
            missing.append("last_failed_deployment_id")
        if latest_metadata.get("status") != "rollback_requested":
            missing.append("latest_metadata.status=rollback_requested")
        if pending_boot_health:
            missing.append("pending_boot_health_cleared")
    else:
        raise SystemExit("scenario must be one of: good_release, rollback_drill")

    return {
        "scenario": scenario,
        "evidence_complete": len(missing) == 0,
        "missing_checks": missing,
        "device_id": report.get("device_id"),
        "last_applied_deployment_id": report.get("last_applied_deployment_id"),
        "last_healthy_tag": report.get("last_healthy_tag"),
        "last_failed_deployment_id": report.get("last_failed_deployment_id"),
        "latest_metadata_status": latest_metadata.get("status"),
        "note": "Evidence completeness is a gate aid only; final parity signoff still requires real-device operator review.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate collected system-image validation evidence")
    parser.add_argument("--scenario", required=True, choices=["good_release", "rollback_drill"])
    parser.add_argument("--evidence-json", required=True)
    args = parser.parse_args(argv)

    report = _load_report(Path(args.evidence_json))
    print(json.dumps(evaluate(scenario=args.scenario, report=report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
