#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from telegram_controller.presentation import render_control_text
from telegram_controller.setup import (
    SetupError,
    SetupPaths,
    default_service_user,
    discover_private_group_registration,
    ensure_service_user,
    gateway_uses_systemd_lte_power,
    install_local_gateway_helper,
    install_systemd_service,
    prepare_controller,
    read_control_bot_token,
    render_systemd_unit,
    smoke_test_local_gateway_control,
)
from telegram_controller.telegram import TelegramClient, TelegramError


STABLE_REPOSITORY_ROOT = Path("/opt/edgewatch/current")
STABLE_PYTHON = Path("/opt/edgewatch/app/.venv/bin/python")


def _absolute_without_resolving(path: Path) -> Path:
    """Make a setup path absolute while preserving a stable release symlink."""

    return path if path.is_absolute() else Path(os.path.abspath(path))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Securely initialize the dedicated EdgeWatch Telegram control bot"
    )
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("/etc/edgewatch-controller/controller.yaml"),
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("/var/lib/edgewatch-controller"),
    )
    parser.add_argument(
        "--key-file",
        type=Path,
        default=Path("/etc/edgewatch-controller/controller_device_ed25519"),
    )
    parser.add_argument(
        "--known-hosts-file",
        type=Path,
        default=Path("/etc/edgewatch-controller/known_hosts"),
    )
    parser.add_argument("--service-user", default=default_service_user())
    parser.add_argument("--ssh-username", default="ryne")
    parser.add_argument("--gateway-device-id", default=None)
    parser.add_argument("--registration-timeout-s", type=int, default=300)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--install-service", action="store_true")
    parser.add_argument(
        "--service-unit",
        type=Path,
        default=Path("/etc/systemd/system/edgewatch-telegram-controller.service"),
    )
    parser.add_argument("--repository-root", type=Path, default=STABLE_REPOSITORY_ROOT)
    parser.add_argument("--python-executable", type=Path, default=STABLE_PYTHON)
    parser.add_argument(
        "--gateway-power-env",
        type=Path,
        default=Path("/etc/edgewatch-controller/gateway-power.env"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        token = read_control_bot_token(args.token_file)
        client = TelegramClient(token)
        registration = discover_private_group_registration(
            client,
            timeout_s=args.registration_timeout_s,
            ready=lambda username: print(
                f"Send /register@{username} in the new private control group now.",
                flush=True,
            ),
        )
        ensure_service_user(args.service_user, state_dir=args.state_dir)
        result = prepare_controller(
            SetupPaths(
                config_path=args.config,
                state_dir=args.state_dir,
                source_token_file=args.token_file,
                key_file=args.key_file,
                known_hosts_file=args.known_hosts_file,
            ),
            registration,
            token=token,
            service_user=args.service_user,
            ssh_username=args.ssh_username,
            gateway_device_id=args.gateway_device_id,
            force=args.force,
        )
        client.send_message(
            registration.chat_id,
            render_control_text(
                "EdgeWatch control registration and configuration verified.",
                state="success",
            ),
            registration.topic_id,
        )
        if args.install_service:
            install_local_gateway_helper(
                service_user=args.service_user,
                gateway_device_id=result.gateway_device_id,
                enable_lte_power_systemd=gateway_uses_systemd_lte_power(args.gateway_power_env),
            )
            smoke_test_local_gateway_control(
                service_user=args.service_user,
                gateway_device_id=result.gateway_device_id,
            )
            unit = render_systemd_unit(
                service_user=args.service_user,
                repository_root=_absolute_without_resolving(args.repository_root),
                config_path=args.config.resolve(),
                state_dir=args.state_dir.resolve(),
                python_executable=args.python_executable.resolve(),
            )
            install_systemd_service(args.service_unit, unit)
    except (SetupError, TelegramError, ValueError) as exc:
        print(f"Telegram control setup failed: {exc}", file=sys.stderr)
        return 1

    print(f"Control group ID: {result.chat_id}")
    print(f"Administrator user ID: {result.admin_user_id}")
    print(f"Gateway device ID: {result.gateway_device_id}")
    print("Controller SSH public key:")
    print(result.public_key)
    print(f"Controller SSH key fingerprint: {result.key_fingerprint}")
    print(f"Controller configuration: {result.config_path}")
    print("Existing telemetry bot and channel settings were not changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
