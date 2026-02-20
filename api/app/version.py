from __future__ import annotations

import tomllib
from importlib import metadata
from pathlib import Path


_DIST_NAME = "edgewatch-telemetry"


def get_version() -> str:
    """Return the repo version.

    Prefer the installed distribution metadata (works in Docker/venv).
    Fall back to reading pyproject.toml so `python api/app/main.py` still shows a version
    even when the project isn't installed.
    """

    try:
        return metadata.version(_DIST_NAME)
    except metadata.PackageNotFoundError:
        pass

    # Fallback: read pyproject.toml from repo root.
    repo_root = Path(__file__).resolve().parents[2]
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        return "0.0.0"

    try:
        data = tomllib.loads(pyproject.read_text("utf-8"))
        project = data.get("project") or {}
        v = project.get("version")
        return str(v) if v else "0.0.0"
    except Exception:
        return "0.0.0"


__version__ = get_version()
