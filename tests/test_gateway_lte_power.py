from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from gateway_runtime.lte_power import (
    GatewayLtePowerController,
    GatewayPowerConfig,
    GatewayPowerConfigError,
    GatewayPowerError,
    SystemdLtePowerBackend,
    load_gateway_power_config,
)


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def power_on(self) -> None:
        self.calls.append("on")

    def power_off(self) -> None:
        self.calls.append("off")


class SimulatedProcessDeath(BaseException):
    pass


def _config(tmp_path: Path, *, mode: str = "systemd") -> GatewayPowerConfig:
    return GatewayPowerConfig(
        mode=mode,
        interval_s=3600,
        min_window_s=60,
        max_window_s=300,
        max_held_window_s=900,
        trigger_path=tmp_path / "trigger.json",
        state_path=tmp_path / "state.json",
        hold_dir=tmp_path / "holds",
    )


def test_config_is_disabled_by_default_and_validates_bounds() -> None:
    assert load_gateway_power_config({}).mode == "disabled"
    with pytest.raises(GatewayPowerConfigError, match="must not exceed"):
        load_gateway_power_config(
            {
                "EDGEWATCH_GATEWAY_LTE_MIN_WINDOW_S": "301",
                "EDGEWATCH_GATEWAY_LTE_MAX_WINDOW_S": "300",
            }
        )
    with pytest.raises(GatewayPowerConfigError, match="CELLULAR_INTERFACE"):
        load_gateway_power_config({"CELLULAR_INTERFACE": "wwan0; poweroff"})
    with pytest.raises(GatewayPowerConfigError, match="maximum held window"):
        load_gateway_power_config(
            {
                "EDGEWATCH_GATEWAY_LTE_MAX_WINDOW_S": "301",
                "EDGEWATCH_GATEWAY_LTE_MAX_HELD_WINDOW_S": "300",
            }
        )


def test_scheduled_window_is_bounded_and_persisted(tmp_path: Path) -> None:
    backend = FakeBackend()
    controller = GatewayLtePowerController(_config(tmp_path), backend=backend, clock=lambda: 1000.0)

    assert controller.next_reason() == "scheduled"
    opened = controller.open_window("scheduled")
    assert opened["must_close_at"] == 1300.0
    assert opened["held_must_close_at"] == 1900.0
    assert controller.should_close(busy=False, now=1059.0) is False
    assert controller.should_close(busy=False, now=1060.0) is True
    assert controller.should_close(busy=True, now=1299.0) is False
    assert controller.should_close(busy=True, now=1300.0) is True

    closed = controller.close_window(now=1300.0)
    assert closed["active"] is False
    assert backend.calls == ["on", "off"]
    assert stat.S_IMODE(_config(tmp_path).state_path.stat().st_mode) == 0o600
    assert controller.next_reason(now=4599.0) is None
    assert controller.next_reason(now=4600.0) == "scheduled"


def test_alert_trigger_survives_restart_until_successful_power_on(tmp_path: Path) -> None:
    backend = FakeBackend()
    config = _config(tmp_path)
    first = GatewayLtePowerController(config, backend=backend, clock=lambda: 20.0)
    first.request_immediate("alert")

    restarted = GatewayLtePowerController(config, backend=backend, clock=lambda: 21.0)
    assert restarted.next_reason() == "alert"
    restarted.open_window("alert")
    assert not config.trigger_path.exists()
    assert restarted.snapshot()["reason"] == "alert"


def test_failed_power_transition_keeps_trigger_retryable(tmp_path: Path) -> None:
    class FailingBackend(FakeBackend):
        def power_on(self) -> None:
            raise GatewayPowerError("no carrier power service")

    config = _config(tmp_path)
    controller = GatewayLtePowerController(config, backend=FailingBackend(), clock=lambda: 20.0)
    controller.request_immediate("control")

    with pytest.raises(GatewayPowerError):
        controller.open_window("control")
    assert config.trigger_path.exists()
    assert controller.next_reason() == "control"


def test_systemd_backend_executes_only_fixed_units() -> None:
    calls: list[list[str]] = []

    class Result:
        returncode = 0

    def run(argv: list[str], **_: object) -> Result:
        calls.append(argv)
        return Result()

    backend = SystemdLtePowerBackend(run_command=run)
    backend.power_on()
    backend.power_off()

    assert calls == [
        [
            "/usr/bin/sudo",
            "-n",
            "/usr/bin/systemctl",
            "start",
            "edgewatch-lte-power-on.service",
        ],
        [
            "/usr/bin/sudo",
            "-n",
            "/usr/bin/systemctl",
            "start",
            "edgewatch-lte-power-off.service",
        ],
    ]


def test_corrupt_or_permissive_state_fails_closed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.state_path.write_text(json.dumps({"active": False}))
    config.state_path.chmod(0o644)
    controller = GatewayLtePowerController(config, backend=FakeBackend())

    with pytest.raises(GatewayPowerError, match="0600"):
        controller.snapshot()


