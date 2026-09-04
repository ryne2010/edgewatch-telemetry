"""Hardware qualification for electrically switched gateway LTE modems."""

from __future__ import annotations

import json
import os
import re
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .lte_power import GatewayPowerError, LtePowerBackend, SystemdLtePowerBackend


_THROTTLED = re.compile(r"throttled=(0x[0-9a-fA-F]+)\Z")


class QualificationError(RuntimeError):
    """A required hardware qualification observation failed."""


@dataclass(frozen=True)
class CycleEvidence:
    cycle: int
    attach_seconds: float
    started_at: float
    completed_at: float


def read_pi_throttled(*, run_command=subprocess.run) -> int:
    """Return Raspberry Pi sticky/current throttle flags and fail closed."""

    try:
        completed = run_command(
            ["/usr/bin/vcgencmd", "get_throttled"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("vcgencmd get_throttled could not be executed") from exc
    match = _THROTTLED.fullmatch(str(completed.stdout).strip())
    if completed.returncode != 0 or match is None:
        raise QualificationError("vcgencmd returned an invalid throttling result")
    return int(match.group(1), 16)


class BoundHttpsProbe:
    """Prove DNS, TCP, TLS, and HTTP while bound to the cellular interface."""

    def __init__(
        self,
        interface: str,
        *,
        url: str = "https://www.gstatic.com/generate_204",
        timeout_s: float = 15.0,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,32}", interface):
            raise ValueError("cellular interface is invalid")
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("qualification URL must be credential-free HTTPS")
        self.interface = interface
        self.parsed = parsed
        self.timeout_s = timeout_s

    def __call__(self) -> bool:
        host = self.parsed.hostname
        assert host is not None
        port = self.parsed.port or 443
        target = self.parsed.path or "/"
        if self.parsed.query:
            target += f"?{self.parsed.query}"
        for family, socktype, proto, _name, address in socket.getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        ):
            raw = socket.socket(family, socktype, proto)
            try:
                raw.settimeout(self.timeout_s)
                raw.setsockopt(
                    socket.SOL_SOCKET,
                    getattr(socket, "SO_BINDTODEVICE", 25),
                    self.interface.encode("ascii") + b"\0",
                )
                raw.connect(address)
                with ssl.create_default_context().wrap_socket(raw, server_hostname=host) as secured:
                    secured.sendall(
                        (
                            f"GET {target} HTTP/1.1\r\nHost: {host}\r\n"
                            "Connection: close\r\nUser-Agent: edgewatch-lte-qualification/1\r\n\r\n"
                        ).encode("ascii")
                    )
                    status = secured.makefile("rb").readline(4096).decode("ascii", errors="replace")
                fields = status.split()
                return len(fields) >= 2 and fields[0].startswith("HTTP/") and 200 <= int(fields[1]) < 400
            except (OSError, ssl.SSLError, ValueError):
                try:
                    raw.close()
                except OSError:
                    pass
        return False


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    finally:
        temp_path.unlink(missing_ok=True)


class GatewayLteQualifier:
    """Exercise modem power/attach cycles and reject any Pi throttle flag."""

    def __init__(
        self,
        *,
        report_path: Path,
        backend: LtePowerBackend | None = None,
        data_probe: Callable[[], bool],
        throttled_source: Callable[[], int] = read_pi_throttled,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.report_path = report_path
        self.backend = backend or SystemdLtePowerBackend()
        self.data_probe = data_probe
        self.throttled_source = throttled_source
        self.sleeper = sleeper
        self.clock = clock

    def run(
        self,
        *,
        cycles: int = 100,
        attach_timeout_s: float = 180.0,
        probe_interval_s: float = 2.0,
        off_settle_s: float = 10.0,
    ) -> dict[str, object]:
        if not 1 <= cycles <= 1_000:
            raise ValueError("cycles must be within 1..1000")
        if not 1 <= attach_timeout_s <= 900:
            raise ValueError("attach_timeout_s must be within 1..900")
        if not 0.1 <= probe_interval_s <= 30 or not 0 <= off_settle_s <= 300:
            raise ValueError("qualification timing is outside the allowed range")
        started_at = self.clock()
        evidence: list[CycleEvidence] = []
        report: dict[str, object] = {
            "schema_version": 1,
            "status": "running",
            "required_cycles": cycles,
            "completed_cycles": 0,
            "started_at": started_at,
            "cycles": [],
        }
        _write_report(self.report_path, report)
        if self.throttled_source() != 0:
            report.update(status="failed", failure="pi_throttled_before_test")
            _write_report(self.report_path, report)
            raise QualificationError("Pi throttling/undervoltage flags must be 0x0 before the test")

        try:
            self.backend.power_off()
            self.sleeper(off_settle_s)
            for cycle in range(1, cycles + 1):
                cycle_started = self.clock()
                self.backend.power_on()
                deadline = cycle_started + attach_timeout_s
                while not self.data_probe():
                    if self.clock() >= deadline:
                        raise QualificationError(f"LTE data path did not attach in cycle {cycle}")
                    self.sleeper(probe_interval_s)
                attached_at = self.clock()
                if self.throttled_source() != 0:
                    raise QualificationError(f"Pi throttling/undervoltage detected in cycle {cycle}")
                self.backend.power_off()
                self.sleeper(off_settle_s)
                if self.throttled_source() != 0:
                    raise QualificationError(f"Pi throttling/undervoltage detected in cycle {cycle}")
                completed_at = self.clock()
                evidence.append(
                    CycleEvidence(
                        cycle=cycle,
                        attach_seconds=max(0.0, attached_at - cycle_started),
                        started_at=cycle_started,
                        completed_at=completed_at,
                    )
                )
                report["completed_cycles"] = len(evidence)
                report["cycles"] = [asdict(item) for item in evidence]
                _write_report(self.report_path, report)
        except (QualificationError, GatewayPowerError) as exc:
            report.update(
                status="failed",
                completed_at=self.clock(),
                failure=type(exc).__name__,
            )
            _write_report(self.report_path, report)
            raise
        finally:
            try:
                self.backend.power_off()
            except GatewayPowerError:
                pass

        report.update(status="passed", completed_at=self.clock())
        _write_report(self.report_path, report)
        return report
