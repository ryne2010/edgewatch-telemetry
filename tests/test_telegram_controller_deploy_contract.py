from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "telegram-controller"


def test_example_uses_separate_secret_files_and_official_spacebridge_port() -> None:
    config = yaml.safe_load((DEPLOY / "controller.example.yaml").read_text(encoding="utf-8"))

    assert config["telegram"]["token_file"] == "/etc/edgewatch-controller/control_bot_token"
    assert config["ssh"]["device_key_file"].endswith("controller_device_ed25519")
    assert config["ssh"]["spacebridge_identity_file"].endswith("spacebridge_rsa")
    assert config["ssh"]["spacebridge_port"] == 999
    assert config["controller"]["shutdown_enabled"] is False
    assert config["fleets"]["home-lab"]["canaries"] == ["rpi-001"]
    assert config["ota"]["catalog_file"].endswith("releases.json")


def test_systemd_unit_is_supervised_hardened_and_state_scoped() -> None:
    unit = (DEPLOY / "edgewatch-telegram-controller.service").read_text(encoding="utf-8")

    assert "User=edgewatch-controller" in unit
    assert "Restart=always" in unit
    assert "ProtectSystem=strict" in unit
    assert "NoNewPrivileges=false" in unit
    assert (
        "ReadWritePaths=/var/lib/edgewatch-controller /var/lib/edgewatch /var/lib/edgewatch-gateway" in unit
    )
    assert "WorkingDirectory=/opt/edgewatch/current" in unit
    assert "ExecStart=/opt/edgewatch/app/.venv/bin/python" in unit
    assert " -m scripts.telegram_fleet_controller " in unit
    assert "--config /etc/edgewatch-controller/controller.yaml" in unit


def test_controller_fails_closed_when_ssh_dispatcher_cannot_load() -> None:
    launcher = (ROOT / "scripts" / "telegram_fleet_controller.py").read_text(encoding="utf-8")

    assert "from telegram_controller.ssh_dispatch import DeviceDispatcher" in launcher
    assert "UnconfiguredDispatcher" not in launcher
