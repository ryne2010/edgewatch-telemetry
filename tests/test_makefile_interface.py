from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"


@dataclass(frozen=True)
class MakeTarget:
    prerequisites: tuple[str, ...]
    recipe: tuple[str, ...]


def _logical_lines(source: str) -> list[str]:
    lines: list[str] = []
    pending = ""
    for raw_line in source.splitlines():
        line = f"{pending}{raw_line.lstrip()}" if pending else raw_line
        if line.rstrip().endswith("\\"):
            pending = f"{line.rstrip()[:-1]} "
            continue
        lines.append(line)
        pending = ""
    if pending:
        lines.append(pending.rstrip())
    return lines


def _parse_targets(source: str) -> dict[str, MakeTarget]:
    targets: dict[str, MakeTarget] = {}
    current_names: tuple[str, ...] = ()
    for line in _logical_lines(source):
        if line.startswith("\t"):
            command = line.removeprefix("\t")
            for name in current_names:
                target = targets[name]
                targets[name] = MakeTarget(target.prerequisites, (*target.recipe, command))
            continue

        current_names = ()
        if not line or line.startswith(("#", ".")) or ":" not in line:
            continue
        declaration, prerequisites = line.split(":", 1)
        if "=" in declaration or prerequisites.lstrip().startswith("=") or not declaration.strip():
            continue
        current_names = tuple(declaration.split())
        dependency_names = tuple(prerequisites.split("#", 1)[0].split())
        for name in current_names:
            targets[name] = MakeTarget(dependency_names, ())
    return targets


def _make_targets() -> dict[str, MakeTarget]:
    return _parse_targets(MAKEFILE.read_text(encoding="utf-8"))


def _commands_for(target_name: str, targets: dict[str, MakeTarget]) -> tuple[str, ...]:
    target = targets[target_name]
    prerequisite_commands = tuple(
        command
        for prerequisite in target.prerequisites
        if prerequisite in targets
        for command in _commands_for(prerequisite, targets)
    )
    return (*prerequisite_commands, *target.recipe)


def test_makefile_exposes_canonical_command_targets() -> None:
    canonical_targets = {"run", "dev", "doctor", "setup", "stop", "check", "logs", "reset", "help"}

    assert canonical_targets <= _make_targets().keys()


def test_makefile_exposes_guided_telegram_control_initialization() -> None:
    targets = _make_targets()
    commands = "\n".join(_commands_for("telegram-control-init", targets))

    assert "CONTROL_BOT_TOKEN_FILE is required" in commands
    assert "GATEWAY_DEVICE_ID is required" in commands
    assert "-m scripts.telegram_control_init" in commands
    assert "--install-service" in commands
    assert "TELEGRAM_BOT_TOKEN" not in commands


def test_makefile_exposes_role_aware_rpi_provisioning() -> None:
    commands = "\n".join(_commands_for("rpi-provision", _make_targets()))

    assert '--profile "$$profile"' in commands
    assert 'profile="$(RPI_PROFILE)"' in commands
    for profile in ("standalone", "gateway", "camera-satellite"):
        assert f"{profile})" in commands
    for required in (
        "LORAWAN_GATEWAY_CONFIG_FILE is required for gateway",
        "LORAWAN_REGISTRY_FILE is required for gateway",
        "GATEWAY_POWER_ENV_FILE is required for gateway",
        "CAMERA_RUNTIME_ENV_FILE is required for camera-satellite",
        "CAMERA_CREDENTIALS_FILE is required for camera-satellite",
        "MODEL_PUBLIC_KEY_FILE is required for camera-satellite",
    ):
        assert required in commands
    assert "uv run --locked python scripts/rpi_provision_device.py" in commands


def test_makefile_exposes_signed_model_release_builder() -> None:
    commands = "\n".join(_commands_for("model-release", _make_targets()))

    for required in (
        "MODEL_SOURCE_DIR is required",
        "MODEL_PRIVATE_KEY_FILE is required",
        "MODEL_ARTIFACT_URI is required",
        "MODEL_VERSION is required",
    ):
        assert required in commands
    assert "-m scripts.build_model_bundle" in commands
    assert "--private-key" in commands


