from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests


class CellularConfigError(ValueError):
    """Raised when cellular env configuration is invalid."""


CommandRunner = Callable[[list[str], float], str | None]
DnsProbe = Callable[[str, float], bool]
HttpProbe = Callable[[str, float], bool]
DefaultRouteInterfaceDetector = Callable[[], str | None]
InterfaceCounterReader = Callable[[str], tuple[int, int] | None]
NowFn = Callable[[], datetime]

_FLOAT_RE = re.compile(r"-?\d+(?:\.\d+)?")
_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
_FALSE_VALUES = {"0", "false", "no", "n", "off"}


@dataclass(frozen=True)
class CellularConfig:
    enabled: bool
    modem_id: str
    modem_poll_interval_s: int
    command_timeout_s: float
    watchdog_enabled: bool
    watchdog_interval_s: int
    watchdog_dns_host: str
    watchdog_http_url: str
    watchdog_timeout_s: float
    usage_poll_interval_s: int
    interface_name: str | None
    usage_state_path: Path | None = None


class CellularMonitor:
    """Collect best-effort cellular observability metrics for the edge agent."""

    def __init__(
        self,
        config: CellularConfig,
        *,
        command_runner: CommandRunner | None = None,
        dns_probe: DnsProbe | None = None,
        http_probe: HttpProbe | None = None,
        default_route_interface_detector: DefaultRouteInterfaceDetector | None = None,
        interface_counters: InterfaceCounterReader | None = None,
        now_fn: NowFn | None = None,
    ) -> None:
        self.config = config
        self._command_runner = command_runner or _run_command
        self._dns_probe = dns_probe or _default_dns_probe
        self._http_probe = http_probe or _default_http_probe
        self._default_route_interface_detector = (
            default_route_interface_detector or _detect_default_route_interface
        )
        self._interface_counter_reader = interface_counters or _read_interface_counters
        self._now_fn = now_fn or _utcnow

        self._cached_modem_metrics: dict[str, Any] = {}
        self._cached_watchdog_metrics: dict[str, Any] = {}
        self._cached_usage_metrics: dict[str, Any] = {}

        self._next_modem_poll_at = 0.0
        self._next_watchdog_poll_at = 0.0
        self._next_usage_poll_at = 0.0

        self._mmcli_available: bool | None = None
        self._interface_name = config.interface_name

        self._last_link_ok_at: datetime | None = None
        self._usage_state = self._load_usage_state()

    def read_metrics(self) -> dict[str, Any]:
        if not self.config.enabled:
            return {}

        now_dt = self._now_fn()
        now_s = max(0.0, now_dt.timestamp())

        if now_s >= self._next_modem_poll_at:
            self._cached_modem_metrics = self._poll_modem_metrics()
            self._next_modem_poll_at = now_s + float(self.config.modem_poll_interval_s)

        if self.config.watchdog_enabled and now_s >= self._next_watchdog_poll_at:
            self._cached_watchdog_metrics = self._poll_watchdog_metrics(now_dt)
            self._next_watchdog_poll_at = now_s + float(self.config.watchdog_interval_s)

        if now_s >= self._next_usage_poll_at:
            self._cached_usage_metrics = self._poll_usage_metrics(now_dt)
            self._next_usage_poll_at = now_s + float(self.config.usage_poll_interval_s)

        out: dict[str, Any] = {}
        out.update(self._cached_modem_metrics)
        out.update(self._cached_watchdog_metrics)
        out.update(self._cached_usage_metrics)
        return out

    def _poll_modem_metrics(self) -> dict[str, Any]:
        if not self._is_mmcli_available():
            return {}

        status_text = self._run_mmcli(["-m", self.config.modem_id, "--simple-status"])
        if not status_text:
            # ModemManager 1.24 removed --simple-status. A plain modem query
            # still exposes the registration state and supports key/value
            # output, so keep older releases working while supporting the
            # current Raspberry Pi OS package.
            status_text = self._run_mmcli(["-m", self.config.modem_id])
        signal_text = self._run_mmcli(["-m", self.config.modem_id, "--signal-get"])
        payload = "\n".join(part for part in (status_text, signal_text) if part)
        if not payload:
            return {}

        metrics: dict[str, Any] = {}

        registration = _parse_registration_state(status_text or payload)
        if registration:
            metrics["cellular_registration_state"] = registration

        metrics.update(_parse_signal_metrics(payload))
        return metrics

    def _poll_watchdog_metrics(self, now_dt: datetime) -> dict[str, Any]:
        try:
            dns_ok = bool(self._dns_probe(self.config.watchdog_dns_host, self.config.watchdog_timeout_s))
        except Exception:
            dns_ok = False

        try:
            http_ok = bool(self._http_probe(self.config.watchdog_http_url, self.config.watchdog_timeout_s))
        except Exception:
            http_ok = False

        link_ok = dns_ok and http_ok
        if link_ok:
            self._last_link_ok_at = now_dt

        metrics: dict[str, Any] = {"link_ok": bool(link_ok)}
        if self._last_link_ok_at is not None:
            metrics["link_last_ok_at"] = self._last_link_ok_at.isoformat()
        return metrics

    def _poll_usage_metrics(self, now_dt: datetime) -> dict[str, Any]:
        interface_name = self._resolve_interface_name()
        if not interface_name:
            return {}

        counters = self._interface_counter_reader(interface_name)
        if counters is None:
            return {}

        rx_bytes, tx_bytes = counters
        today = now_dt.date().isoformat()
        previous = self._usage_state
        if previous is None or previous["utc_day"] != today:
            received_today = 0
            sent_today = 0
        elif previous["interface"] != interface_name:
            # A newly selected cellular interface may already have carried
            # traffic before this poll. Count its current counters rather than
            # silently dropping that usage.
            received_today = int(previous["received_today"]) + max(0, int(rx_bytes))
            sent_today = int(previous["sent_today"]) + max(0, int(tx_bytes))
        else:
            previous_rx = int(previous["last_rx"])
            previous_tx = int(previous["last_tx"])
            # Kernel interface counters reset on modem reconnect and reboot.
            # When they move backwards, the current value is the post-reset
            # delta and must be added to the durable daily total.
            rx_delta = int(rx_bytes) - previous_rx if int(rx_bytes) >= previous_rx else int(rx_bytes)
            tx_delta = int(tx_bytes) - previous_tx if int(tx_bytes) >= previous_tx else int(tx_bytes)
            received_today = int(previous["received_today"]) + max(0, rx_delta)
            sent_today = int(previous["sent_today"]) + max(0, tx_delta)

        self._usage_state = {
            "utc_day": today,
            "interface": interface_name,
            "last_rx": max(0, int(rx_bytes)),
            "last_tx": max(0, int(tx_bytes)),
            "received_today": max(0, int(received_today)),
            "sent_today": max(0, int(sent_today)),
        }
        self._save_usage_state()

        return {
            "cellular_bytes_sent_today": sent_today,
            "cellular_bytes_received_today": received_today,
        }

    def _load_usage_state(self) -> dict[str, Any] | None:
        path = self.config.usage_state_path
        if path is None:
            return None
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return None
        if not isinstance(parsed, dict):
            return None
        try:
            utc_day = date.fromisoformat(str(parsed["utc_day"])).isoformat()
            interface = str(parsed["interface"]).strip()
            state = {
                "utc_day": utc_day,
                "interface": interface,
                "last_rx": max(0, int(parsed["last_rx"])),
                "last_tx": max(0, int(parsed["last_tx"])),
                "received_today": max(0, int(parsed["received_today"])),
                "sent_today": max(0, int(parsed["sent_today"])),
            }
        except (KeyError, TypeError, ValueError):
            return None
        return state if interface else None

    def _save_usage_state(self) -> None:
        path = self.config.usage_state_path
        if path is None or self._usage_state is None:
            return
        tmp_path: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=path.parent,
            )
            tmp_path = Path(tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                os.fchmod(tmp_file.fileno(), 0o600)
                tmp_file.write(json.dumps(self._usage_state, sort_keys=True) + "\n")
                tmp_file.flush()
                os.fsync(tmp_file.fileno())

            os.replace(tmp_path, path)
            tmp_path = None

            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_fd = os.open(path.parent, directory_flags)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Usage telemetry must never take down the edge agent. If the state
            # directory is temporarily unavailable, continue with the in-memory
            # counters and retry on the next poll.
            return
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _resolve_interface_name(self) -> str | None:
        if self._interface_name:
            return self._interface_name

        detected = self._default_route_interface_detector()
        if detected:
            self._interface_name = detected
        return detected

    def _is_mmcli_available(self) -> bool:
        if self._mmcli_available is None:
            self._mmcli_available = shutil.which("mmcli") is not None
        return bool(self._mmcli_available)

    def _run_mmcli(self, args: list[str]) -> str | None:
        keyvalue = self._command_runner(
            ["mmcli", *args, "--output-keyvalue"],
            self.config.command_timeout_s,
        )
        if keyvalue:
            return keyvalue
        return self._command_runner(["mmcli", *args], self.config.command_timeout_s)


def build_cellular_monitor_from_env() -> CellularMonitor | None:
    config = load_cellular_config_from_env()
    if not config.enabled:
        return None
    return CellularMonitor(config)


def load_cellular_config_from_env() -> CellularConfig:
    enabled = _parse_bool_env("CELLULAR_METRICS_ENABLED", default=False)

    modem_id = os.getenv("CELLULAR_MODEM_ID", "0").strip() or "0"
    modem_poll_interval_s = _parse_positive_int_env("CELLULAR_MODEM_POLL_INTERVAL_S", default=60)
    command_timeout_s = _parse_positive_float_env("CELLULAR_MMCLI_TIMEOUT_S", default=3.0)

    watchdog_enabled = _parse_bool_env("CELLULAR_WATCHDOG_ENABLED", default=enabled)
    watchdog_interval_s = _parse_positive_int_env("CELLULAR_WATCHDOG_INTERVAL_S", default=60)
    watchdog_dns_host = os.getenv("CELLULAR_WATCHDOG_DNS_HOST", "www.gstatic.com").strip()
    if not watchdog_dns_host:
        raise CellularConfigError("CELLULAR_WATCHDOG_DNS_HOST must be non-empty")

    watchdog_http_url = os.getenv(
        "CELLULAR_WATCHDOG_HTTP_URL",
        "https://www.gstatic.com/generate_204",
    ).strip()
    if not watchdog_http_url:
        raise CellularConfigError("CELLULAR_WATCHDOG_HTTP_URL must be non-empty")
    watchdog_timeout_s = _parse_positive_float_env("CELLULAR_WATCHDOG_TIMEOUT_S", default=2.5)

    usage_poll_interval_s = _parse_positive_int_env("CELLULAR_USAGE_POLL_INTERVAL_S", default=60)
    interface_name = os.getenv("CELLULAR_INTERFACE", "").strip() or None
    usage_state_raw = os.getenv("CELLULAR_USAGE_STATE_PATH", "").strip()
    usage_state_path = Path(usage_state_raw).expanduser() if usage_state_raw else None

    return CellularConfig(
        enabled=enabled,
        modem_id=modem_id,
        modem_poll_interval_s=modem_poll_interval_s,
        command_timeout_s=command_timeout_s,
        watchdog_enabled=watchdog_enabled,
        watchdog_interval_s=watchdog_interval_s,
        watchdog_dns_host=watchdog_dns_host,
        watchdog_http_url=watchdog_http_url,
        watchdog_timeout_s=watchdog_timeout_s,
        usage_poll_interval_s=usage_poll_interval_s,
        interface_name=interface_name,
        usage_state_path=usage_state_path,
    )


def _parse_bool_env(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    norm = raw.strip().lower()
    if norm in _TRUE_VALUES:
        return True
    if norm in _FALSE_VALUES:
        return False
    raise CellularConfigError(f"{name} must be one of: {sorted(_TRUE_VALUES | _FALSE_VALUES)}")


def _parse_positive_int_env(name: str, *, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return int(default)
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise CellularConfigError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise CellularConfigError(f"{name} must be > 0")
    return parsed


def _parse_positive_float_env(name: str, *, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return float(default)
    try:
        parsed = float(raw)
    except ValueError as exc:
        raise CellularConfigError(f"{name} must be a number") from exc
    if parsed <= 0:
        raise CellularConfigError(f"{name} must be > 0")
    return parsed


def _parse_signal_metrics(payload: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    patterns: tuple[tuple[str, str], ...] = (
        ("signal_rssi_dbm", r"\brssi\b[^-\d]*(-?\d+(?:\.\d+)?)"),
        ("cellular_rsrp_dbm", r"\brsrp\b[^-\d]*(-?\d+(?:\.\d+)?)"),
        ("cellular_rsrq_db", r"\brsrq\b[^-\d]*(-?\d+(?:\.\d+)?)"),
        ("cellular_sinr_db", r"\b(?:sinr|snr)\b[^-\d]*(-?\d+(?:\.\d+)?)"),
    )

    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        lower = line.lower()
        if "threshold" in lower or "refresh.rate" in lower:
            continue

        for key, pattern in patterns:
            value = _extract_float_from_text(line, pattern)
            if value is not None:
                metrics[key] = value
                break

    return metrics


def _parse_registration_state(payload: str) -> str | None:
    if not payload:
        return None

    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if "registration" not in lower or "state" not in lower:
            continue

        if "=" in line:
            value = line.split("=", 1)[1]
        elif ":" in line:
            value = line.split(":", 1)[1]
        else:
            continue

        cleaned = value.strip().strip("'\"").lower().replace(" ", "_")
        cleaned = re.sub(r"[^a-z0-9_-]", "", cleaned)
        if cleaned:
            return cleaned

    return None


def _extract_float_from_text(payload: str, pattern: str) -> float | None:
    match = re.search(pattern, payload, flags=re.IGNORECASE)
    if not match:
        return None
    token = match.group(1)
    found = _FLOAT_RE.search(token)
    if not found:
        return None
    try:
        return float(found.group(0))
    except ValueError:
        return None


def _run_command(command: list[str], timeout_s: float) -> str | None:
    try:
        proc = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(0.1, float(timeout_s)),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if proc.returncode != 0:
        return None

    out = proc.stdout.strip()
    err = proc.stderr.strip()
    return f"{out}\n{err}".strip()


def _default_dns_probe(hostname: str, timeout_s: float) -> bool:
    # getaddrinfo has no per-call timeout argument; we keep this best-effort.
    _ = timeout_s
    try:
        socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError:
        return False
    return True


def _default_http_probe(url: str, timeout_s: float) -> bool:
    try:
        resp = requests.head(url, timeout=timeout_s, allow_redirects=True)
        if resp.status_code == 405:
            resp = requests.get(url, timeout=timeout_s, allow_redirects=True, stream=True)
        return 200 <= resp.status_code < 500
    except requests.RequestException:
        return False


def _detect_default_route_interface() -> str | None:
    route_file = Path("/proc/net/route")
    try:
        lines = route_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines[1:]:
        cols = line.split()
        if len(cols) < 11:
            continue
        interface_name = cols[0]
        destination = cols[1]
        if destination == "00000000":
            return interface_name
    return None


def _read_interface_counters(interface_name: str) -> tuple[int, int] | None:
    stats_dir = Path("/sys/class/net") / interface_name / "statistics"
    try:
        rx_bytes = int((stats_dir / "rx_bytes").read_text(encoding="utf-8").strip())
        tx_bytes = int((stats_dir / "tx_bytes").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return rx_bytes, tx_bytes


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
