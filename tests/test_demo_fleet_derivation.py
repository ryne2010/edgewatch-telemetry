from __future__ import annotations

from api.app.main import _derive_nth


def test_derive_nth_uses_named_sample_fleet_defaults() -> None:
    assert _derive_nth("baxter-1", 1) == "baxter-1"
    assert _derive_nth("baxter-1", 2) == "sprinklers-west"
    assert _derive_nth("baxter-1", 5) == "sprinklers-south"
    assert _derive_nth("lms-2", 3) == "lms-4"


def test_derive_nth_replaces_3digit_suffix() -> None:
    assert _derive_nth("demo-well-001", 1) == "demo-well-001"
    assert _derive_nth("demo-well-001", 2) == "demo-well-002"
    assert _derive_nth("demo-well-009", 12) == "demo-well-012"


def test_derive_nth_appends_when_no_suffix() -> None:
    assert _derive_nth("device", 1) == "device"
    assert _derive_nth("device", 2) == "device-002"
