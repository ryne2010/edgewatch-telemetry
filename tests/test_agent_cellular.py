from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
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


def _usage_config(state_path: Path) -> CellularConfig:
    return CellularConfig(
        enabled=True,
        modem_id="0",
        modem_poll_interval_s=60,
        command_timeout_s=2.0,
        watchdog_enabled=False,
        watchdog_interval_s=60,
        watchdog_dns_host="example.org",
        watchdog_http_url="https://example.org/healthz",
        watchdog_timeout_s=1.0,
        usage_poll_interval_s=1,
        interface_name="wwan0",
        usage_state_path=state_path,
    )


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


def test_cellular_usage_persists_across_monitor_restart_and_counter_reset(tmp_path: Path) -> None:
    state_path = tmp_path / "cellular-usage.json"
    config = _usage_config(state_path)
    clock = datetime(2026, 2, 21, 10, 0, 0, tzinfo=timezone.utc)
    first_counters = _StickySequence([(1_000, 2_000), (1_500, 2_600)])
    first = CellularMonitor(
        config,
        interface_counters=lambda _: next(first_counters),
        now_fn=lambda: clock,
    )

    assert first.read_metrics()["cellular_bytes_sent_today"] == 0
    first._next_usage_poll_at = 0.0
    assert first.read_metrics()["cellular_bytes_sent_today"] == 600

    # Simulate a reboot/modem reconnect: kernel counters moved backwards, but
    # the durable daily total must continue from the saved state.
    restarted = CellularMonitor(
        config,
        interface_counters=lambda _: (100, 200),
        now_fn=lambda: clock,
    )
    metrics = restarted.read_metrics()

    assert metrics["cellular_bytes_sent_today"] == 800
    assert metrics["cellular_bytes_received_today"] == 600
    assert state_path.stat().st_mode & 0o777 == 0o600


