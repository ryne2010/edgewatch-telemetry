#!/usr/bin/env python3
"""Run the Raspberry Pi gateway's 100-cycle LTE power qualification."""

from __future__ import annotations

import argparse
from pathlib import Path

from gateway_runtime.qualification import BoundHttpsProbe, GatewayLteQualifier, QualificationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=100)
    parser.add_argument("--interface", default="wwan0")
    parser.add_argument("--attach-timeout-s", type=float, default=180.0)
    parser.add_argument("--off-settle-s", type=float, default=10.0)
    parser.add_argument(
        "--probe-url",
        default="https://www.gstatic.com/generate_204",
        help="Credential-free HTTPS URL used only to prove the LTE data path.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("/var/lib/edgewatch-gateway/lte-qualification.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    qualifier = GatewayLteQualifier(
        report_path=args.report,
        data_probe=BoundHttpsProbe(args.interface, url=args.probe_url),
    )
    try:
        report = qualifier.run(
            cycles=args.cycles,
            attach_timeout_s=args.attach_timeout_s,
            off_settle_s=args.off_settle_s,
        )
    except QualificationError as exc:
        print(f"LTE power qualification failed: {exc}")
        return 1
    print(
        "LTE power qualification passed: "
        f"{report['completed_cycles']}/{report['required_cycles']} cycles; report={args.report}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
