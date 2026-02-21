"""Create a clean distribution zip under ./dist.

This script is intentionally conservative about what it includes.

- If running from a git checkout, it prefers **tracked files only**.
- Otherwise, it falls back to a filesystem walk with aggressive excludes.

The output zip includes a single top-level folder:

  edgewatch-telemetry_vX.Y.Z/

so extraction is tidy.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import zipfile
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from api.app.version import __version__
DIST_DIR = REPO_ROOT / "dist"

ZIP_NAME = f"edgewatch-telemetry_v{__version__}.zip"
BASE_FOLDER = f"edgewatch-telemetry_v{__version__}"

# Directories to exclude (match on any path segment).
EXCLUDE_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".pnpm-store",
    "dist",
    "build",
    ".terraform",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".pyright",
    "__MACOSX",
}

# Explicit file names to exclude.
EXCLUDE_FILE_NAMES = {
    ".env",
    "edgewatch_policy_cache.json",
    "edgewatch_policy_cache_demo.json",
    "edgewatch_buffer.sqlite",
    "edgewatch_buffer.sqlite3",
    "terraform.tfstate",
    "terraform.tfstate.backup",
    ".DS_Store",
}

# File suffixes to exclude.
EXCLUDE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".log",
    ".tfstate",
}


def _git_tracked_files() -> list[Path]:
    """Return git-tracked files relative to REPO_ROOT, or empty list."""

    try:
        out = subprocess.check_output(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []

    files: list[Path] = []
    for line in out.decode("utf-8").splitlines():
        if not line.strip():
            continue
        files.append(Path(line.strip()))
    return files


def _should_exclude(rel: Path) -> bool:
    parts = rel.parts
    if any(p in EXCLUDE_DIR_NAMES for p in parts):
        return True

    name = rel.name
    if name in EXCLUDE_FILE_NAMES:
        return True

    # Exclude any .env.* secrets files.
    if name.startswith(".env.") and name not in {".env.example"}:
        return True

    # Common generated artifacts.
    if any(name.endswith(suf) for suf in EXCLUDE_SUFFIXES):
        return True

    # Exclude local buffers / caches produced by the agent.
    if name.startswith("edgewatch_policy_cache_") and name.endswith(".json"):
        return True
    if name.startswith("edgewatch_buffer") and (
        name.endswith(".sqlite") or name.endswith(".sqlite3") or name.endswith(".db")
    ):
        return True

    # Exclude tfstate variants.
    if name.startswith("terraform.tfstate"):
        return True

    return False


def _iter_repo_files() -> list[Path]:
    tracked = _git_tracked_files()
    if tracked:
        out: list[Path] = []
        for rel in tracked:
            abs_path = REPO_ROOT / rel
            if abs_path.is_file() and not _should_exclude(rel):
                out.append(rel)
        return out

    out: list[Path] = []
    for abs_path in REPO_ROOT.rglob("*"):
        if not abs_path.is_file():
            continue
        rel = abs_path.relative_to(REPO_ROOT)
        if _should_exclude(rel):
            continue
        out.append(rel)
    return out


def main() -> None:
    DIST_DIR.mkdir(exist_ok=True)
    out_path = DIST_DIR / ZIP_NAME
    if out_path.exists():
        out_path.unlink()

    files = _iter_repo_files()
    if not files:
        raise SystemExit("No files discovered to package. Are you in the repo root?")

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            abs_path = REPO_ROOT / rel
            arcname = str(Path(BASE_FOLDER) / rel)
            zf.write(abs_path, arcname=arcname)

    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
