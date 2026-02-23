from __future__ import annotations


def safe_display_name(device_id: str, display_name: str | None) -> str:
    """Return a UI-safe display name even for legacy/null rows."""
    candidate = (display_name or "").strip()
    if candidate:
        return candidate
    return device_id