def test_gateway_energy_report_requires_evidence_and_uses_qualification_tool() -> None:
    commands = "\n".join(_commands_for("gateway-energy-report", _make_targets()))

    assert "GATEWAY_ENERGY_INPUT is required" in commands
    assert "GATEWAY_ENERGY_REPORT is required" in commands
    assert "scripts.gateway_energy_report" in commands
    assert "--minimum-daily-samples" in commands


def test_camera_qualification_report_requires_evidence_and_uses_evaluator() -> None:
    commands = "\n".join(_commands_for("camera-qualification-report", _make_targets()))

    assert "CAMERA_QUALIFICATION_INPUT is required" in commands
    assert "CAMERA_QUALIFICATION_REPORT is required" in commands
    assert "scripts.camera_qualify" in commands


def test_makefile_defaults_to_help() -> None:
    source = MAKEFILE.read_text(encoding="utf-8")

    assert re.search(r"^\.DEFAULT_GOAL\s*:?=\s*help\s*$", source, re.MULTILINE)


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [("up", "run"), ("down", "stop"), ("harness", "check")],
    ids=["up-aliases-run", "down-aliases-stop", "harness-aliases-check"],
)
def test_makefile_retains_dependency_only_compatibility_alias(alias: str, canonical: str) -> None:
    target = _make_targets()[alias]

    assert target == MakeTarget(prerequisites=(canonical,), recipe=())


def test_makefile_check_runs_every_quality_gate() -> None:
    commands = "\n".join(_commands_for("check", _make_targets()))

    for gate in ("lint", "typecheck", "test", "build"):
        assert re.search(rf"scripts/harness\.py\s+{gate}(?:\s|$)", commands)


def test_makefile_check_excludes_mutating_formatters_and_hooks() -> None:
    targets = _make_targets()
    target = targets["check"]
    commands = "\n".join(_commands_for("check", targets))

    assert "fmt" not in target.prerequisites
    assert not re.search(r"scripts/harness\.py\s+(?:fmt|all)(?:\s|$)", commands)
    assert "pre-commit" not in commands


def test_makefile_setup_is_idempotent_and_uses_locked_dependencies() -> None:
    commands = "\n".join(_commands_for("setup", _make_targets()))

    assert "[ ! -e .env ]" in commands
    assert "cp .env.example .env" in commands
    assert "[ ! -e agent/.env ]" in commands
    assert "cp agent/.env.example agent/.env" in commands
    assert "uv sync --locked" in commands
    assert "pnpm install --frozen-lockfile" in commands


def test_makefile_run_and_stop_wrap_docker_compose() -> None:
    targets = _make_targets()

    assert "$(COMPOSE) up --build" in targets["run"].recipe
    assert "$(COMPOSE) down" in targets["stop"].recipe


def test_makefile_doctor_reports_both_lanes_without_echoing_secrets() -> None:
    targets = _make_targets()
    doctor_commands = "\n".join(_commands_for("doctor", targets))
    dev_doctor_commands = "\n".join(_commands_for("doctor-dev", targets))

    assert "run: READY" in doctor_commands
    assert "dev: READY" in doctor_commands
    assert not re.search(
        r"echo.*\$\((?:EDGEWATCH_DEVICE_TOKEN|ADMIN_API_KEY)\)",
        dev_doctor_commands,
    )


def test_makefile_harness_commands_use_uv_managed_python() -> None:
    targets = _make_targets()

    for target_name in ("fmt", "lint", "typecheck", "test", "build", "check", "harness-doctor"):
        commands = "\n".join(_commands_for(target_name, targets))
        assert not re.search(r"(?:^|\n)python\s+scripts/", commands)
        assert "uv run --locked python scripts/" in commands
