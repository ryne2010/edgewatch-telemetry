#!/usr/bin/env python3
"""Validate outdoor camera pilot evidence and persist a qualification report."""

from __future__ import annotations

import argparse
import json
import math
import os
import stat
import tempfile
from pathlib import Path
from typing import Mapping

from agent.media.qualification import CameraQualificationEvidence, evaluate_camera_qualification


class CameraEvidenceError(ValueError):
    """Camera evidence is incomplete, malformed, or internally inconsistent."""


_FIELDS = {
    "schema_version",
    "works_without_internet",
    "works_without_cloud_account",
    "local_credentials_supported",
    "video_codec",
    "audio_codec",
    "ingress_rating",
    "power_interface",
    "first_media_seconds",
    "successful_power_cycles",
    "attempted_power_cycles",
    "automatic_stream_recovery",
    "recovery_observation_hours",
    "satellite_electronics_cost_usd",
}


def _boolean(raw: Mapping[str, object], key: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise CameraEvidenceError(f"{key} must be a boolean")
    return value


def _text(raw: Mapping[str, object], key: str, *, optional: bool = False) -> str | None:
    value = raw.get(key)
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise CameraEvidenceError(f"{key} must be bounded non-empty text")
    return value.strip()


def _number(raw: Mapping[str, object], key: str, *, minimum: float = 0) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CameraEvidenceError(f"{key} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise CameraEvidenceError(f"{key} must be finite and at least {minimum}")
    return result


def _integer(raw: Mapping[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CameraEvidenceError(f"{key} must be a non-negative integer")
    return value


def parse_camera_evidence(raw: object) -> CameraQualificationEvidence:
    if not isinstance(raw, Mapping) or not all(isinstance(key, str) for key in raw):
        raise CameraEvidenceError("camera evidence must be a JSON object")
    missing = sorted(_FIELDS - set(raw))
    unknown = sorted(set(raw) - _FIELDS)
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown: {', '.join(unknown)}")
        raise CameraEvidenceError("invalid camera evidence fields (" + "; ".join(details) + ")")
    if raw.get("schema_version") != 1:
        raise CameraEvidenceError("schema_version must be 1")
    attempted = _integer(raw, "attempted_power_cycles")
    successful = _integer(raw, "successful_power_cycles")
    if successful > attempted:
        raise CameraEvidenceError("successful_power_cycles cannot exceed attempted_power_cycles")
    first_media_raw = raw.get("first_media_seconds")
    if not isinstance(first_media_raw, list):
        raise CameraEvidenceError("first_media_seconds must be a list")
    first_media: list[float] = []
    for index, item in enumerate(first_media_raw):
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise CameraEvidenceError(f"first_media_seconds[{index}] must be numeric")
        value = float(item)
        if not math.isfinite(value) or value < 0:
            raise CameraEvidenceError(f"first_media_seconds[{index}] must be finite and non-negative")
        first_media.append(value)
    if len(first_media) != successful:
        raise CameraEvidenceError(
            "first_media_seconds must contain one observation for every successful power cycle"
        )
    return CameraQualificationEvidence(
        works_without_internet=_boolean(raw, "works_without_internet"),
        works_without_cloud_account=_boolean(raw, "works_without_cloud_account"),
        local_credentials_supported=_boolean(raw, "local_credentials_supported"),
        video_codec=str(_text(raw, "video_codec")),
        audio_codec=_text(raw, "audio_codec", optional=True),
        ingress_rating=str(_text(raw, "ingress_rating")),
        power_interface=str(_text(raw, "power_interface")),
        first_media_seconds=tuple(first_media),
        successful_power_cycles=successful,
        attempted_power_cycles=attempted,
        automatic_stream_recovery=_boolean(raw, "automatic_stream_recovery"),
        recovery_observation_hours=_number(raw, "recovery_observation_hours"),
        satellite_electronics_cost_usd=_number(raw, "satellite_electronics_cost_usd"),
    )


def _write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
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
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        raw = json.loads(args.input.read_text(encoding="utf-8"))
        evidence = parse_camera_evidence(raw)
        result = evaluate_camera_qualification(evidence)
        report: dict[str, object] = {
            "schema_version": 1,
            "status": "passed" if result.qualified else "failed",
            "failures": list(result.failures),
            "evidence": raw,
        }
        _write_report(args.output, report)
    except (OSError, UnicodeError, json.JSONDecodeError, CameraEvidenceError) as exc:
        print(f"Camera qualification failed: {exc}")
        return 2
    print(f"Camera qualification {report['status']}: report={args.output}")
    return 0 if result.qualified else 1


if __name__ == "__main__":
    raise SystemExit(main())
