from __future__ import annotations

from .config import ControllerConfig
from .models import Principal, Role
from .parser import Command


class AuthorizationError(PermissionError):
    pass


def authorize(
    config: ControllerConfig, user_id: str, chat_id: str, topic_id: str | None, command: Command
) -> Principal:
    if chat_id not in config.allowed_chats:
        raise AuthorizationError("chat is not authorized")
    principal = config.principals.get(user_id)
    if principal is None or principal.role < command.required_role:
        raise AuthorizationError("user is not authorized for this operation")
    fleet_id = command.target if command.scope == "fleet" else _device_fleet(config, command.target)
    if principal.role is not Role.ADMIN and fleet_id not in principal.fleets:
        raise AuthorizationError("user is not authorized for this fleet")
    fleet = config.fleets.get(fleet_id)
    if fleet is None:
        raise AuthorizationError("target is not authorized")
    if fleet.topic_id is not None and fleet.topic_id != topic_id:
        raise AuthorizationError("command was sent in the wrong topic")
    return principal


def _device_fleet(config: ControllerConfig, device_id: str) -> str:
    device = config.devices.get(device_id)
    if device is None or not device.enabled:
        raise AuthorizationError("target is not authorized")
    return device.fleet_id