def test_observe_mode_never_claims_electrical_switching(tmp_path: Path) -> None:
    controller = GatewayLtePowerController(_config(tmp_path, mode="observe"), clock=lambda: 1.0)
    state = controller.open_window("startup")
    assert state["electrically_switched"] is False


def test_restart_closes_stale_window_then_schedules_a_fresh_startup(tmp_path: Path) -> None:
    backend = FakeBackend()
    config = _config(tmp_path)
    first = GatewayLtePowerController(config, backend=backend, clock=lambda: 10.0)
    first.open_window("scheduled")

    restarted = GatewayLtePowerController(config, backend=backend, clock=lambda: 20.0)
    assert restarted.recover_interrupted_window() is True
    assert restarted.snapshot()["active"] is False
    assert restarted.next_reason() == "startup"
    assert backend.calls == ["on", "off"]


def test_restart_recovers_process_death_after_modem_power_on(tmp_path: Path) -> None:
    class DiesAfterPowerOn(FakeBackend):
        def power_on(self) -> None:
            super().power_on()
            raise SimulatedProcessDeath

    config = _config(tmp_path)
    dying_backend = DiesAfterPowerOn()
    controller = GatewayLtePowerController(config, backend=dying_backend, clock=lambda: 10.0)

    with pytest.raises(SimulatedProcessDeath):
        controller.open_window("scheduled")
    assert controller.snapshot()["transition"] == "opening"

    recovery_backend = FakeBackend()
    restarted = GatewayLtePowerController(config, backend=recovery_backend, clock=lambda: 20.0)
    assert restarted.recover_interrupted_window() is True
    assert recovery_backend.calls == ["off"]
    assert restarted.snapshot()["active"] is False
    assert restarted.next_reason() == "startup"


def test_restart_recovers_process_death_after_modem_power_off(tmp_path: Path) -> None:
    class DiesAfterPowerOff(FakeBackend):
        def power_off(self) -> None:
            super().power_off()
            raise SimulatedProcessDeath

    config = _config(tmp_path)
    controller = GatewayLtePowerController(config, backend=FakeBackend(), clock=lambda: 10.0)
    controller.open_window("scheduled")
    dying_backend = DiesAfterPowerOff()
    controller.backend = dying_backend

    with pytest.raises(SimulatedProcessDeath):
        controller.close_window(now=20.0)
    assert controller.snapshot()["transition"] == "closing"

    recovery_backend = FakeBackend()
    restarted = GatewayLtePowerController(config, backend=recovery_backend, clock=lambda: 30.0)
    assert restarted.recover_interrupted_window() is True
    assert recovery_backend.calls == ["off"]
    assert restarted.snapshot()["active"] is False


def test_cross_process_hold_delays_close_but_never_exceeds_hard_window(tmp_path: Path) -> None:
    controller = GatewayLtePowerController(_config(tmp_path), backend=FakeBackend(), clock=lambda: 1_000.0)
    controller.open_window("alert")
    controller.acquire_hold("lorawan-outbox", ttl_s=120)

    assert controller.has_active_holds(now=1_060.0) is True
    assert controller.should_close(busy=False, now=1_060.0) is False
    assert controller.should_close(busy=False, now=1_121.0) is True
    controller.acquire_hold("lorawan-outbox", ttl_s=600)
    assert controller.should_close(busy=False, now=1_300.0) is False
    assert controller.should_close(busy=False, now=1_599.0) is False
    assert controller.should_close(busy=False, now=1_601.0) is True

    controller.release_hold("lorawan-outbox")
    assert controller.has_active_holds(now=1_100.0) is False


def test_hold_expiry_is_clamped_to_the_held_window_deadline(tmp_path: Path) -> None:
    controller = GatewayLtePowerController(_config(tmp_path), backend=FakeBackend(), clock=lambda: 1_000.0)
    controller.open_window("ota")
    controller.acquire_hold("artifact-cache", ttl_s=14_400)

    hold = json.loads((_config(tmp_path).hold_dir / "artifact-cache.json").read_text(encoding="utf-8"))
    assert hold["expires_at"] == 1_900.0
    assert controller.should_close(busy=False, now=1_899.0) is False
    assert controller.should_close(busy=True, now=1_900.0) is True


def test_invalid_or_permissive_hold_fails_closed(tmp_path: Path) -> None:
    controller = GatewayLtePowerController(_config(tmp_path), backend=FakeBackend(), clock=lambda: 1.0)
    controller.acquire_hold("delivery")
    hold_path = _config(tmp_path).hold_dir / "delivery.json"
    hold_path.chmod(0o644)

    with pytest.raises(GatewayPowerError, match="0600"):
        controller.has_active_holds()
