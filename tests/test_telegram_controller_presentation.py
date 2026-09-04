from telegram_controller.presentation import operation_subsystem, render_control_text


def test_control_renderer_uses_one_state_and_at_most_one_subsystem_icon() -> None:
    assert render_control_text("queued", state="queued") == "⏳ queued"
    assert render_control_text("applying", state="queued", subsystem="ota") == "⏳ 🔄 applying"
    assert render_control_text("failed", state="failed", subsystem="network") == "❌ 📶 failed"


def test_operation_mapping_is_restrained_and_deterministic() -> None:
    assert operation_subsystem("ota_stage") == "ota"
    assert operation_subsystem("deep_sleep") == "sleep"
    assert operation_subsystem("set_power_mode") == "power"
    assert operation_subsystem("network") == "network"
    assert operation_subsystem("status") is None
