from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def describe_drift(*, example_path: Path, current_path: Path, keys: Sequence[str], label: str) -> str | None:
    if not current_path.exists():
        return None

    example_values = _parse_env(example_path)
    current_values = _parse_env(current_path)

    drift_parts: list[str] = []
    for key in keys:
        expected = example_values.get(key)
        actual = current_values.get(key)
        if expected is None or actual is None or actual == expected:
            continue
        drift_parts.append(f"{key}={actual} (example: {expected})")

    if not drift_parts:
        return None

    joined = ", ".join(drift_parts)
    return (
        f"NOTE: preserving existing {label}; local demo settings differ from {example_path}: {joined}. "
        f"Remove {current_path} and rerun this target to adopt the current repo defaults."
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report local demo env drift without overwriting user files."
    )
    parser.add_argument("--example", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--keys", nargs="+", required=True)
    args = parser.parse_args(argv)

    message = describe_drift(
        example_path=Path(args.example),
        current_path=Path(args.current),
        keys=args.keys,
        label=args.label,
    )
    if message:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
