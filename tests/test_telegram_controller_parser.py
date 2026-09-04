import pytest

from telegram_controller.models import Role
from telegram_controller.parser import CommandParseError, parse_command


@pytest.mark.parametrize(
    ("text", "operation", "role", "mutating"),
    [
        ("/device pump-1 status", "status", Role.VIEWER, False),
        ("/device pump-1 sample now", "sample_now", Role.OPERATOR, True),
        ("/device pump-1 mode active", "set_operation_mode", Role.OPERATOR, True),
        ("/device pump-1 power deep-sleep 30m", "deep_sleep", Role.ADMIN, True),
        ("/fleet west reboot", "reboot", Role.ADMIN, True),
        ("/ota west stage stable-1", "ota_stage", Role.ADMIN, True),
        ("/ota west canary dep-1", "ota_canary", Role.ADMIN, True),
        ("/ota west promote dep-1", "ota_promote", Role.ADMIN, True),
        ("/ota west abort dep-1", "ota_abort", Role.ADMIN, True),
        ("/ota west status", "ota_status", Role.VIEWER, False),
    ],
)
def test_parses_only_typed_operations(text, operation, role, mutating) -> None:
    command = parse_command(text)
    assert (command.operation, command.required_role, command.mutating) == (operation, role, mutating)


@pytest.mark.parametrize(
    "text",
    [
        "/device pump-1 shell id",
        "/ota west stage https://bad/x",
        "/ota west canary",
        "/ota west promote",
        "/ota west abort",
        "/device pump-1 power deep-sleep",
        "/device pump-1 power deep-sleep forever",
        "/device pump-1 power deep-sleep 59s",
        "/device pump-1 alert mute tomorrow",
        "/device pump-1 alert mute 2026-08-09T12:00:00-06:00",
        "/fleet west shutdown now",
        "/exec rm -rf x",
        "/device pump-1 status\n/ota west abort x",
    ],
)
def test_rejects_arbitrary_commands_urls_files_and_multiline(text: str) -> None:
    with pytest.raises(CommandParseError):
        parse_command(text)


def test_normalizes_typed_helper_arguments() -> None:
    assert parse_command("/device pump-1 mode sleep 900").arguments == {
        "mode": "sleep",
        "sleep_poll_interval_s": 900,
    }
    assert parse_command("/device pump-1 alert mute 2026-08-09T12:00:00Z maintenance").arguments == {
        "until": "2026-08-09T12:00:00Z",
        "reason": "maintenance",
    }
    assert parse_command("/ota west stage stable-1").arguments == {"release_alias": "stable-1"}
    assert parse_command("/ota west canary deployment-1").arguments == {"deployment_id": "deployment-1"}
    assert parse_command("/device pump-1 power deep-sleep 30m").arguments == {"duration": "30m"}
