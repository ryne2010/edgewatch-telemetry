#!/usr/bin/env python3
"""scripts/repo_hygiene.py

Repo hygiene checks that catch common "zip artifact" and portability gotchas.

Why this exists
- Prevent leaking environment-specific package index URLs into lockfiles.
- Prevent committing OS cruft (.DS_Store, __MACOSX) that causes noisy diffs.
- Provide a fast, dependency-free gate that can run in CI.

This script is intentionally conservative:
- It FAILS on clear problems (forbidden hosts / leaked credentials / OS cruft).
- It WARNS on optional improvements (missing pnpm-lock.yaml, etc.).

Run:
  python scripts/repo_hygiene.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List


REPO_ROOT = Path(__file__).resolve().parents[1]


# ---- Policy knobs -----------------------------------------------------------

# Domains / substrings that should never appear in committed artifacts.
FORBIDDEN_SUBSTRINGS = [
    # Internal execution environment / mirrors.
    "packages.applied-caas-gateway1.internal.api.openai.org",
    "internal.api.openai.org",
    # Common credential patterns in URLs.
    "@packages.",
    "reader:",
]

# File/dir patterns that shouldn't be committed.
OS_CRUFT_PATH_PARTS = {
    ".DS_Store",
    "__MACOSX",
}

# Generated artifacts are common during local development. We only fail hygiene
# checks if they are *tracked* by git (i.e., would be committed / shipped).
GENERATED_PATH_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".pyright",
}

GENERATED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
}


def _git_tracked_paths() -> set[str]:
    """Return repo-relative paths tracked by git.

    Pre-commit runs inside a git checkout. Using git-tracked paths lets us avoid
    failing the hook due to untracked runtime caches.
    """

    try:
        import subprocess

        out = subprocess.check_output(["git", "ls-files"], cwd=REPO_ROOT)
        return {line.strip() for line in out.decode("utf-8").splitlines() if line.strip()}
    except Exception:
        return set()

# Files we treat as text for substring scans.
TEXT_EXTENSIONS = {
    ".md",
    ".py",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".txt",
    ".lock",
    ".bak",
    ".ini",
    ".tf",
    ".tfvars",
    ".sh",
    ".env",
    "",
}

# Explicit text files regardless of extension.
TEXT_FILENAMES = {
    "uv.lock",
    "pnpm-lock.yaml",
    "Dockerfile",
    "Makefile",
}


@dataclass(frozen=True)
class Finding:
    level: str  # ERROR | WARN
    path: Path
    message: str


def _iter_repo_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        # Skip virtualenvs and big vendored folders.
        if any(part in {".venv", "web/node_modules", "web/dist", "infra/gcp/.terraform"} for part in p.parts):
            continue
        if p.is_file():
            yield p


def _is_text_file(p: Path) -> bool:
    if p.name in TEXT_FILENAMES:
        return True
    return p.suffix.lower() in TEXT_EXTENSIONS


def _read_text_safely(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        # If a file can't be read (permissions, etc.), treat as binary.
        return ""


def check_os_cruft(files: Iterable[Path]) -> List[Finding]:
    findings: List[Finding] = []
    tracked = _git_tracked_paths()
    for p in files:
        # 1) Always error on OS cruft (these files are never useful).
        if any(part in OS_CRUFT_PATH_PARTS for part in p.parts):
            findings.append(
                Finding(
                    level="ERROR",
                    path=p,
                    message="OS cruft detected (remove .DS_Store / __MACOSX artifacts).",
                )
            )

        # 2) Dev/runtime generated artifacts: fail only if tracked by git.
        is_generated = any(part in GENERATED_PATH_PARTS for part in p.parts) or (
            p.suffix.lower() in GENERATED_SUFFIXES
        )
        if is_generated and tracked:
            rel = str(p.relative_to(REPO_ROOT))
            if rel in tracked:
                findings.append(
                    Finding(
                        level="ERROR",
                        path=p,
                        message=(
                            "Generated artifact is tracked by git (remove from repo and add to .gitignore)."
                        ),
                    )
                )
    return findings


def check_forbidden_substrings(files: Iterable[Path]) -> List[Finding]:
    findings: List[Finding] = []
    for p in files:
        # This file intentionally contains the forbidden substrings as part of
        # the policy definition; don't self-flag.
        if p.resolve() == Path(__file__).resolve():
            continue
        if not _is_text_file(p):
            continue
        text = _read_text_safely(p)
        if not text:
            continue
        for needle in FORBIDDEN_SUBSTRINGS:
            if needle in text:
                findings.append(
                    Finding(
                        level="ERROR",
                        path=p,
                        message=f"Forbidden substring found: {needle}",
                    )
                )
    return findings


def check_optional_lockfiles() -> List[Finding]:
    findings: List[Finding] = []

    if not (REPO_ROOT / "uv.lock").exists():
        findings.append(
            Finding(
                level="WARN",
                path=REPO_ROOT / "uv.lock",
                message="uv.lock missing. For team reproducibility, commit uv.lock (make lock).",
            )
        )

    if not (REPO_ROOT / "pnpm-lock.yaml").exists():
        findings.append(
            Finding(
                level="WARN",
                path=REPO_ROOT / "pnpm-lock.yaml",
                message=(
                    "pnpm-lock.yaml missing. CI supports lockless installs, but for reproducibility "
                    "you should commit a lockfile once deps stabilize."
                ),
            )
        )

    return findings


def main() -> int:
    files = list(_iter_repo_files(REPO_ROOT))

    findings: List[Finding] = []
    findings += check_os_cruft(files)
    findings += check_forbidden_substrings(files)
    findings += check_optional_lockfiles()

    errors = [f for f in findings if f.level == "ERROR"]
    warns = [f for f in findings if f.level == "WARN"]

    if errors:
        print("\n== Repo hygiene: FAIL ==")
        for f in errors:
            rel = f.path.relative_to(REPO_ROOT)
            print(f"[ERROR] {rel}: {f.message}")
        if warns:
            print("\nWarnings:")
            for f in warns:
                rel = f.path.relative_to(REPO_ROOT)
                print(f"[WARN]  {rel}: {f.message}")
        return 1

    print("\n== Repo hygiene: OK ==")
    if warns:
        for f in warns:
            rel = f.path.relative_to(REPO_ROOT)
            print(f"[WARN] {rel}: {f.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
