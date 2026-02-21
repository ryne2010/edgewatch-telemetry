from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, TypeVar

import pytest

from agent.cellular import (
    CellularConfig,
    CellularConfigError,
    CellularMonitor,
    build_cellular_monitor_from_env,
    load_cellular_config_from_env,
)

T = TypeVar("T")


class _StickySequence(Iterable[T]):
    def __init__(self, values: list[T]) -> None:
        self._values = list(values)
        self._idx = 0

    def __iter__(self):
        return self

    def __next__(self) -> T:
        if not self._values:
            raise StopIteration
        value = self._values[min(self._idx, len(self._values) - 1)]
        self._idx += 1
        return value


def test_build_cellular_monitor_returns_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CELLULAR_METRICS_ENABLED", raising=False)
    assert build_cellular_monitor_from_env() is None


def test_load_cellular_config_rejects_invalid_bool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CELLULAR_METRICS_ENABLED", "maybe")
    with pytest.raises(CellularConfigError):
        load_cellular_config_from_env()


def test_cellular_monitor_collects_modem_watchdog_and_daily_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent.cellular.shutil.which", lambda _: "/usr/bin/mmcli")

    clock = _StickySequence(
        [
            datetime(2026, 2, 21, 10, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 2, 21, 10, 1, 5, tzinfo=timezone.utc),
        ]
    )
    counters = _StickySequence([(1_000, 2_000), (1_800, 3_000)])

    def command_runner(command: list[str], timeout_s: float) -> str | None:
        _ = timeout_s
        cmd = " ".join(command)
        if "--simple-status" in cmd:
            return "modem.3gpp.registration-state=home"
        if "--signal-get" in cmd:
            return "\n".join(
                [
                    "modem.signal.rssi.value=-71",
                    "modem.signal.lte.rsrp.value=-95",
                    "modem.signal.lte.rsrq.value=-8",
                    "modem.signal.lte.snr.value=11.5",
                ]
            )
        return None

    config = CellularConfig(
        enabled=True,
        modem_id="0",
        modem_poll_interval_s=1,
        command_timeout_s=2.0,
        watchdog_enabled=True,
        watchdog_interval_s=1,
        watchdog_dns_host="example.org",
        watchdog_http_url="https://example.org/healthz",
        watchdog_timeout_s=1.0,
        usage_poll_interval_s=1,
        interface_name=None,
    )

    monitor = CellularMonitor(
        config,
        command_runner=command_runner,
        dns_probe=lambda host, timeout: host == "example.org" and timeout > 0,
        http_probe=lambda url, timeout: url.endswith("/healthz") and timeout > 0,
        default_route_interface_detector=lambda: "wwan0",
        interface_counters=lambda _: next(counters),
        now_fn=lambda: next(clock),
    )

    first = monitor.read_metrics()
    assert first["cellular_registration_state"] == "home"
    assert first["signal_rssi_dbm"] == -71.0
    assert first["cellular_rsrp_dbm"] == -95.0
    assert first["cellular_rsrq_db"] == -8.0
    assert first["cellular_sinr_db"] == 11.5
    assert first["link_ok"] is True
    assert first["link_last_ok_at"] == "2026-02-21T10:00:00+00:00"
    assert first["cellular_bytes_sent_today"] == 0
    assert first["cellular_bytes_received_today"] == 0

    second = monitor.read_metrics()
    assert second["cellular_bytes_sent_today"] == 1_000
    assert second["cellular_bytes_received_today"] == 800
    assert second["link_last_ok_at"] == "2026-02-21T10:01:05+00:00"


def test_cellular_monitor_handles_missing_mmcli_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent.cellular.shutil.which", lambda _: None)

    config = CellularConfig(
        enabled=True,
        modem_id="0",
        modem_poll_interval_s=30,
        command_timeout_s=2.0,
        watchdog_enabled=True,
        watchdog_interval_s=30,
        watchdog_dns_host="example.org",
        watchdog_http_url="https://example.org/healthz",
        watchdog_timeout_s=1.0,
        usage_poll_interval_s=30,
        interface_name=None,
    )

    monitor = CellularMonitor(
        config,
        dns_probe=lambda _host, _timeout: False,
        http_probe=lambda _url, _timeout: False,
        default_route_interface_detector=lambda: None,
        interface_counters=lambda _iface: None,
        now_fn=lambda: datetime(2026, 2, 21, 10, 0, 0, tzinfo=timezone.utc),
    )

    metrics = monitor.read_metrics()
    assert metrics["link_ok"] is False
    assert "link_last_ok_at" not in metrics
    assert "signal_rssi_dbm" not in metrics
