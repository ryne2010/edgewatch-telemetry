from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Mapping

import yaml


MetricType = Literal["number", "string", "boolean"]


@dataclass(frozen=True)
class MetricSpec:
    key: str
    type: MetricType
    unit: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class TelemetryContract:
    version: str
    sha256: str
    metrics: dict[str, MetricSpec]

    def validate_metrics(self, metrics: Mapping[str, Any]) -> tuple[set[str], list[str]]:
        """Validate a metrics dict against the contract.

        Compatibility semantics:
        - Unknown keys are allowed (additive drift). They are returned as `unknown_keys`.
        - Known keys must match declared type (breaking drift). Type mismatches are returned as errors.

        Returns:
        - unknown_keys: set[str]
        - errors: list[str]
        """

        unknown_keys: set[str] = set()
        errors: list[str] = []

        for k, v in metrics.items():
            spec = self.metrics.get(k)
            if spec is None:
                unknown_keys.add(k)
                continue

            if v is None:
                continue

            ok = _value_matches_type(v, spec.type)
            if not ok:
                errors.append(f"metric '{k}' expected type '{spec.type}' but got '{type(v).__name__}'")

        return unknown_keys, errors


def _value_matches_type(value: Any, expected: MetricType) -> bool:
    if expected == "number":
        # bool is a subclass of int in Python; treat it as non-numeric for metrics.
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    return False


def _repo_root() -> Path:
    # api/app/contracts.py -> api/app -> api -> repo root
    return Path(__file__).resolve().parents[2]


def _contract_path(version: str) -> Path:
    # Version is also the filename, e.g. v1 -> contracts/telemetry/v1.yaml
    v = (version or "").strip()
    if not v:
        raise ValueError("contract version is empty")
    if "/" in v or ".." in v:
        raise ValueError("invalid contract version")
    return _repo_root() / "contracts" / "telemetry" / f"{v}.yaml"


@lru_cache(maxsize=8)
def load_telemetry_contract(version: str) -> TelemetryContract:
    path = _contract_path(version)
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()

    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError("telemetry contract must be a mapping")

    version_from_file = str(data.get("version") or version)

    metrics_raw = data.get("metrics") or {}
    if not isinstance(metrics_raw, dict):
        raise ValueError("telemetry contract 'metrics' must be a mapping")

    metrics: dict[str, MetricSpec] = {}
    for key, spec in metrics_raw.items():
        if not isinstance(key, str):
            continue
        if not isinstance(spec, dict):
            continue

        typ = spec.get("type")
        if typ not in {"number", "string", "boolean"}:
            raise ValueError(f"invalid metric type for '{key}': {typ!r}")

        metrics[key] = MetricSpec(
            key=key,
            type=typ,  # type: ignore[arg-type]
            unit=str(spec.get("unit")) if spec.get("unit") is not None else None,
            description=str(spec.get("description")) if spec.get("description") is not None else None,
        )

    return TelemetryContract(version=version_from_file, sha256=sha256, metrics=metrics)
