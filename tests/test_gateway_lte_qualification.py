from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from gateway_runtime.qualification import GatewayLteQualifier, QualificationError, read_pi_throttled


class Backend:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def power_on(self) -> None:
        self.calls.append("on")

    def power_off(self) -> None:
        self.calls.append("off")


def test_throttle_parser_requires_exact_zero_capable_output() -> None:
    class Result:
        returncode = 0
        stdout = "throttled=0x50005\n"

    assert read_pi_throttled(run_command=lambda *_args, **_kwargs: Result()) == 0x50005


def test_qualification_persists_each_success_and_leaves_modem_off(tmp_path: Path) -> None:
    backend = Backend()
    moments = iter((0.0, 10.0, 12.0, 14.0, 20.0, 23.0, 25.0, 30.0))
    report_path = tmp_path / "qualification.json"
    qualifier = GatewayLteQualifier(
        report_path=report_path,
        backend=backend,
        data_probe=lambda: True,
        throttled_source=lambda: 0,
        sleeper=lambda _seconds: None,
        clock=lambda: next(moments),
    )

    result = qualifier.run(cycles=2, off_settle_s=0)

    assert result["status"] == "passed"
    assert result["completed_cycles"] == 2
    assert backend.calls == ["off", "on", "off", "on", "off", "off"]
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "passed"
    assert len(persisted["cycles"]) == 2
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600


def test_qualification_fails_before_switching_when_pi_has_sticky_faults(tmp_path: Path) -> None:
    backend = Backend()
    qualifier = GatewayLteQualifier(
        report_path=tmp_path / "qualification.json",
        backend=backend,
        data_probe=lambda: True,
        throttled_source=lambda: 0x50000,
        sleeper=lambda _seconds: None,
        clock=lambda: 1.0,
    )

    with pytest.raises(QualificationError, match="0x0"):
        qualifier.run(cycles=1)

    assert backend.calls == []
    assert json.loads(qualifier.report_path.read_text())["failure"] == "pi_throttled_before_test"


def test_attach_timeout_records_failure_and_attempts_final_power_off(tmp_path: Path) -> None:
    backend = Backend()
    moments = iter((0.0, 10.0, 12.0, 14.0, 16.0))
    qualifier = GatewayLteQualifier(
        report_path=tmp_path / "qualification.json",
        backend=backend,
        data_probe=lambda: False,
        throttled_source=lambda: 0,
        sleeper=lambda _seconds: None,
        clock=lambda: next(moments),
    )

    with pytest.raises(QualificationError, match="did not attach"):
        qualifier.run(cycles=1, attach_timeout_s=1, off_settle_s=0)

    assert backend.calls == ["off", "on", "off"]
    assert json.loads(qualifier.report_path.read_text())["status"] == "failed"
