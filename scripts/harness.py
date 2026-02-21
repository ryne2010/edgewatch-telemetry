#!/usr/bin/env python3
"""
scripts/harness.py

A lightweight execution harness for agent-first repositories.

Design goals
- One entrypoint for fmt/lint/typecheck/test/build across polyglot repos.
- Prefer explicit commands in harness.toml when provided.
- Otherwise, auto-detect *multiple* applicable steps (Python/TS/Go/Rust) and run them.
- Prefer `uv` for Python and `pnpm` for TypeScript/Node when configured.

Usage:
  python scripts/harness.py lint
  python scripts/harness.py test
  python scripts/harness.py typecheck
  python scripts/harness.py all
  python scripts/harness.py doctor

Options:
  --strict      Treat SKIP as failure (useful for CI gating)
  --dry-run     Print commands without executing
  --keep-going  Run all steps even if some fail (default respects harness.fail_fast)
  --only        Comma-separated ecosystems to run (precommit,python,node,go,rust)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Tuple,
)  # tomllib is stdlib in Python 3.11+. Fallback to tomli for older versions.

try:
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_TOML = REPO_ROOT / "harness.toml"


# ----------------------------
# Models
# ----------------------------


@dataclass(frozen=True)
class Step:
    ecosystem: str  # precommit | python | node | go | rust
    name: str
    command: Optional[str] = None
    kind: str = "shell"  # shell | gofmt_check | gofmt_apply
    reason: str = ""
    skip_reason: Optional[str] = None
    cwd: Path = REPO_ROOT


@dataclass(frozen=True)
class StepResult:
    step: Step
    status: str  # PASS | FAIL | SKIP
    returncode: int
    details: Optional[str] = None


# ----------------------------
# Utilities
# ----------------------------


def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _read_toml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        data = tomllib.load(f)
        return data if isinstance(data, dict) else {}


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(_read_text(path))
    except json.JSONDecodeError:
        return {}
    except FileNotFoundError:
        return {}


def _print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def _run_shell(command: str, *, cwd: Path, dry_run: bool) -> int:
    if dry_run:
        print(f"[dry-run] $ {command}")
        return 0
    print(f"$ {command}")
    completed = subprocess.run(command, shell=True, cwd=str(cwd))
    return completed.returncode


def _run_capture(args: Sequence[str], *, cwd: Path) -> Tuple[int, str, str]:
    completed = subprocess.run(
        list(args),
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _chunked(seq: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _is_git_repo() -> bool:
    """Return True when REPO_ROOT is inside a git work tree.

    Why we care: some tools (notably pre-commit) require an actual git repo.
    When users unzip an artifact without the .git directory, we should degrade
    gracefully rather than failing repo-quality gates.
    """

    if (REPO_ROOT / ".git").exists():
        return True
    if not _which("git"):
        return False
    rc, out, _ = _run_capture(["git", "rev-parse", "--is-inside-work-tree"], cwd=REPO_ROOT)
    return rc == 0 and out.strip().lower() == "true"


def _git_ls_files(pattern: str) -> List[str]:
    if not _which("git"):
        return []
    rc, out, _ = _run_capture(["git", "ls-files", "--", pattern], cwd=REPO_ROOT)
    if rc != 0:
        return []
    files = [line.strip() for line in out.splitlines() if line.strip()]
    return files


def _has_any(paths: Sequence[Path]) -> bool:
    return any(p.exists() for p in paths)


# ----------------------------
# Detection helpers
# ----------------------------


def _detect_python_project() -> bool:
    return _has_any(
        [
            REPO_ROOT / "pyproject.toml",
            REPO_ROOT / "requirements.txt",
            REPO_ROOT / "setup.py",
            REPO_ROOT / "setup.cfg",
        ]
    )


def _detect_node_project() -> bool:
    return (REPO_ROOT / "package.json").exists()


def _detect_go_project() -> bool:
    return (REPO_ROOT / "go.mod").exists()


def _detect_rust_project() -> bool:
    return (REPO_ROOT / "Cargo.toml").exists()


def _python_has_table(pyproject: Dict[str, Any], dotted: str) -> bool:
    cur: Any = pyproject
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return False
        if part not in cur:
            return False
        cur = cur[part]
    return True


def _load_pyproject() -> Dict[str, Any]:
    path = REPO_ROOT / "pyproject.toml"
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _python_uses_pytest(pyproject: Dict[str, Any]) -> bool:
    if (REPO_ROOT / "pytest.ini").exists():
        return True
    if (REPO_ROOT / "conftest.py").exists():
        return True
    if _python_has_table(pyproject, "tool.pytest.ini_options"):
        return True
    tests_dir = REPO_ROOT / "tests"
    if tests_dir.exists():
        for p in tests_dir.rglob("test_*.py"):
            return True
        for p in tests_dir.rglob("*_test.py"):
            return True
    return False


def _python_has_any_tests() -> bool:
    """Heuristic to avoid running pytest in repos with zero tests.

    Pytest exits non-zero when it collects no tests. This helper is conservative: it only
    returns True when we see a plausible test file in a conventional location.
    """
    tests_dir = REPO_ROOT / "tests"
    if tests_dir.exists():
        # common pytest conventions
        if any(tests_dir.rglob("test_*.py")):
            return True
        if any(tests_dir.rglob("*_test.py")):
            return True
        # any python file in tests/ is a decent signal
        if any(tests_dir.rglob("*.py")):
            return True

    # Light-weight fallback scan (avoid heavy dirs)
    skip_dirs = {
        ".git",
        ".venv",
        "venv",
        ".tox",
        "node_modules",
        "dist",
        "build",
        "out",
        ".mypy_cache",
        ".pytest_cache",
    }
    for p in REPO_ROOT.rglob("*.py"):
        if any(part in skip_dirs for part in p.parts):
            continue
        name = p.name
        if name.startswith("test_") or name.endswith("_test.py"):
            return True
    return False


def _python_has_mypy(pyproject: Dict[str, Any]) -> bool:
    return (
        (REPO_ROOT / "mypy.ini").exists()
        or (REPO_ROOT / ".mypy.ini").exists()
        or _python_has_table(pyproject, "tool.mypy")
    )


def _python_has_pyright() -> bool:
    return (REPO_ROOT / "pyrightconfig.json").exists()


def _python_has_ruff(pyproject: Dict[str, Any]) -> bool:
    if _python_has_table(pyproject, "tool.ruff"):
        return True
    return _has_any([REPO_ROOT / "ruff.toml", REPO_ROOT / ".ruff.toml"])


def _python_has_black(pyproject: Dict[str, Any]) -> bool:
    if _python_has_table(pyproject, "tool.black"):
        return True
    return _has_any([REPO_ROOT / "pyproject.toml"])  # black commonly configured here; keep conservative? no


def _node_is_workspace(pkg: Dict[str, Any]) -> bool:
    if (REPO_ROOT / "pnpm-workspace.yaml").exists():
        return True
    workspaces = pkg.get("workspaces")
    return isinstance(workspaces, (list, dict))


def _node_package_manager(pkg: Dict[str, Any]) -> str:
    pm = pkg.get("packageManager")
    if isinstance(pm, str):
        # "pnpm@9.6.0" etc
        return pm.split("@", 1)[0].strip()
    return ""


def _node_has_script(pkg: Dict[str, Any], name: str) -> bool:
    scripts = pkg.get("scripts", {})
    return (
        isinstance(scripts, dict)
        and name in scripts
        and isinstance(scripts[name], str)
        and scripts[name].strip() != ""
    )


def _detect_node_configs() -> Dict[str, bool]:
    # Only used for fallbacks when scripts are missing
    return {
        "tsconfig": (REPO_ROOT / "tsconfig.json").exists(),
        "eslint": _has_any(
            [
                REPO_ROOT / ".eslintrc",
                REPO_ROOT / ".eslintrc.json",
                REPO_ROOT / ".eslintrc.js",
                REPO_ROOT / ".eslintrc.cjs",
                REPO_ROOT / ".eslintrc.yaml",
                REPO_ROOT / ".eslintrc.yml",
                REPO_ROOT / "eslint.config.js",
                REPO_ROOT / "eslint.config.mjs",
                REPO_ROOT / "eslint.config.cjs",
            ]
        ),
        "vitest": _has_any(
            [
                REPO_ROOT / "vitest.config.ts",
                REPO_ROOT / "vitest.config.js",
                REPO_ROOT / "vitest.config.mjs",
                REPO_ROOT / "vitest.config.cjs",
            ]
        ),
        "jest": _has_any(
            [
                REPO_ROOT / "jest.config.ts",
                REPO_ROOT / "jest.config.js",
                REPO_ROOT / "jest.config.mjs",
                REPO_ROOT / "jest.config.cjs",
            ]
        ),
    }


def _has_golangci_config() -> bool:
    return _has_any(
        [
            REPO_ROOT / ".golangci.yml",
            REPO_ROOT / ".golangci.yaml",
            REPO_ROOT / ".golangci.toml",
            REPO_ROOT / ".golangci.json",
        ]
    )


def _cargo_subcommand_available(subcmd: str) -> bool:
    if not _which("cargo"):
        return False
    rc, _, _ = _run_capture(["cargo", subcmd, "--version"], cwd=REPO_ROOT)
    return rc == 0


# ----------------------------
# Config + runners
# ----------------------------


def _cfg_get(cfg: Dict[str, Any], path: str, default: Any) -> Any:
    cur: Any = cfg
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _python_runner(cfg: Dict[str, Any]) -> str:
    pref = str(_cfg_get(cfg, "autodetect.python_runner", "auto")).strip().lower()
    if pref == "python":
        return "python"
    if pref in ("uv", "auto"):
        if _which("uv"):
            return "uv"
    return "python"


def _python_default(cfg: Dict[str, Any], key: str, default: str = "auto") -> str:
    """Read opinionated Python defaults from harness.toml.

    Keys live under [autodetect.python]. Values are normalized to lowercase.
    Use 'auto' to keep behavior conservative (config-driven).
    """
    val = str(_cfg_get(cfg, f"autodetect.python.{key}", default)).strip().lower()
    return val


def _node_runner(cfg: Dict[str, Any], pkg: Dict[str, Any]) -> str:
    """Pick a Node package manager.

    Important nuance:
    - If a repo declares a specific package manager (e.g. `packageManager: pnpm@...`),
      we should not silently fall back to npm/yarn. Many scripts call pnpm directly.
    - Missing tooling is handled by `_plan_node` using SKIP semantics.
    """

    pref = str(_cfg_get(cfg, "autodetect.node_runner", "auto")).strip().lower()
    pm = _node_package_manager(pkg)

    def has(lock: str) -> bool:
        return (REPO_ROOT / lock).exists()

    # Strong signals (do NOT fall back)
    if pref == "pnpm" or pm == "pnpm" or has("pnpm-lock.yaml") or has("pnpm-workspace.yaml"):
        return "pnpm"
    if pref == "yarn" or pm == "yarn" or has("yarn.lock"):
        return "yarn"

    # Default
    return "npm"


# ----------------------------
# Planning: explicit overrides
# ----------------------------


def _explicit_steps_for_task(cfg: Dict[str, Any], task: str) -> Optional[List[Step]]:
    commands = cfg.get("commands", {})
    if not isinstance(commands, dict):
        return None
    raw = commands.get(task)
    if raw is None:
        return None

    if isinstance(raw, str):
        if raw.strip() == "":
            return None
        return [
            Step(
                ecosystem="explicit", name=f"{task}", command=raw.strip(), reason="configured in harness.toml"
            )
        ]
    if isinstance(raw, list):
        cleaned = [str(x).strip() for x in raw if str(x).strip() != ""]
        if not cleaned:
            return None
        return [
            Step(
                ecosystem="explicit", name=f"{task}:{i + 1}", command=cmd, reason="configured in harness.toml"
            )
            for i, cmd in enumerate(cleaned)
        ]
    return None


# ----------------------------
# Planning: auto-detection
# ----------------------------


def _plan_precommit(cfg: Dict[str, Any], task: str) -> List[Step]:
    if task not in ("lint", "fmt"):
        return []
    pcfg = REPO_ROOT / ".pre-commit-config.yaml"
    if not pcfg.exists():
        return []
    if not _is_git_repo():
        return [
            Step(
                ecosystem="precommit",
                name="pre-commit",
                skip_reason="not a git repository (.git missing)",
                reason="detected .pre-commit-config.yaml",
            )
        ]
    # Prefer native pre-commit if available; fallback to uv run pre-commit.
    if _which("pre-commit"):
        cmd = "pre-commit run --all-files"
        return [
            Step(
                ecosystem="precommit",
                name="pre-commit",
                command=cmd,
                reason="detected .pre-commit-config.yaml",
            )
        ]
    if _which("uv"):
        cmd = "uv run --locked pre-commit run --all-files"
        return [
            Step(
                ecosystem="precommit",
                name="pre-commit",
                command=cmd,
                reason="detected .pre-commit-config.yaml (via uv)",
            )
        ]
    return [
        Step(
            ecosystem="precommit",
            name="pre-commit",
            skip_reason="pre-commit not installed",
            reason="detected .pre-commit-config.yaml",
        )
    ]


def _plan_python(cfg: Dict[str, Any], task: str) -> List[Step]:
    if not _detect_python_project():
        return []
    runner = _python_runner(cfg)
    pyproject = _load_pyproject()

    default_linter = _python_default(cfg, "linter", "auto")
    default_formatter = _python_default(cfg, "formatter", "auto")
    default_typechecker = _python_default(cfg, "typechecker", "auto")
    default_testrunner = _python_default(cfg, "testrunner", "auto")

    def run(tool_cmd: str) -> str:
        if runner == "uv":
            return f"uv run --locked {tool_cmd}"
        return tool_cmd

    steps: List[Step] = []

    if task == "lint":
        want_ruff = _python_has_ruff(pyproject) or default_linter == "ruff"
        if want_ruff:
            reason = (
                "ruff config detected" if _python_has_ruff(pyproject) else "default linter (harness.toml)"
            )
            steps.append(
                Step(ecosystem="python", name="ruff check", command=run("ruff check ."), reason=reason)
            )
            steps.append(
                Step(
                    ecosystem="python",
                    name="ruff format --check",
                    command=run("ruff format --check ."),
                    reason="keep formatting stable",
                )
            )
        else:
            steps.append(
                Step(
                    ecosystem="python",
                    name="lint",
                    skip_reason="no linter configured (set autodetect.python.linter)",
                    reason="python project detected",
                )
            )
    elif task == "fmt":
        want_formatter = _python_has_ruff(pyproject) or default_formatter == "ruff"
        if want_formatter:
            reason = (
                "ruff config detected" if _python_has_ruff(pyproject) else "default formatter (harness.toml)"
            )
            steps.append(
                Step(ecosystem="python", name="ruff format", command=run("ruff format ."), reason=reason)
            )
        else:
            steps.append(
                Step(
                    ecosystem="python",
                    name="fmt",
                    skip_reason="no formatter configured (set autodetect.python.formatter)",
                    reason="python project detected",
                )
            )
    elif task == "typecheck":
        want_pyright = _python_has_pyright() or default_typechecker == "pyright"
        want_mypy = _python_has_mypy(pyproject) or default_typechecker == "mypy"
        if want_pyright:
            reason = (
                "pyrightconfig.json detected"
                if _python_has_pyright()
                else "default typechecker (harness.toml)"
            )
            steps.append(Step(ecosystem="python", name="pyright", command=run("pyright"), reason=reason))
        elif want_mypy:
            reason = (
                "mypy config detected"
                if _python_has_mypy(pyproject)
                else "default typechecker (harness.toml)"
            )
            steps.append(Step(ecosystem="python", name="mypy", command=run("mypy ."), reason=reason))
        else:
            steps.append(
                Step(
                    ecosystem="python",
                    name="typecheck",
                    skip_reason="no typechecker configured (set autodetect.python.typechecker)",
                    reason="python project detected",
                )
            )
    elif task == "test":
        want_pytest = _python_uses_pytest(pyproject) or default_testrunner == "pytest"
        if want_pytest and _python_has_any_tests():
            # Prefer pytest entrypoint; uv run resolves the venv.
            cmd = run("pytest") if runner == "uv" else "python -m pytest"
            reason = (
                "pytest signals detected"
                if _python_uses_pytest(pyproject)
                else "default testrunner (harness.toml)"
            )
            steps.append(Step(ecosystem="python", name="pytest", command=cmd, reason=reason))
        else:
            tests_dir = REPO_ROOT / "tests"
            if tests_dir.exists():
                steps.append(
                    Step(
                        ecosystem="python",
                        name="unittest",
                        command="python -m unittest discover",
                        reason="tests/ directory detected",
                    )
                )
            else:
                steps.append(
                    Step(
                        ecosystem="python",
                        name="tests",
                        skip_reason="no test files detected",
                        reason="python project detected",
                    )
                )
    elif task == "build":
        # No universal Python build step; keep conservative.
        steps.append(
            Step(
                ecosystem="python",
                name="build",
                skip_reason="no default python build step",
                reason="python project detected",
            )
        )

    # If runner is uv but uv is missing, convert runnable steps to SKIP unless strict overrides.
    if runner == "uv" and not _which("uv"):
        adjusted: List[Step] = []
        for s in steps:
            if s.command and s.command.startswith("uv run "):
                adjusted.append(Step(**{**s.__dict__, "command": None, "skip_reason": "uv not installed"}))  # type: ignore
            else:
                adjusted.append(s)
        steps = adjusted

    return steps


def _plan_node(cfg: Dict[str, Any], task: str) -> List[Step]:
    if not _detect_node_project():
        return []
    pkg = _read_json(REPO_ROOT / "package.json")
    runner = _node_runner(cfg, pkg)
    skip_missing = bool(_cfg_get(cfg, "autodetect.skip_missing_tools", True))

    if runner == "pnpm" and not _which("pnpm"):
        if skip_missing:
            return [
                Step(
                    ecosystem="node",
                    name="pnpm",
                    skip_reason="pnpm not installed",
                    reason="packageManager/lockfiles indicate pnpm",
                )
            ]
    if runner == "yarn" and not _which("yarn"):
        if skip_missing:
            return [
                Step(
                    ecosystem="node",
                    name="yarn",
                    skip_reason="yarn not installed",
                    reason="packageManager/lockfiles indicate yarn",
                )
            ]
    if runner == "npm" and not _which("npm"):
        if skip_missing:
            return [
                Step(
                    ecosystem="node",
                    name="npm",
                    skip_reason="npm not installed",
                    reason="node project detected",
                )
            ]

    # Some environments expose pnpm via a corepack shim. If pnpm cannot execute
    # (e.g., corepack cannot download in an offline environment), treat it as missing
    # when skip_missing_tools is enabled.
    if runner == "pnpm":
        rc, _, _ = _run_capture(["pnpm", "--version"], cwd=REPO_ROOT)
        if rc != 0 and skip_missing:
            return [
                Step(
                    ecosystem="node",
                    name="pnpm",
                    skip_reason="pnpm unavailable",
                    reason="pnpm runner selected but pnpm --version failed",
                )
            ]
    if runner == "yarn":
        rc, _, _ = _run_capture(["yarn", "--version"], cwd=REPO_ROOT)
        if rc != 0 and skip_missing:
            return [
                Step(
                    ecosystem="node",
                    name="yarn",
                    skip_reason="yarn unavailable",
                    reason="yarn runner selected but yarn --version failed",
                )
            ]

    configs = _detect_node_configs()
    workspace = bool(_cfg_get(cfg, "autodetect.node_recursive", True)) and _node_is_workspace(pkg)

    def pnpm_run(script: str) -> str:
        if workspace:
            return f"pnpm -r --if-present {script}"
        return f"pnpm {script}"

    def yarn_run(script: str) -> str:
        if workspace:
            # yarn workspaces foreach (berry) is different; keep conservative
            return f"yarn {script}"
        return f"yarn {script}"

    def npm_run(script: str) -> str:
        return f"npm run {script}"

    def exec_cmd(bin_cmd: str) -> str:
        if runner == "pnpm":
            return f"pnpm exec {bin_cmd}"
        if runner == "yarn":
            return f"yarn {bin_cmd}"
        # npm: prefer npx
        return f"npx -y {bin_cmd}"

    steps: List[Step] = []

    # Map harness tasks to conventional script names
    script_candidates: Dict[str, List[str]] = {
        "fmt": ["format", "fmt"],
        "lint": ["lint"],
        "typecheck": ["typecheck"],
        "test": ["test"],
        "build": ["build"],
    }

    if task in script_candidates:
        candidates = script_candidates[task]
        # Workspace: run recursively with --if-present for each candidate (fmt may have 2).
        if workspace and runner == "pnpm":
            for script in candidates:
                steps.append(
                    Step(
                        ecosystem="node",
                        name=f"pnpm:{script}",
                        command=pnpm_run(script),
                        reason="pnpm workspace (recursive --if-present)",
                    )
                )
            return steps

        # Non-workspace or non-pnpm: prefer root scripts when present.
        for script in candidates:
            if _node_has_script(pkg, script):
                if runner == "pnpm":
                    steps.append(
                        Step(
                            ecosystem="node",
                            name=f"pnpm:{script}",
                            command=pnpm_run(script),
                            reason="package.json script",
                        )
                    )
                elif runner == "yarn":
                    steps.append(
                        Step(
                            ecosystem="node",
                            name=f"yarn:{script}",
                            command=yarn_run(script),
                            reason="package.json script",
                        )
                    )
                else:
                    steps.append(
                        Step(
                            ecosystem="node",
                            name=f"npm:{script}",
                            command=npm_run(script),
                            reason="package.json script",
                        )
                    )
                return steps

        # Fallbacks when scripts are missing (only when config files suggest intent)
        if task == "typecheck" and configs["tsconfig"]:
            steps.append(
                Step(
                    ecosystem="node",
                    name="tsc --noEmit",
                    command=exec_cmd("tsc -p tsconfig.json --noEmit"),
                    reason="tsconfig.json detected",
                )
            )
            return steps
        if task == "lint" and configs["eslint"]:
            steps.append(
                Step(
                    ecosystem="node",
                    name="eslint",
                    command=exec_cmd("eslint ."),
                    reason="eslint config detected",
                )
            )
            return steps
        if task == "test" and configs["vitest"]:
            steps.append(
                Step(
                    ecosystem="node",
                    name="vitest",
                    command=exec_cmd("vitest run"),
                    reason="vitest config detected",
                )
            )
            return steps
        if task == "test" and configs["jest"]:
            steps.append(
                Step(ecosystem="node", name="jest", command=exec_cmd("jest"), reason="jest config detected")
            )
            return steps

        steps.append(
            Step(
                ecosystem="node",
                name=task,
                skip_reason="no script/config detected",
                reason="node project detected",
            )
        )
        return steps

    return []


def _plan_go(cfg: Dict[str, Any], task: str) -> List[Step]:
    if not _detect_go_project():
        return []
    steps: List[Step] = []
    use_golangci = str(_cfg_get(cfg, "autodetect.go_use_golangci_lint", "auto")).strip().lower()

    def want_golangci() -> bool:
        if use_golangci == "true":
            return True
        if use_golangci == "false":
            return False
        return _has_golangci_config()

    if task == "lint":
        # gofmt check (tracked files only, to avoid vendor/)
        steps.append(
            Step(ecosystem="go", name="gofmt --check", kind="gofmt_check", reason="standard go formatting")
        )
        steps.append(Step(ecosystem="go", name="go vet", command="go vet ./...", reason="static analysis"))
        if want_golangci():
            if _which("golangci-lint"):
                steps.append(
                    Step(
                        ecosystem="go",
                        name="golangci-lint",
                        command="golangci-lint run",
                        reason="golangci config detected",
                    )
                )
            else:
                steps.append(
                    Step(
                        ecosystem="go",
                        name="golangci-lint",
                        skip_reason="golangci-lint not installed",
                        reason="golangci config detected",
                    )
                )
    elif task == "fmt":
        steps.append(Step(ecosystem="go", name="gofmt", kind="gofmt_apply", reason="standard go formatting"))
    elif task == "typecheck":
        steps.append(
            Step(
                ecosystem="go",
                name="compile",
                command="go test -run=^$ ./...",
                reason="compile-only typecheck",
            )
        )
    elif task == "test":
        steps.append(Step(ecosystem="go", name="go test", command="go test ./...", reason="go.mod detected"))
    elif task == "build":
        steps.append(
            Step(ecosystem="go", name="go build", command="go build ./...", reason="go.mod detected")
        )
    return steps


def _plan_rust(cfg: Dict[str, Any], task: str) -> List[Step]:
    if not _detect_rust_project():
        return []
    steps: List[Step] = []
    use_clippy = str(_cfg_get(cfg, "autodetect.rust_use_clippy", "auto")).strip().lower()

    def want_clippy() -> bool:
        if use_clippy == "true":
            return True
        if use_clippy == "false":
            return False
        # Auto: only if clippy subcommand is available
        return _cargo_subcommand_available("clippy")

    if task == "lint":
        if _cargo_subcommand_available("fmt"):
            steps.append(
                Step(
                    ecosystem="rust",
                    name="cargo fmt --check",
                    command="cargo fmt --all --check",
                    reason="rustfmt available",
                )
            )
        else:
            steps.append(
                Step(
                    ecosystem="rust",
                    name="cargo fmt",
                    skip_reason="rustfmt not available",
                    reason="Cargo.toml detected",
                )
            )
        if want_clippy():
            steps.append(
                Step(
                    ecosystem="rust",
                    name="cargo clippy",
                    command="cargo clippy --all-targets --all-features -- -D warnings",
                    reason="clippy available",
                )
            )
        else:
            steps.append(
                Step(
                    ecosystem="rust",
                    name="cargo clippy",
                    skip_reason="clippy not available",
                    reason="Cargo.toml detected",
                )
            )
    elif task == "fmt":
        if _cargo_subcommand_available("fmt"):
            steps.append(
                Step(
                    ecosystem="rust", name="cargo fmt", command="cargo fmt --all", reason="rustfmt available"
                )
            )
        else:
            steps.append(
                Step(
                    ecosystem="rust",
                    name="cargo fmt",
                    skip_reason="rustfmt not available",
                    reason="Cargo.toml detected",
                )
            )
    elif task == "typecheck":
        steps.append(
            Step(
                ecosystem="rust",
                name="cargo check",
                command="cargo check --all-targets --all-features",
                reason="Cargo.toml detected",
            )
        )
    elif task == "test":
        steps.append(
            Step(
                ecosystem="rust", name="cargo test", command="cargo test --all", reason="Cargo.toml detected"
            )
        )
    elif task == "build":
        steps.append(
            Step(
                ecosystem="rust",
                name="cargo build",
                command="cargo build --all",
                reason="Cargo.toml detected",
            )
        )
    return steps


def plan_task(cfg: Dict[str, Any], task: str, *, only: Optional[Sequence[str]] = None) -> List[Step]:
    explicit = _explicit_steps_for_task(cfg, task)
    if explicit is not None:
        return explicit

    allowed = set([x.strip() for x in (only or []) if x.strip()])

    def ok(ecosystem: str) -> bool:
        return True if not allowed else ecosystem in allowed

    steps: List[Step] = []
    if ok("precommit"):
        steps.extend(_plan_precommit(cfg, task))
    if ok("python"):
        steps.extend(_plan_python(cfg, task))
    if ok("node"):
        steps.extend(_plan_node(cfg, task))
    if ok("go"):
        steps.extend(_plan_go(cfg, task))
    if ok("rust"):
        steps.extend(_plan_rust(cfg, task))

    # If nothing planned, return a single SKIP placeholder.
    if not steps:
        steps.append(
            Step(
                ecosystem="harness",
                name=task,
                skip_reason="no matching projects detected",
                reason="auto-detection",
            )
        )
    return steps


# ----------------------------
# Execution
# ----------------------------


def _run_gofmt(kind: str) -> StepResult:
    # Use tracked files if possible to avoid vendor/ and generated junk.
    files: List[str] = []
    if _which("git"):
        files = _git_ls_files("*.go")
    if not files:
        # fallback: best-effort recursive scan excluding vendor/.git
        for p in REPO_ROOT.rglob("*.go"):
            if any(part in {"vendor", ".git"} for part in p.parts):
                continue
            files.append(str(p.relative_to(REPO_ROOT)))

    if not files:
        return StepResult(
            step=Step(ecosystem="go", name="gofmt", skip_reason="no go files", reason="go.mod detected"),
            status="SKIP",
            returncode=0,
        )

    args_base = ["gofmt"]
    if kind == "gofmt_check":
        args_base.append("-l")
    elif kind == "gofmt_apply":
        args_base.append("-w")
    else:
        return StepResult(
            step=Step(ecosystem="go", name="gofmt", skip_reason="unknown gofmt kind", reason="internal"),
            status="SKIP",
            returncode=0,
        )

    out_all: List[str] = []
    rc_any = 0
    for chunk in _chunked(files, 200):
        rc, out, err = _run_capture(args_base + list(chunk), cwd=REPO_ROOT)
        if rc != 0:
            rc_any = rc
            if err.strip():
                out_all.append(err.strip())
        if kind == "gofmt_check":
            # gofmt -l prints files needing formatting
            out_all.extend([line.strip() for line in out.splitlines() if line.strip()])

    if kind == "gofmt_check":
        needs = [x for x in out_all if x.endswith(".go")]
        if needs:
            details = "Files need gofmt:\n" + "\n".join(f"  - {x}" for x in needs[:200])
            return StepResult(
                step=Step(ecosystem="go", name="gofmt --check"), status="FAIL", returncode=1, details=details
            )
        return StepResult(step=Step(ecosystem="go", name="gofmt --check"), status="PASS", returncode=0)

    # apply
    if rc_any != 0:
        return StepResult(
            step=Step(ecosystem="go", name="gofmt"),
            status="FAIL",
            returncode=rc_any,
            details="\n".join(out_all) if out_all else None,
        )
    return StepResult(step=Step(ecosystem="go", name="gofmt"), status="PASS", returncode=0)


def run_steps(
    steps: Sequence[Step], *, strict: bool, dry_run: bool, keep_going: bool, fail_fast_default: bool
) -> Tuple[int, List[StepResult]]:
    results: List[StepResult] = []
    fail_fast = fail_fast_default and not keep_going

    for step in steps:
        if step.skip_reason:
            status = "SKIP"
            rc = 0 if not strict else 2
            results.append(StepResult(step=step, status=status, returncode=rc, details=step.skip_reason))
            if strict and fail_fast:
                return rc, results
            continue

        if step.kind in ("gofmt_check", "gofmt_apply"):
            if dry_run:
                results.append(StepResult(step=step, status="PASS", returncode=0, details="[dry-run] gofmt"))
                continue
            if not _which("gofmt"):
                status = "SKIP"
                rc = 0 if not strict else 2
                results.append(
                    StepResult(step=step, status=status, returncode=rc, details="gofmt not installed")
                )
                if strict and fail_fast:
                    return rc, results
                continue
            res = _run_gofmt(step.kind)
            results.append(res)
            if res.returncode != 0 and fail_fast:
                return res.returncode, results
            continue

        if not step.command:
            status = "SKIP"
            rc = 0 if not strict else 2
            results.append(
                StepResult(step=step, status=status, returncode=rc, details=step.skip_reason or "no command")
            )
            if strict and fail_fast:
                return rc, results
            continue

        rc = _run_shell(step.command, cwd=step.cwd, dry_run=dry_run)
        status = "PASS" if rc == 0 else "FAIL"
        results.append(StepResult(step=step, status=status, returncode=rc))
        if rc != 0 and fail_fast:
            return rc, results

    # Exit code: 0 if all PASS/SKIP (non-strict); else first non-zero.
    exit_code = 0
    for r in results:
        if r.returncode != 0:
            exit_code = r.returncode
            break
    return exit_code, results


def _print_results(task: str, results: Sequence[StepResult]) -> None:
    _print_header(f"== Harness: {task} ==")
    for r in results:
        s = r.step
        label = f"[{r.status:4s}] {s.ecosystem}:{s.name}"
        if s.reason:
            label += f"  ({s.reason})"
        print(label)
        if r.details:
            print(r.details)


def doctor(cfg: Dict[str, Any]) -> int:
    _print_header("== Harness doctor ==")
    print(f"Repo root: {REPO_ROOT}")
    print(f"harness.toml: {'present' if HARNESS_TOML.exists() else 'missing'}")
    print("")

    if HARNESS_TOML.exists():
        commands = cfg.get("commands", {})
        print("-- configured commands (harness.toml) --")
        for k in ("fmt", "lint", "typecheck", "test", "build"):
            v = commands.get(k, "") if isinstance(commands, dict) else ""
            print(f"  {k:10s}: {v!r}")
        print("")

    print("-- autodetect preferences (harness.toml) --")
    print(f"  python_runner: {str(_cfg_get(cfg, 'autodetect.python_runner', 'auto')).strip()}")
    print(f"  node_runner:   {str(_cfg_get(cfg, 'autodetect.node_runner', 'auto')).strip()}")
    print(
        f"  python defaults: linter={_python_default(cfg, 'linter', 'auto')}, formatter={_python_default(cfg, 'formatter', 'auto')}, typechecker={_python_default(cfg, 'typechecker', 'auto')}, testrunner={_python_default(cfg, 'testrunner', 'auto')}"
    )
    print("")

    print("-- tool availability (PATH) --")
    for tool in (
        "uv",
        "python",
        "pre-commit",
        "pnpm",
        "npm",
        "yarn",
        "go",
        "gofmt",
        "golangci-lint",
        "cargo",
        "rustup",
        "ruff",
        "pyright",
        "pytest",
    ):
        print(f"  {tool:12s}: {'yes' if _which(tool) else 'no'}")

    print("")
    print("-- detected ecosystems --")
    print(f"  python: {'yes' if _detect_python_project() else 'no'}")
    print(f"  node:   {'yes' if _detect_node_project() else 'no'}")
    print(f"  go:     {'yes' if _detect_go_project() else 'no'}")
    print(f"  rust:   {'yes' if _detect_rust_project() else 'no'}")

    print("")
    print("-- auto-detection plan preview --")
    for task in ("fmt", "lint", "typecheck", "test", "build"):
        steps = plan_task(cfg, task)
        printable = ", ".join(f"{s.ecosystem}:{s.name}" + ("" if s.command else " (skip)") for s in steps)
        print(f"  {task:10s}: {printable}")

    return 0


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", choices=["fmt", "lint", "typecheck", "test", "build", "all", "doctor"])
    parser.add_argument("--strict", action="store_true", help="Treat SKIP as failure (useful for CI gating).")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them.")
    parser.add_argument("--keep-going", action="store_true", help="Run all steps even if some fail.")
    parser.add_argument(
        "--only", default="", help="Comma-separated ecosystems to run: precommit,python,node,go,rust"
    )
    args = parser.parse_args(argv)

    cfg = _read_toml(HARNESS_TOML)

    if args.task == "doctor":
        return doctor(cfg)

    only = [x.strip() for x in args.only.split(",") if x.strip()] if args.only else None
    fail_fast_default = bool(_cfg_get(cfg, "harness.fail_fast", True))

    if args.task == "all":
        overall_rc = 0
        for t in ("fmt", "lint", "typecheck", "test", "build"):
            steps = plan_task(cfg, t, only=only)
            rc, results = run_steps(
                steps,
                strict=args.strict,
                dry_run=args.dry_run,
                keep_going=args.keep_going,
                fail_fast_default=fail_fast_default,
            )
            _print_results(t, results)
            if rc != 0:
                overall_rc = rc
                if fail_fast_default and not args.keep_going:
                    return overall_rc
        return overall_rc

    steps = plan_task(cfg, args.task, only=only)
    rc, results = run_steps(
        steps,
        strict=args.strict,
        dry_run=args.dry_run,
        keep_going=args.keep_going,
        fail_fast_default=fail_fast_default,
    )
    _print_results(args.task, results)
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
