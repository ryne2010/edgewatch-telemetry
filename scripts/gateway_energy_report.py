#!/usr/bin/env python3
"""Validate measured gateway energy and calculate battery/solar requirements."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from gateway_runtime.energy import EnergyQualificationError, build_energy_report


def _write_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Meter evidence JSON file")
    parser.add_argument("--output", type=Path, required=True, help="Durable report JSON file")
    parser.add_argument(
        "--minimum-daily-samples",
        type=int,
        default=7,
        help="Use 1 for the initial 24-hour benchmark; production qualification defaults to 7.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        raw = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise EnergyQualificationError("energy input must be a JSON object")
        report = build_energy_report(raw, minimum_daily_samples=args.minimum_daily_samples)
        _write_report(args.output, report)
    except (OSError, json.JSONDecodeError, EnergyQualificationError) as exc:
        print(f"Gateway energy qualification failed: {exc}")
        return 2
    print(
        f"Gateway energy qualification {report['status']}: "
        f"P95={report['p95_daily_energy_wh']} Wh/day, "
        f"average={report['p95_average_power_w']} W, report={args.output}"
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
