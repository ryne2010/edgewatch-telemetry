from __future__ import annotations

from api.app.services.device_identity import safe_display_name


def test_safe_display_name_keeps_non_empty_value() -> None:
    assert safe_display_name("demo-well-001", "Demo Well 001") == "Demo Well 001"


def test_safe_display_name_falls_back_to_device_id_when_missing() -> None:
    assert safe_display_name("demo-well-001", None) == "demo-well-001"
    assert safe_display_name("demo-well-001", "") == "demo-well-001"
    assert safe_display_name("demo-well-001", "   ") == "demo-well-001"
