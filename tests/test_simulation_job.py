from __future__ import annotations

from datetime import datetime, timezone

from api.app.jobs.simulate_telemetry import _generate_metrics, _simulation_allowed_in_env


def test_simulation_allowed_in_env_blocks_prod_by_default() -> None:
    assert _simulation_allowed_in_env(app_env="prod", allow_in_prod=False) is False


def test_simulation_allowed_in_env_allows_prod_with_opt_in() -> None:
    assert _simulation_allowed_in_env(app_env="prod", allow_in_prod=True) is True
    assert _simulation_allowed_in_env(app_env="stage", allow_in_prod=False) is True


def test_generate_metrics_includes_microphone_and_power_fields() -> None:
    metrics = _generate_metrics(device_index=1, ts=datetime(2026, 2, 27, 12, 0, tzinfo=timezone.utc))

    assert isinstance(metrics.get("microphone_level_db"), float)
    assert isinstance(metrics.get("power_input_v"), float)
    assert isinstance(metrics.get("power_input_a"), float)
    assert isinstance(metrics.get("power_input_w"), float)
    assert metrics.get("power_source") in {"solar", "battery"}
    assert isinstance(metrics.get("power_input_out_of_range"), bool)
    assert isinstance(metrics.get("power_unsustainable"), bool)
    assert isinstance(metrics.get("power_saver_active"), bool)
    assert "water_pressure_psi" not in metrics


def test_generate_metrics_legacy_profile_opt_in_includes_legacy_metrics() -> None:
    metrics = _generate_metrics(
        device_index=1,
        ts=datetime(2026, 2, 27, 12, 0, tzinfo=timezone.utc),
        include_legacy_metrics=True,
    )
    assert "water_pressure_psi" in metrics
    assert "battery_v" in metrics
