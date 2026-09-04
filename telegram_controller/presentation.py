from __future__ import annotations

from typing import Literal


ReplyState = Literal["failed", "info", "queued", "success", "warning"]
Subsystem = Literal["audio", "lorawan", "network", "ota", "power", "sleep", "vision"]

_STATE_EMOJI: dict[ReplyState, str] = {
    "failed": "❌",
    "info": "ℹ️",
    "queued": "⏳",
    "success": "✅",
    "warning": "⚠️",
}
_SUBSYSTEM_EMOJI: dict[Subsystem, str] = {
    "audio": "🎙️",
    "lorawan": "🛰️",
    "network": "📶",
    "ota": "🔄",
    "power": "🔋",
    "sleep": "💤",
    "vision": "🎥",
}


def render_control_text(
    text: str,
    *,
    state: ReplyState,
    subsystem: Subsystem | None = None,
) -> str:
    """Render a human reply with one state icon and at most one domain icon."""

    icons = [_STATE_EMOJI[state]]
    if subsystem is not None:
        icons.append(_SUBSYSTEM_EMOJI[subsystem])
    return f"{' '.join(icons)} {text}"


def operation_subsystem(operation: str) -> Subsystem | None:
    normalized = operation.lower()
    if normalized.startswith("ota_") or normalized == "ota":
        return "ota"
    if normalized == "deep_sleep":
        return "sleep"
    if normalized in {"power", "set_power_mode"}:
        return "power"
    if normalized in {"network", "sync_now"}:
        return "network"
    return None