def test_cellular_usage_state_write_is_durable_and_uses_unique_temps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state_path = tmp_path / "cellular-usage.json"
    events: list[tuple[str, str | None]] = []
    replacement_sources: list[Path] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def tracking_fsync(fd: int) -> None:
        kind = "directory_fsync" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file_fsync"
        events.append((kind, None))
        real_fsync(fd)

    def tracking_replace(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        source_path = Path(source)
        replacement_sources.append(source_path)
        events.append(("replace", source_path.name))
        real_replace(source, destination)

    monkeypatch.setattr("agent.cellular.os.fsync", tracking_fsync)
    monkeypatch.setattr("agent.cellular.os.replace", tracking_replace)

    monitor = CellularMonitor(
        _usage_config(state_path),
        interface_counters=lambda _: (1_000, 2_000),
        now_fn=lambda: datetime(2026, 2, 21, 10, 0, 0, tzinfo=timezone.utc),
    )
    monitor.read_metrics()
    monitor._next_usage_poll_at = 0.0
    monitor.read_metrics()

    assert [event[0] for event in events] == [
        "file_fsync",
        "replace",
        "directory_fsync",
        "file_fsync",
        "replace",
        "directory_fsync",
    ]
    assert len(set(replacement_sources)) == 2
    assert all(source.parent == state_path.parent for source in replacement_sources)
    assert all(source.name.startswith(f".{state_path.name}.") for source in replacement_sources)
    assert not list(tmp_path.glob(f".{state_path.name}.*.tmp"))
    assert state_path.stat().st_mode & 0o777 == 0o600


def test_cellular_usage_state_replace_failure_is_fail_open_and_cleans_temp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state_path = tmp_path / "cellular-usage.json"
    original_state = {"sentinel": "preserved"}
    state_path.write_text(json.dumps(original_state), encoding="utf-8")

    def failed_replace(_source: os.PathLike[str], _destination: os.PathLike[str]) -> None:
        raise OSError("simulated abrupt storage failure")

    monkeypatch.setattr("agent.cellular.os.replace", failed_replace)
    monitor = CellularMonitor(
        _usage_config(state_path),
        interface_counters=lambda _: (1_000, 2_000),
        now_fn=lambda: datetime(2026, 2, 21, 10, 0, 0, tzinfo=timezone.utc),
    )

    metrics = monitor.read_metrics()

    assert metrics["cellular_bytes_sent_today"] == 0
    assert metrics["cellular_bytes_received_today"] == 0
    assert json.loads(state_path.read_text(encoding="utf-8")) == original_state
    assert not list(tmp_path.glob(f".{state_path.name}.*.tmp"))


def test_cellular_usage_state_file_fsync_failure_is_fail_open_and_cleans_temp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state_path = tmp_path / "cellular-usage.json"

    def failed_fsync(_fd: int) -> None:
        raise OSError("simulated fsync failure")

    monkeypatch.setattr("agent.cellular.os.fsync", failed_fsync)
    monitor = CellularMonitor(
        _usage_config(state_path),
        interface_counters=lambda _: (1_000, 2_000),
        now_fn=lambda: datetime(2026, 2, 21, 10, 0, 0, tzinfo=timezone.utc),
    )

    metrics = monitor.read_metrics()

    assert metrics["cellular_bytes_sent_today"] == 0
    assert metrics["cellular_bytes_received_today"] == 0
    assert not state_path.exists()
    assert not list(tmp_path.glob(f".{state_path.name}.*.tmp"))


def test_load_cellular_config_reads_usage_state_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    state_path = tmp_path / "usage.json"
    monkeypatch.setenv("CELLULAR_METRICS_ENABLED", "true")
    monkeypatch.setenv("CELLULAR_USAGE_STATE_PATH", str(state_path))

    assert load_cellular_config_from_env().usage_state_path == state_path


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


def test_cellular_monitor_uses_generic_modem_output_when_simple_status_is_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent.cellular.shutil.which", lambda _: "/usr/bin/mmcli")

    def command_runner(command: list[str], timeout_s: float) -> str | None:
        _ = timeout_s
        if command == ["mmcli", "-m", "0", "--output-keyvalue"]:
            return "modem.3gpp.registration-state=home"
        return None

    config = CellularConfig(
        enabled=True,
        modem_id="0",
        modem_poll_interval_s=30,
        command_timeout_s=2.0,
        watchdog_enabled=False,
        watchdog_interval_s=30,
        watchdog_dns_host="example.org",
        watchdog_http_url="https://example.org/healthz",
        watchdog_timeout_s=1.0,
        usage_poll_interval_s=30,
        interface_name=None,
    )
    monitor = CellularMonitor(
        config,
        command_runner=command_runner,
        default_route_interface_detector=lambda: None,
        now_fn=lambda: datetime(2026, 2, 21, 10, 0, 0, tzinfo=timezone.utc),
    )

    metrics = monitor.read_metrics()

    assert metrics["cellular_registration_state"] == "home"


def test_cellular_monitor_omits_rssi_when_signal_output_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent.cellular.shutil.which", lambda _: "/usr/bin/mmcli")

    def command_runner(command: list[str], timeout_s: float) -> str | None:
        _ = timeout_s
        if "--simple-status" in command:
            return "modem.3gpp.registration-state=home"
        if "--signal-get" in command:
            return "\n".join(
                [
                    "modem.signal.threshold.rssi=0",
                    "modem.signal.gsm.rssi=--",
                    "modem.signal.lte.rssi=--",
                ]
            )
        return None

    config = CellularConfig(
        enabled=True,
        modem_id="0",
        modem_poll_interval_s=30,
        command_timeout_s=2.0,
        watchdog_enabled=False,
        watchdog_interval_s=30,
        watchdog_dns_host="example.org",
        watchdog_http_url="https://example.org/healthz",
        watchdog_timeout_s=1.0,
        usage_poll_interval_s=30,
        interface_name=None,
    )
    monitor = CellularMonitor(
        config,
        command_runner=command_runner,
        default_route_interface_detector=lambda: None,
        now_fn=lambda: datetime(2026, 2, 21, 10, 0, 0, tzinfo=timezone.utc),
    )

    metrics = monitor.read_metrics()

    assert "signal_rssi_dbm" not in metrics
