"""Create a clean distribution zip.

This is useful when sharing the repo as an archive (e.g., with recruiters, as a demo,
for offline review, etc.).

Design goals:
- Exclude build artifacts, caches, node_modules, terraform state, and secrets
- Produce a stable, predictable zip path under ./dist/

Usage:
  python scripts/package_dist.py

Optional:
  DIST_NAME=edgewatch-telemetry_custom.zip python scripts/package_dist.py
"""

from __future__ import annotations

import os
import re
import sys
import zipfile
from pathlib import Path


EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".pyright",
    "node_modules",
    ".pnpm-store",
    "dist",
    "build",
    ".terraform",
    ".terraform.d",
}

EXCLUDE_FILES = {
    ".env",
    "edgewatch_buffer.sqlite",
    "edgewatch_policy_cache.json",
}

EXCLUDE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".tfstate",
    ".tfstate.backup",
}


def _read_version() -> str:
    # Prefer pyproject.toml (single source of truth)
    pyproject = Path("pyproject.toml")
    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8")
        m = re.search(r"^version\s*=\s*\"([^\"]+)\"", text, re.MULTILINE)
        if m:
            return m.group(1)
    return "0.0.0"


def _should_exclude(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDE_DIRS:
        return True

    if path.name in EXCLUDE_FILES:
        return True

    if path.suffix in EXCLUDE_SUFFIXES:
        return True

    # Common secret patterns
    if path.name.endswith(".pem") or path.name.endswith(".key"):
        return True

    # Frontend build output
    if "web" in path.parts and path.parts[-2:] == ("web", "dist"):
        return True

    return False


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    os.chdir(repo_root)

    version = _read_version()
    dist_dir = Path("dist")
    dist_dir.mkdir(exist_ok=True)

    dist_name = os.environ.get("DIST_NAME")
    if not dist_name:
        dist_name = f"edgewatch-telemetry_v{version}.zip"

    out_path = dist_dir / dist_name

    # Collect files
    files: list[Path] = []
    for p in Path(".").rglob("*"):
        if p.is_dir():
            continue
        if _should_exclude(p):
            continue
        files.append(p)

    files.sort(key=lambda p: str(p))

    # Create zip
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, arcname=str(p))

    print(f"Wrote {out_path} ({len(files)} files)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
