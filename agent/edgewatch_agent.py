from __future__ import annotations

import json
import os
import random
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import requests
from dotenv import load_dotenv

from buffer import SqliteBuffer
from cellular import CellularConfigError, build_cellular_monitor_from_env
from cost_caps import CostCapError, CostCapState
from device_policy import (
    CachedPolicy,
    DevicePolicy,
    fetch_device_policy,
    load_cached_policy,
    save_cached_policy,
)
from media import MediaConfigError, MediaUploadError, build_media_runtime_from_env
from power_management import PowerManagementError, PowerManager
from sensors import SensorConfigError, build_sensor_backend, load_sensor_config_from_env


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_point(metrics: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "message_id": uuid.uuid4().hex,
        "ts": utcnow_iso(),
        "metrics": metrics,
    }


class RateLimited(RuntimeError):
    """Raised when the server returns HTTP 429.

    retry_after_s is best-effort parsed from Retry-After.
    """

    def __init__(self, message: str, retry_after_s: float | None = None):
        super().__init__(message)
        self.retry_after_s = retry_after_s


def _parse_retry_after_seconds(headers: Mapping[str, Any]) -> float | None:
    """Parse Retry-After (seconds only). Returns None if unparseable."""

    ra = headers.get("Retry-After")
    if not ra:
        return None
    try:
        return float(str(ra).strip())
    except ValueError:
        return None


def _parse_positive_int_env(name: str, *, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        print(f"[edgewatch-agent] invalid {name}={raw!r}; using {default}")
        return default
    if value <= 0:
        print(f"[edgewatch-agent] invalid {name}={raw!r}; using {default}")
        return default
    return value


def _parse_optional_nonnegative_int_env(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        value = int(raw.strip())
    except ValueError:
        print(f"[edgewatch-agent] invalid {name}={raw!r}; using unbounded")
        return None
    if value <= 0:
        return None
    return value


def _parse_bool_env(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    print(f"[edgewatch-agent] invalid {name}={raw!r}; using {default}")
    return default


def _remote_shutdown_command() -> list[str]:
    raw = (os.getenv("EDGEWATCH_REMOTE_SHUTDOWN_CMD") or "sudo shutdown -h now").strip()
    if not raw:
        return ["sudo", "shutdown", "-h", "now"]
    try:
        parsed = shlex.split(raw)
    except ValueError:
        print("[edgewatch-agent] invalid EDGEWATCH_REMOTE_SHUTDOWN_CMD; using default 'sudo shutdown -h now'")
        return ["sudo", "shutdown", "-h", "now"]
    return parsed or ["sudo", "shutdown", "-h", "now"]


def _run_remote_shutdown(*, shutdown_grace_s: int, command_id: str) -> bool:
    grace_s = max(1, int(shutdown_grace_s))
    print(
        "[edgewatch-agent] executing remote shutdown command id=%s after grace period (%ss elapsed)"
        % (command_id, grace_s)
    )
    cmd = _remote_shutdown_command()
    try:
        # Intentional local-side-effect command; guarded by EDGEWATCH_ALLOW_REMOTE_SHUTDOWN.
        subprocess.run(cmd, check=False)
        return True
    except Exception as exc:
        print(f"[edgewatch-agent] remote shutdown command failed: {exc!r}")
        return False


def build_buffer_from_env(path: str) -> SqliteBuffer:
    return SqliteBuffer(
        path,
        max_db_bytes=_parse_optional_nonnegative_int_env("BUFFER_MAX_DB_BYTES"),
        journal_mode=os.getenv("BUFFER_SQLITE_JOURNAL_MODE", "WAL"),
        synchronous=os.getenv("BUFFER_SQLITE_SYNCHRONOUS", "NORMAL"),
        temp_store=os.getenv("BUFFER_SQLITE_TEMP_STORE", "MEMORY"),
        eviction_batch_size=_parse_positive_int_env("BUFFER_EVICTION_BATCH_SIZE", default=100),
        recover_corruption=_parse_bool_env("BUFFER_RECOVER_CORRUPTION", default=True),
    )


def post_points(
    session: requests.Session,
    api_url: str,
    token: str,
    points: List[Dict[str, Any]],
    timeout_s: float = 5.0,
) -> requests.Response:
    return session.post(
        f"{api_url.rstrip('/')}/api/v1/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={"points": points},
        timeout=timeout_s,
    )


def ack_control_command(
    session: requests.Session,
    *,
    api_url: str,
    token: str,
    command_id: str,
    timeout_s: float = 5.0,
) -> requests.Response:
    return session.post(
        f"{api_url.rstrip('/')}/api/v1/device-commands/{command_id}/ack",
        headers={"Authorization": f"Bearer {token}"},
        json={},
        timeout=timeout_s,
    )


def _command_state_path(device_id: str) -> Path:
    default = f"./edgewatch_command_state_{device_id}.json"
    raw = (os.getenv("EDGEWATCH_COMMAND_STATE_PATH") or default).strip()
    return Path(raw or default)


def _load_command_state(path: Path) -> tuple[str | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None
    except Exception:
        return None, None
    if not isinstance(data, dict):
        return None, None

    last_applied = data.get("last_applied_command_id")
    pending_ack = data.get("pending_ack_command_id")
    return (
        str(last_applied).strip() if isinstance(last_applied, str) and last_applied.strip() else None,
        str(pending_ack).strip() if isinstance(pending_ack, str) and pending_ack.strip() else None,
    )


def _save_command_state(
    path: Path,
    *,
    last_applied_command_id: str | None,
    pending_ack_command_id: str | None,
) -> None:
    payload = {
        "last_applied_command_id": last_applied_command_id,
        "pending_ack_command_id": pending_ack_command_id,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _parse_iso_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _estimate_ingest_payload_bytes(points: List[Dict[str, Any]]) -> int:
    payload = {"points": points}
    blob = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return len(blob.encode("utf-8"))


@dataclass
class AgentState:
    """In-memory agent state.

    This state is used for *device-side optimization* (cadence + buffering) and
    for hysteresis decisions. The server remains the source of truth for alerts.
    """

    last_state: str = "UNKNOWN"
    last_alerts: set[str] = field(default_factory=set)

    last_sent_at: float = 0.0
    last_heartbeat_at: float = 0.0
    last_alert_snapshot_at: float = 0.0
    last_metrics_snapshot: Dict[str, Any] = field(default_factory=dict)

    consecutive_failures: int = 0
    next_network_attempt_at: float = 0.0
    last_cost_cap_active: bool = False
    last_snapshot_cap_log_at: float = 0.0
    last_power_saver_active: bool = False
    last_power_saver_log_at: float = 0.0
    disabled_latched: bool = False
    last_disabled_log_at: float = 0.0
    last_command_ack_log_at: float = 0.0
    pending_shutdown_command_id: str | None = None
    pending_shutdown_execute_at: float = 0.0
    pending_shutdown_grace_s: int = 0
    last_shutdown_log_at: float = 0.0


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _as_float(v: Any) -> float | None:
    if _is_number(v):
        return float(v)
    return None


def _as_bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    return None


def _changed_keys(
    *,
    current: Mapping[str, Any],
    previous: Mapping[str, Any],
    thresholds: Mapping[str, float],
) -> List[str]:
    """Return metric keys that changed enough to be worth sending."""

    changed: List[str] = []

    for k, cur in current.items():
        prev = previous.get(k)

        # Always send when a key is first observed.
        if k not in previous:
            changed.append(k)
            continue

        # Treat None as "no update".
        if cur is None:
            continue

        # Booleans/strings: equality.
        if isinstance(cur, bool) or isinstance(prev, bool):
            if bool(cur) != bool(prev):
                changed.append(k)
            continue

        if isinstance(cur, str) or isinstance(prev, str):
            if str(cur) != str(prev):
                changed.append(k)
            continue

        # Numbers: absolute delta threshold.
        cur_f = _as_float(cur)
        prev_f = _as_float(prev)
        if cur_f is not None and prev_f is not None:
            thresh = float(thresholds.get(k, 0.0))
            if abs(cur_f - prev_f) >= thresh:
                changed.append(k)
            continue

        # Fallback: compare raw values.
        if cur != prev:
            changed.append(k)

    return changed


def _compute_alerts(metrics: Mapping[str, Any], prev_alerts: set[str], policy: DevicePolicy) -> set[str]:
    """Compute active alerts with per-alert hysteresis.

    IMPORTANT: Hysteresis must be *per alert*, not tied to the coarse overall
    device state. Otherwise, one active alert (e.g. battery low) can incorrectly
    influence hysteresis for a different alert (e.g. water pressure).

    We also treat missing/non-numeric readings as "sticky": if an alert was
    previously active and the reading is unavailable, we keep it active until
    we observe a reading that satisfies recovery.
    """

    def _low_alert(key: str, value: float | None, *, low: float, recover: float) -> bool:
        prev = key in prev_alerts
        if value is None:
            return prev
        if prev:
            return value < recover
        return value < low

    alerts: set[str] = set()

    wp = _as_float(metrics.get("water_pressure_psi"))
    if _low_alert(
        "WATER_PRESSURE_LOW",
        wp,
        low=policy.alert_thresholds.water_pressure_low_psi,
        recover=policy.alert_thresholds.water_pressure_recover_psi,
    ):
        alerts.add("WATER_PRESSURE_LOW")

    oil_p = _as_float(metrics.get("oil_pressure_psi"))
    if _low_alert(
        "OIL_PRESSURE_LOW",
        oil_p,
        low=policy.alert_thresholds.oil_pressure_low_psi,
        recover=policy.alert_thresholds.oil_pressure_recover_psi,
    ):
        alerts.add("OIL_PRESSURE_LOW")

    oil_lvl = _as_float(metrics.get("oil_level_pct"))
    if _low_alert(
        "OIL_LEVEL_LOW",
        oil_lvl,
        low=policy.alert_thresholds.oil_level_low_pct,
        recover=policy.alert_thresholds.oil_level_recover_pct,
    ):
        alerts.add("OIL_LEVEL_LOW")

    drip = _as_float(metrics.get("drip_oil_level_pct"))
    if _low_alert(
        "DRIP_OIL_LEVEL_LOW",
        drip,
        low=policy.alert_thresholds.drip_oil_level_low_pct,
        recover=policy.alert_thresholds.drip_oil_level_recover_pct,
    ):
        alerts.add("DRIP_OIL_LEVEL_LOW")

    oil_life = _as_float(metrics.get("oil_life_pct"))
    if _low_alert(
        "OIL_LIFE_LOW",
        oil_life,
        low=policy.alert_thresholds.oil_life_low_pct,
        recover=policy.alert_thresholds.oil_life_recover_pct,
    ):
        alerts.add("OIL_LIFE_LOW")

    batt = _as_float(metrics.get("battery_v"))
    if _low_alert(
        "BATTERY_LOW",
        batt,
        low=policy.alert_thresholds.battery_low_v,
        recover=policy.alert_thresholds.battery_recover_v,
    ):
        alerts.add("BATTERY_LOW")

    sig = _as_float(metrics.get("signal_rssi_dbm"))
    if _low_alert(
        "SIGNAL_LOW",
        sig,
        low=policy.alert_thresholds.signal_low_rssi_dbm,
        recover=policy.alert_thresholds.signal_recover_rssi_dbm,
    ):
        alerts.add("SIGNAL_LOW")

    microphone_level_db = _as_float(metrics.get("microphone_level_db"))
    if _low_alert(
        "MICROPHONE_OFFLINE",
        microphone_level_db,
        low=policy.alert_thresholds.microphone_offline_db,
        recover=policy.alert_thresholds.microphone_offline_db,
    ):
        alerts.add("MICROPHONE_OFFLINE")

    power_input_out_of_range = _as_bool(metrics.get("power_input_out_of_range"))
    if power_input_out_of_range:
        alerts.add("POWER_INPUT_OUT_OF_RANGE")

    power_unsustainable = _as_bool(metrics.get("power_unsustainable"))
    if power_unsustainable:
        alerts.add("POWER_UNSUSTAINABLE")

    return alerts


def _compute_state(
    metrics: Mapping[str, Any],
    prev_alerts: set[str],
    policy: DevicePolicy,
) -> tuple[str, set[str]]:
    """Compute coarse device state + active alert set."""

    alerts = _compute_alerts(metrics, prev_alerts, policy)
    return ("WARN" if alerts else "OK"), alerts


def _minimal_heartbeat_metrics(metrics: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k in (
        "microphone_level_db",
        "battery_v",
        "signal_rssi_dbm",
        "power_input_v",
        "power_input_a",
        "power_input_w",
        "power_source",
        "power_input_out_of_range",
        "power_unsustainable",
        "power_saver_active",
        "water_pressure_psi",
        "pump_on",
    ):
        if k in metrics:
            out[k] = metrics[k]
    return out


def _resolve_runtime_cadence(
    *,
    policy: DevicePolicy,
    critical_active: bool,
    power_saver_active: bool,
    operation_mode: str,
    sleep_poll_interval_s: int,
) -> tuple[int, int]:
    sleep_interval = max(60, int(sleep_poll_interval_s))
    if operation_mode == "sleep":
        return (sleep_interval, sleep_interval)
    if power_saver_active:
        return (
            policy.power_management.saver_sample_interval_s,
            policy.power_management.saver_heartbeat_interval_s,
        )
    return (
        policy.reporting.alert_sample_interval_s if critical_active else policy.reporting.sample_interval_s,
        policy.reporting.heartbeat_interval_s,
    )


def _media_disabled_by_operation(*, operation_mode: str) -> bool:
    return operation_mode in {"sleep", "disabled"}


def _media_disabled_by_power(*, policy: DevicePolicy, power_saver_active: bool) -> bool:
    return power_saver_active and policy.power_management.media_disabled_in_saver


def _normalized_operation_mode(raw: str) -> str:
    mode = (raw or "active").strip().lower()
    if mode in {"active", "sleep", "disabled"}:
        return mode
    return "active"


def _apply_pending_control_command_override(
    *,
    policy: DevicePolicy,
    last_applied_command_id: str | None,
    pending_ack_command_id: str | None,
    command_state_path: Path,
    now_utc: datetime | None = None,
) -> tuple[str, int, str | None, str | None, str | None]:
    operation_mode = _normalized_operation_mode(policy.operation_mode)
    sleep_poll_interval_s = max(60, int(policy.sleep_poll_interval_s))
    applied_command_id: str | None = None

    pending_command = policy.pending_control_command
    ts = now_utc or datetime.now(timezone.utc)
    if pending_command is None:
        return (
            operation_mode,
            sleep_poll_interval_s,
            last_applied_command_id,
            pending_ack_command_id,
            applied_command_id,
        )

    expires_at = _parse_iso_utc(pending_command.expires_at)
    command_active = expires_at is None or ts < expires_at
    if not command_active:
        return (
            operation_mode,
            sleep_poll_interval_s,
            last_applied_command_id,
            pending_ack_command_id,
            applied_command_id,
        )

    operation_mode = _normalized_operation_mode(pending_command.operation_mode)
    sleep_poll_interval_s = max(60, int(pending_command.sleep_poll_interval_s))

    if pending_command.id != last_applied_command_id:
        last_applied_command_id = pending_command.id
        pending_ack_command_id = pending_command.id
        applied_command_id = pending_command.id
        _save_command_state(
            command_state_path,
            last_applied_command_id=last_applied_command_id,
            pending_ack_command_id=pending_ack_command_id,
        )

    return (
        operation_mode,
        sleep_poll_interval_s,
        last_applied_command_id,
        pending_ack_command_id,
        applied_command_id,
    )


def _maybe_ack_pending_command(
    *,
    session: requests.Session,
    api_url: str,
    token: str,
    pending_ack_command_id: str | None,
    last_applied_command_id: str | None,
    command_state_path: Path,
    now_s: float,
    last_log_at: float,
) -> tuple[str | None, float]:
    if not pending_ack_command_id:
        return pending_ack_command_id, last_log_at

    try:
        ack_resp = ack_control_command(
            session,
            api_url=api_url,
            token=token,
            command_id=pending_ack_command_id,
        )
        if ack_resp.status_code == 429:
            raise RateLimited(
                "device command ack rate limited (429)",
                retry_after_s=_parse_retry_after_seconds(ack_resp.headers),
            )
        if 200 <= ack_resp.status_code < 300 or ack_resp.status_code == 404:
            if ack_resp.status_code == 404:
                print(
                    "[edgewatch-agent] command ack target missing on server; clearing local pending ack id=%s"
                    % pending_ack_command_id
                )
            pending_ack_command_id = None
            _save_command_state(
                command_state_path,
                last_applied_command_id=last_applied_command_id,
                pending_ack_command_id=pending_ack_command_id,
            )
            return pending_ack_command_id, last_log_at

        if now_s - last_log_at >= 300.0:
            print(
                "[edgewatch-agent] command ack failed id=%s status=%s body=%s"
                % (
                    pending_ack_command_id,
                    ack_resp.status_code,
                    (ack_resp.text or "")[:200],
                )
            )
            return pending_ack_command_id, now_s
        return pending_ack_command_id, last_log_at
    except Exception as exc:
        if now_s - last_log_at >= 300.0:
            print(f"[edgewatch-agent] command ack failed (will retry): {exc!r}")
            return pending_ack_command_id, now_s
        return pending_ack_command_id, last_log_at


def _clear_pending_shutdown_state(state: AgentState) -> None:
    state.pending_shutdown_command_id = None
    state.pending_shutdown_execute_at = 0.0
    state.pending_shutdown_grace_s = 0


def _sync_pending_shutdown_state(
    *,
    state: AgentState,
    pending_command: Any,
    last_applied_command_id: str | None,
    now_utc: datetime,
    now_s: float,
) -> None:
    pending_shutdown_intent = False
    if pending_command is not None and getattr(pending_command, "id", None) == last_applied_command_id:
        expires_at = _parse_iso_utc(getattr(pending_command, "expires_at", None))
        command_active = expires_at is None or now_utc < expires_at
        pending_shutdown_intent = bool(
            command_active
            and bool(getattr(pending_command, "shutdown_requested", False))
            and _normalized_operation_mode(getattr(pending_command, "operation_mode", "active")) == "disabled"
        )
        if pending_shutdown_intent:
            grace_s = max(1, int(getattr(pending_command, "shutdown_grace_s", 30)))
            if state.pending_shutdown_command_id != pending_command.id:
                state.pending_shutdown_command_id = pending_command.id
                state.pending_shutdown_grace_s = grace_s
                state.pending_shutdown_execute_at = now_s + float(grace_s)
                state.last_shutdown_log_at = 0.0

    if not pending_shutdown_intent and state.pending_shutdown_command_id is not None:
        _clear_pending_shutdown_state(state)


def _maybe_execute_pending_shutdown(
    *,
    state: AgentState,
    pending_ack_command_id: str | None,
    allow_remote_shutdown: bool,
    now_s: float,
) -> bool:
    if state.pending_shutdown_command_id is None:
        return False
    if pending_ack_command_id == state.pending_shutdown_command_id:
        if now_s - state.last_shutdown_log_at >= 60.0:
            print(
                "[edgewatch-agent] waiting for ack before shutdown id=%s" % state.pending_shutdown_command_id
            )
            state.last_shutdown_log_at = now_s
        return False
    if pending_ack_command_id is not None:
        return False

    if not allow_remote_shutdown:
        if now_s - state.last_shutdown_log_at >= 60.0:
            print(
                "[edgewatch-agent] shutdown command id=%s acknowledged but remote shutdown is disabled "
                "(set EDGEWATCH_ALLOW_REMOTE_SHUTDOWN=1 to allow)" % state.pending_shutdown_command_id
            )
            state.last_shutdown_log_at = now_s
        _clear_pending_shutdown_state(state)
        return False

    if now_s < state.pending_shutdown_execute_at:
        if now_s - state.last_shutdown_log_at >= 60.0:
            remaining = max(1, int(state.pending_shutdown_execute_at - now_s))
            print(
                "[edgewatch-agent] shutdown id=%s scheduled in %ss"
                % (state.pending_shutdown_command_id, remaining)
            )
            state.last_shutdown_log_at = now_s
        return False

    shutdown_command_id = state.pending_shutdown_command_id
    shutdown_grace_s = state.pending_shutdown_grace_s or 30
    if _run_remote_shutdown(
        shutdown_grace_s=shutdown_grace_s,
        command_id=shutdown_command_id,
    ):
        _clear_pending_shutdown_state(state)
        return True

    # Retry shutdown execution later if command invocation fails.
    state.pending_shutdown_execute_at = now_s + 300.0
    state.last_shutdown_log_at = now_s
    return False


def _flush_buffer(
    *,
    session: requests.Session,
    buf: SqliteBuffer,
    api_url: str,
    token: str,
    max_points_per_batch: int,
    on_batch_sent: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
) -> bool:
    """Flush queued points.

    Robustness notes
    - If the API returns a validation error (HTTP 422) for a batch, we fall back
      to sending points individually to isolate a "poison" message.
    - Poison messages are written to a dead-letter file and removed from the queue
      so they don't block the entire buffer.

    Returns True if the queue is fully drained (or was empty). Returns False on
    transient failure.
    """

    deadletter_path = os.getenv("EDGEWATCH_DEADLETTER_PATH")
    if not deadletter_path:
        # Default to a device-scoped file.
        device_id = os.getenv("EDGEWATCH_DEVICE_ID", "device")
        deadletter_path = f"./edgewatch_deadletter_{device_id}.jsonl"

    def _deadletter(payload: Dict[str, Any], *, status_code: int, body: str) -> None:
        try:
            record = {
                "ts": utcnow_iso(),
                "status_code": status_code,
                "body": body[:1000],
                "payload": payload,
            }
            with open(deadletter_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, sort_keys=True) + "\n")
        except Exception:
            # Best-effort; never crash the agent due to deadletter.
            return

    while True:
        queued = buf.dequeue_batch(limit=max_points_per_batch)
        if not queued:
            return True

        resp = post_points(session, api_url, token, [m.payload for m in queued])

        if resp.status_code == 429:
            ra = _parse_retry_after_seconds(resp.headers)
            raise RateLimited("buffer flush rate limited (429)", retry_after_s=ra)
        if 200 <= resp.status_code < 300:
            if on_batch_sent is not None:
                try:
                    on_batch_sent([m.payload for m in queued])
                except Exception:
                    pass
            for m in queued:
                buf.delete(m.message_id)
            continue

        # Validation failure: bisect by sending individually.
        if resp.status_code == 422:
            for m in queued:
                r2 = post_points(session, api_url, token, [m.payload])

                if r2.status_code == 429:
                    ra = _parse_retry_after_seconds(r2.headers)
                    raise RateLimited("buffer flush single-message rate limited (429)", retry_after_s=ra)
                if 200 <= r2.status_code < 300:
                    if on_batch_sent is not None:
                        try:
                            on_batch_sent([m.payload])
                        except Exception:
                            pass
                    buf.delete(m.message_id)
                elif r2.status_code == 422:
                    _deadletter(m.payload, status_code=r2.status_code, body=r2.text)
                    buf.delete(m.message_id)
                else:
                    # Transient-ish failure; keep remaining messages for later.
                    return False
            continue

        return False


def _default_policy(device_id: str) -> DevicePolicy:
    """Fallback policy when the API is unavailable."""

    # Conservative defaults: low-ish network usage, but still demo-friendly.
    # In production, policy should come from /api/v1/device-policy.
    from device_policy import AlertThresholds, CostCaps, PowerManagement, ReportingPolicy

    reporting = ReportingPolicy(
        sample_interval_s=int(os.getenv("SAMPLE_INTERVAL_S", "600")),
        alert_sample_interval_s=int(os.getenv("ALERT_SAMPLE_INTERVAL_S", "600")),
        heartbeat_interval_s=int(os.getenv("HEARTBEAT_INTERVAL_S", "600")),
        alert_report_interval_s=int(os.getenv("ALERT_REPORT_INTERVAL_S", "600")),
        max_points_per_batch=int(os.getenv("MAX_POINTS_PER_BATCH", "50")),
        buffer_max_points=int(os.getenv("BUFFER_MAX_POINTS", "5000")),
        buffer_max_age_s=int(os.getenv("BUFFER_MAX_AGE_S", str(7 * 24 * 3600))),
        backoff_initial_s=int(os.getenv("BACKOFF_INITIAL_S", "5")),
        backoff_max_s=int(os.getenv("BACKOFF_MAX_S", "300")),
    )

    alerts = AlertThresholds(
        microphone_offline_db=float(os.getenv("MICROPHONE_OFFLINE_DB", "60.0")),
        microphone_offline_open_consecutive_samples=int(
            os.getenv("MICROPHONE_OFFLINE_OPEN_CONSECUTIVE_SAMPLES", "2")
        ),
        microphone_offline_resolve_consecutive_samples=int(
            os.getenv("MICROPHONE_OFFLINE_RESOLVE_CONSECUTIVE_SAMPLES", "1")
        ),
        water_pressure_low_psi=float(os.getenv("WATER_PRESSURE_LOW_PSI", "30.0")),
        water_pressure_recover_psi=float(os.getenv("WATER_PRESSURE_RECOVER_PSI", "32.0")),
        oil_pressure_low_psi=float(os.getenv("OIL_PRESSURE_LOW_PSI", "20.0")),
        oil_pressure_recover_psi=float(os.getenv("OIL_PRESSURE_RECOVER_PSI", "22.0")),
        oil_level_low_pct=float(os.getenv("OIL_LEVEL_LOW_PCT", "20.0")),
        oil_level_recover_pct=float(os.getenv("OIL_LEVEL_RECOVER_PCT", "25.0")),
        drip_oil_level_low_pct=float(os.getenv("DRIP_OIL_LEVEL_LOW_PCT", "20.0")),
        drip_oil_level_recover_pct=float(os.getenv("DRIP_OIL_LEVEL_RECOVER_PCT", "25.0")),
        oil_life_low_pct=float(os.getenv("OIL_LIFE_LOW_PCT", "15.0")),
        oil_life_recover_pct=float(os.getenv("OIL_LIFE_RECOVER_PCT", "20.0")),
        battery_low_v=float(os.getenv("BATTERY_LOW_V", "11.8")),
        battery_recover_v=float(os.getenv("BATTERY_RECOVER_V", "12.0")),
        signal_low_rssi_dbm=float(os.getenv("SIGNAL_LOW_RSSI_DBM", "-95")),
        signal_recover_rssi_dbm=float(os.getenv("SIGNAL_RECOVER_RSSI_DBM", "-90")),
    )

    cost_caps = CostCaps(
        max_bytes_per_day=int(os.getenv("MAX_BYTES_PER_DAY", "50000000")),
        max_snapshots_per_day=int(os.getenv("MAX_SNAPSHOTS_PER_DAY", "48")),
        max_media_uploads_per_day=int(os.getenv("MAX_MEDIA_UPLOADS_PER_DAY", "48")),
    )

    power_management = PowerManagement(
        enabled=_parse_bool_env("POWER_MGMT_ENABLED", default=True),
        mode=os.getenv("POWER_MGMT_MODE", "dual").strip().lower() or "dual",
        input_warn_min_v=float(os.getenv("POWER_INPUT_WARN_MIN_V", "11.8")),
        input_warn_max_v=float(os.getenv("POWER_INPUT_WARN_MAX_V", "14.8")),
        input_critical_min_v=float(os.getenv("POWER_INPUT_CRITICAL_MIN_V", "11.4")),
        input_critical_max_v=float(os.getenv("POWER_INPUT_CRITICAL_MAX_V", "15.2")),
        sustainable_input_w=float(os.getenv("POWER_SUSTAINABLE_INPUT_W", "15.0")),
        unsustainable_window_s=int(os.getenv("POWER_UNSUSTAINABLE_WINDOW_S", "900")),
        battery_trend_window_s=int(os.getenv("POWER_BATTERY_TREND_WINDOW_S", "1800")),
        battery_drop_warn_v=float(os.getenv("POWER_BATTERY_DROP_WARN_V", "0.25")),
        saver_sample_interval_s=int(os.getenv("POWER_SAVER_SAMPLE_INTERVAL_S", "1200")),
        saver_heartbeat_interval_s=int(os.getenv("POWER_SAVER_HEARTBEAT_INTERVAL_S", "1800")),
        media_disabled_in_saver=_parse_bool_env("POWER_MEDIA_DISABLED_IN_SAVER", default=True),
    )

    return DevicePolicy(
        device_id=device_id,
        policy_version="fallback",
        policy_sha256="",
        cache_max_age_s=3600,
        heartbeat_interval_s=reporting.heartbeat_interval_s,
        offline_after_s=int(os.getenv("OFFLINE_AFTER_S", "600")),
        operation_mode=_normalized_operation_mode(os.getenv("OPERATION_MODE", "active")),
        sleep_poll_interval_s=max(60, int(os.getenv("SLEEP_POLL_INTERVAL_S", str(7 * 24 * 3600)))),
        disable_requires_manual_restart=_parse_bool_env("DISABLE_REQUIRES_MANUAL_RESTART", default=True),
        reporting=reporting,
        delta_thresholds={
            "microphone_level_db": float(os.getenv("DELTA_MICROPHONE_LEVEL_DB", "1.0")),
            "power_input_v": float(os.getenv("DELTA_POWER_INPUT_V", "0.1")),
            "power_input_a": float(os.getenv("DELTA_POWER_INPUT_A", "0.1")),
            "power_input_w": float(os.getenv("DELTA_POWER_INPUT_W", "0.5")),
            "temperature_c": float(os.getenv("DELTA_TEMPERATURE_C", "0.5")),
            "humidity_pct": float(os.getenv("DELTA_HUMIDITY_PCT", "2.0")),
            "oil_pressure_psi": float(os.getenv("DELTA_OIL_PRESSURE_PSI", "1.0")),
            "oil_level_pct": float(os.getenv("DELTA_OIL_LEVEL_PCT", "1.0")),
            "oil_life_pct": float(os.getenv("DELTA_OIL_LIFE_PCT", "1.0")),
            "drip_oil_level_pct": float(os.getenv("DELTA_DRIP_OIL_LEVEL_PCT", "1.0")),
            "water_pressure_psi": float(os.getenv("DELTA_WATER_PRESSURE_PSI", "1.0")),
            "flow_rate_gpm": float(os.getenv("DELTA_FLOW_RATE_GPM", "0.5")),
            "battery_v": float(os.getenv("DELTA_BATTERY_V", "0.05")),
            "signal_rssi_dbm": float(os.getenv("DELTA_SIGNAL_RSSI_DBM", "2")),
        },
        alert_thresholds=alerts,
        cost_caps=cost_caps,
        power_management=power_management,
        pending_control_command=None,
    )


def _maybe_prune(buf: SqliteBuffer, policy: DevicePolicy) -> None:
    try:
        deleted = buf.prune(
            max_messages=policy.reporting.buffer_max_points,
            max_age_s=policy.reporting.buffer_max_age_s,
        )
        if deleted:
            print(f"[edgewatch-agent] pruned {deleted} buffered points (queue={buf.count()})")
    except Exception as e:
        print(f"[edgewatch-agent] prune failed: {e!r}")


def _sleep(seconds: float) -> None:
    time.sleep(max(1.0, float(seconds)))


def _mark_point_recorded(state: AgentState, *, now: float, reason: str, alerts: set[str]) -> None:
    """Update scheduling markers when a point is *recorded*.

    We intentionally treat "buffered" points as recorded for scheduling purposes;
    otherwise an offline device would generate excessive heartbeat points and
    burn disk/battery.

    Notes on battery/data optimization:
    - Any recorded point (sent or buffered) counts as "liveness", so we update the heartbeat
      marker on every record. This avoids redundant heartbeat messages when the device is
      already sending deltas/snapshots.
    - Alert snapshot markers are updated only for "critical" alerts (currently: water pressure).
      Non-critical alerts still trigger an immediate send on entry/exit, but they do not
      cause periodic full snapshots by default.
    """

    state.last_sent_at = now

    # Any point proves liveness; avoid redundant heartbeats.
    state.last_heartbeat_at = now

    critical_active = "WATER_PRESSURE_LOW" in alerts
    if critical_active and reason in {"alert_snapshot", "state_change", "alert_change", "startup"}:
        state.last_alert_snapshot_at = now


def main() -> None:
    # Load repo-level .env (if present), then agent-local overrides.
    load_dotenv()
    load_dotenv(Path(__file__).resolve().parent / ".env")

    api_url = os.getenv("EDGEWATCH_API_URL", "http://localhost:8082")
    device_id = os.getenv("EDGEWATCH_DEVICE_ID", "demo-well-001")
    token = os.getenv("EDGEWATCH_DEVICE_TOKEN", "dev-device-token-001")

    buffer_path = os.getenv("BUFFER_DB_PATH", "./edgewatch_buffer.sqlite")
    buf = build_buffer_from_env(buffer_path)

    try:
        sensor_config = load_sensor_config_from_env()
        sensor_backend = build_sensor_backend(device_id=device_id, config=sensor_config)
    except SensorConfigError as exc:
        raise SystemExit(f"[edgewatch-agent] invalid sensor config: {exc}") from exc

    try:
        cellular_monitor = build_cellular_monitor_from_env()
    except CellularConfigError as exc:
        raise SystemExit(f"[edgewatch-agent] invalid cellular config: {exc}") from exc

    session = requests.Session()

    cached: Optional[CachedPolicy] = load_cached_policy()
    policy: DevicePolicy = cached.policy if cached else _default_policy(device_id)

    next_policy_refresh_at = 0.0
    if cached:
        next_policy_refresh_at = cached.fetched_at + float(policy.cache_max_age_s)

    media_runtime = None
    try:
        media_runtime = build_media_runtime_from_env(device_id=device_id)
    except MediaConfigError as exc:
        print(f"[edgewatch-agent] media disabled: {exc}")
    except Exception as exc:
        print(f"[edgewatch-agent] media disabled due to setup error: {exc!r}")

    try:
        cost_cap_state = CostCapState.from_env(device_id=device_id)
    except CostCapError as exc:
        raise SystemExit(f"[edgewatch-agent] invalid cost-cap config: {exc}") from exc

    try:
        power_manager = PowerManager.from_env(device_id=device_id)
    except PowerManagementError as exc:
        raise SystemExit(f"[edgewatch-agent] invalid power-management config: {exc}") from exc

    allow_remote_shutdown = _parse_bool_env("EDGEWATCH_ALLOW_REMOTE_SHUTDOWN", default=False)
    command_state_path = _command_state_path(device_id)
    last_applied_command_id, pending_ack_command_id = _load_command_state(command_state_path)

    print(
        "[edgewatch-agent] device_id=%s api=%s buffer=%s policy=%s sensors=%s media=%s cellular=%s "
        "cost_caps=%s power_state=%s command_state=%s remote_shutdown=%s"
        % (
            device_id,
            api_url,
            buffer_path,
            policy.policy_version,
            sensor_config.backend,
            "enabled" if media_runtime is not None else "disabled",
            "enabled" if cellular_monitor is not None else "disabled",
            cost_cap_state.path,
            power_manager.path,
            command_state_path,
            "enabled" if allow_remote_shutdown else "disabled",
        )
    )

    state = AgentState()

    while True:
        now = time.time()

        # Refresh device policy (best-effort).
        if now >= next_policy_refresh_at:
            try:
                pol, etag, max_age = fetch_device_policy(session, api_url=api_url, token=token, cached=cached)
                if pol is not None:
                    policy = pol
                    if etag:
                        save_cached_policy(policy, etag)
                        cached = load_cached_policy()  # reload to keep fetched_at

                ttl = max_age if max_age is not None else policy.cache_max_age_s
                next_policy_refresh_at = time.time() + float(ttl)
            except Exception as e:
                # Fall back to existing policy; retry soon.
                print(f"[edgewatch-agent] policy fetch failed (using cached/default): {e!r}")
                next_policy_refresh_at = time.time() + 60.0

        pending_ack_command_id, state.last_command_ack_log_at = _maybe_ack_pending_command(
            session=session,
            api_url=api_url,
            token=token,
            pending_ack_command_id=pending_ack_command_id,
            last_applied_command_id=last_applied_command_id,
            command_state_path=command_state_path,
            now_s=now,
            last_log_at=state.last_command_ack_log_at,
        )

        (
            operation_mode,
            sleep_poll_interval_s,
            last_applied_command_id,
            pending_ack_command_id,
            applied_command_id,
        ) = _apply_pending_control_command_override(
            policy=policy,
            last_applied_command_id=last_applied_command_id,
            pending_ack_command_id=pending_ack_command_id,
            command_state_path=command_state_path,
            now_utc=datetime.now(timezone.utc),
        )
        if applied_command_id is not None:
            print(
                "[edgewatch-agent] applied pending control command id=%s mode=%s sleep_poll_interval_s=%s"
                % (
                    applied_command_id,
                    operation_mode,
                    sleep_poll_interval_s,
                )
            )

        _sync_pending_shutdown_state(
            state=state,
            pending_command=policy.pending_control_command,
            last_applied_command_id=last_applied_command_id,
            now_utc=datetime.now(timezone.utc),
            now_s=now,
        )
        if _maybe_execute_pending_shutdown(
            state=state,
            pending_ack_command_id=pending_ack_command_id,
            allow_remote_shutdown=allow_remote_shutdown,
            now_s=now,
        ):
            # If shutdown command did not terminate process immediately,
            # avoid continuing business logic in this loop.
            _sleep(5.0)
            continue

        if state.disabled_latched:
            if now - state.last_disabled_log_at >= 300.0:
                print(
                    "[edgewatch-agent] device is latched disabled; restart service locally to resume telemetry/media"
                )
                state.last_disabled_log_at = now
            _sleep(sleep_poll_interval_s)
            continue

        if operation_mode == "disabled":
            if policy.disable_requires_manual_restart:
                state.disabled_latched = True
                state.last_disabled_log_at = now
                print(
                    "[edgewatch-agent] operation_mode=disabled received; latching disabled until local restart"
                )
                _sleep(sleep_poll_interval_s)
                continue
            if now - state.last_disabled_log_at >= 300.0:
                print("[edgewatch-agent] operation_mode=disabled active; telemetry/media paused")
                state.last_disabled_log_at = now
            _sleep(sleep_poll_interval_s)
            continue

        metrics = sensor_backend.read_metrics()
        if cellular_monitor is not None:
            cellular_metrics = cellular_monitor.read_metrics()
            if cellular_metrics:
                metrics.update(cellular_metrics)

        power_eval = power_manager.evaluate(metrics=metrics, policy=policy.power_management)
        metrics.update(power_eval.telemetry_flags())

        current_state, current_alerts = _compute_state(metrics, state.last_alerts, policy)
        alert_transition = current_alerts != state.last_alerts
        critical_active = "WATER_PRESSURE_LOW" in current_alerts
        heartbeat_only_mode = cost_cap_state.telemetry_heartbeat_only(policy.cost_caps)
        cost_cap_active = cost_cap_state.cost_cap_active(policy.cost_caps)
        power_saver_active = power_eval.power_saver_active

        if power_saver_active != state.last_power_saver_active:
            print(
                "[edgewatch-agent] power-saver %s source=%s out_of_range=%s unsustainable=%s"
                % (
                    "active" if power_saver_active else "cleared",
                    power_eval.power_source,
                    power_eval.power_input_out_of_range,
                    power_eval.power_unsustainable,
                )
            )
            state.last_power_saver_active = power_saver_active

        if cost_cap_active != state.last_cost_cap_active:
            counters = cost_cap_state.counters()
            print(
                "[edgewatch-agent] cost-cap %s bytes=%s/%s snapshots=%s/%s uploads=%s/%s"
                % (
                    "active" if cost_cap_active else "cleared",
                    counters.bytes_sent_today,
                    policy.cost_caps.max_bytes_per_day,
                    counters.snapshots_today,
                    policy.cost_caps.max_snapshots_per_day,
                    counters.media_uploads_today,
                    policy.cost_caps.max_media_uploads_per_day,
                )
            )
            state.last_cost_cap_active = cost_cap_active

        # Determine sampling interval for the next loop.
        sample_s, heartbeat_interval_s = _resolve_runtime_cadence(
            policy=policy,
            critical_active=critical_active,
            power_saver_active=power_saver_active,
            operation_mode=operation_mode,
            sleep_poll_interval_s=sleep_poll_interval_s,
        )

        send_reason: Optional[str] = None
        payload_metrics: Dict[str, Any] = {}

        if operation_mode == "sleep":
            if state.last_state == "UNKNOWN" and not state.last_metrics_snapshot:
                send_reason = "startup"
                payload_metrics = _minimal_heartbeat_metrics(metrics)
            elif alert_transition:
                send_reason = "state_change" if current_state != state.last_state else "alert_change"
                payload_metrics = _minimal_heartbeat_metrics(metrics)
            elif now - state.last_heartbeat_at >= heartbeat_interval_s:
                send_reason = "heartbeat"
                payload_metrics = _minimal_heartbeat_metrics(metrics)
        elif heartbeat_only_mode:
            if now - state.last_heartbeat_at >= heartbeat_interval_s:
                send_reason = "heartbeat"
                payload_metrics = _minimal_heartbeat_metrics(metrics)
        else:
            if power_saver_active:
                if state.last_state == "UNKNOWN" and not state.last_metrics_snapshot:
                    send_reason = "startup"
                    payload_metrics = dict(metrics)
                elif alert_transition:
                    send_reason = "state_change" if current_state != state.last_state else "alert_change"
                    payload_metrics = dict(metrics)
                elif now - state.last_heartbeat_at >= heartbeat_interval_s:
                    send_reason = "heartbeat"
                    payload_metrics = _minimal_heartbeat_metrics(metrics)

            # Bootstrap: send a full snapshot once on startup to establish baseline.
            elif state.last_state == "UNKNOWN" and not state.last_metrics_snapshot:
                send_reason = "startup"
                payload_metrics = dict(metrics)

            # Immediate send on alert transitions (including transitions between different alert sets).
            elif alert_transition:
                send_reason = "state_change" if current_state != state.last_state else "alert_change"
                payload_metrics = dict(metrics)

            else:
                # Periodic snapshot while in critical alert state
                if critical_active and (
                    now - state.last_alert_snapshot_at >= policy.reporting.alert_report_interval_s
                ):
                    send_reason = "alert_snapshot"
                    payload_metrics = dict(metrics)

                # Heartbeat (only after a period of silence; last_heartbeat_at updates on any record)
                elif now - state.last_heartbeat_at >= heartbeat_interval_s:
                    send_reason = "heartbeat"
                    payload_metrics = _minimal_heartbeat_metrics(metrics)

                # Delta-based send
                else:
                    changed = _changed_keys(
                        current=metrics,
                        previous=state.last_metrics_snapshot,
                        thresholds=policy.delta_thresholds,
                    )
                    if changed:
                        send_reason = "delta"
                        payload_metrics = {k: metrics[k] for k in changed}

        if send_reason:
            # Update local baseline for delta decisions.
            baseline_update = (
                dict(payload_metrics) if send_reason in {"delta", "heartbeat"} else dict(metrics)
            )

            payload_metrics.update(buf.metrics())
            payload_metrics["device_state"] = current_state
            payload_metrics.update(cost_cap_state.audit_metrics(policy.cost_caps))

            point = make_point(payload_metrics)

            # Mark schedules immediately (whether we send now or buffer).
            _mark_point_recorded(state, now=now, reason=send_reason, alerts=current_alerts)

            # Update local baseline immediately; even if offline we buffer the point.
            state.last_metrics_snapshot.update(baseline_update)

            # If we're in backoff, don't burn energy attempting network.
            if now < state.next_network_attempt_at:
                buf.enqueue(point["message_id"], point, point["ts"])
                _maybe_prune(buf, policy)
                print(f"[edgewatch-agent] backoff active -> buffered ({send_reason}) queue={buf.count()}")
            else:
                try:

                    def _record_sent(points: List[Dict[str, Any]]) -> None:
                        cost_cap_state.record_bytes_sent(_estimate_ingest_payload_bytes(points))

                    # Flush buffered non-heartbeat points only when not in heartbeat/power saver/sleep modes.
                    if not heartbeat_only_mode and not power_saver_active and operation_mode != "sleep":
                        ok = _flush_buffer(
                            session=session,
                            buf=buf,
                            api_url=api_url,
                            token=token,
                            max_points_per_batch=policy.reporting.max_points_per_batch,
                            on_batch_sent=_record_sent,
                        )
                        if not ok:
                            raise RuntimeError("buffer flush failed")

                    resp = post_points(session, api_url, token, [point])
                    if 200 <= resp.status_code < 300:
                        _record_sent([point])
                        state.consecutive_failures = 0
                        state.next_network_attempt_at = 0.0
                        print(
                            f"[edgewatch-agent] sent ({send_reason}) state={current_state} alerts={sorted(current_alerts)} queue={buf.count()}"
                        )
                    else:
                        if resp.status_code == 429:
                            ra = _parse_retry_after_seconds(resp.headers)
                            raise RateLimited(f"send failed: 429 {resp.text[:200]}", retry_after_s=ra)
                        raise RuntimeError(f"send failed: {resp.status_code} {resp.text[:200]}")

                except Exception as e:
                    buf.enqueue(point["message_id"], point, point["ts"])
                    _maybe_prune(buf, policy)

                    retry_after_s = e.retry_after_s if isinstance(e, RateLimited) else None

                    state.consecutive_failures += 1
                    base_backoff = min(
                        policy.reporting.backoff_max_s,
                        policy.reporting.backoff_initial_s * (2 ** min(state.consecutive_failures, 8)),
                    )

                    # If the server told us when to retry, respect it.
                    if retry_after_s is not None:
                        base_backoff = max(base_backoff, float(retry_after_s))

                    # Jitter to avoid thundering herd if many devices reconnect simultaneously.
                    jittered = float(base_backoff) * random.uniform(0.8, 1.2)
                    backoff = min(policy.reporting.backoff_max_s, jittered)
                    if retry_after_s is not None:
                        backoff = max(backoff, float(retry_after_s))

                    state.next_network_attempt_at = time.time() + float(backoff)

                    print(
                        f"[edgewatch-agent] send exception: {e!r} -> buffered queue={buf.count()} backoff={backoff:.1f}s"
                    )

            state.last_state = current_state
            state.last_alerts = set(current_alerts)
        elif alert_transition:
            # Keep alert transition handling edge-triggered even when telemetry send is deferred.
            state.last_state = current_state
            state.last_alerts = set(current_alerts)

        if media_runtime is not None:
            media_disabled_by_operation = _media_disabled_by_operation(operation_mode=operation_mode)
            if media_disabled_by_operation:
                if now - state.last_power_saver_log_at >= 60.0:
                    print("[edgewatch-agent] media disabled while operation mode is sleep/disabled")
                    state.last_power_saver_log_at = now
                _sleep(sample_s)
                continue

            media_disabled_by_power = _media_disabled_by_power(
                policy=policy,
                power_saver_active=power_saver_active,
            )
            if media_disabled_by_power:
                if now - state.last_power_saver_log_at >= 60.0:
                    print("[edgewatch-agent] media disabled while power saver is active")
                    state.last_power_saver_log_at = now
                _sleep(sample_s)
                continue

            try:
                captured_asset = None
                if cost_cap_state.allow_snapshot_capture(policy.cost_caps):
                    if alert_transition:
                        captured_asset = media_runtime.maybe_capture_alert_transition(now_s=time.time())
                    if captured_asset is None:
                        captured_asset = media_runtime.maybe_capture_scheduled(now_s=time.time())
                    if captured_asset is not None:
                        cost_cap_state.record_snapshot_capture()
                        counters = cost_cap_state.counters()
                        print(
                            "[edgewatch-agent] media captured camera=%s reason=%s bytes=%s path=%s "
                            "snapshots=%s/%s uploads=%s/%s"
                            % (
                                captured_asset.metadata.camera_id,
                                captured_asset.metadata.reason,
                                captured_asset.metadata.bytes,
                                captured_asset.asset_path,
                                counters.snapshots_today,
                                policy.cost_caps.max_snapshots_per_day,
                                counters.media_uploads_today,
                                policy.cost_caps.max_media_uploads_per_day,
                            )
                        )
                else:
                    if now - state.last_snapshot_cap_log_at >= 60.0:
                        counters = cost_cap_state.counters()
                        print(
                            "[edgewatch-agent] media capture skipped due to cost caps "
                            "(snapshots=%s/%s uploads=%s/%s)"
                            % (
                                counters.snapshots_today,
                                policy.cost_caps.max_snapshots_per_day,
                                counters.media_uploads_today,
                                policy.cost_caps.max_media_uploads_per_day,
                            )
                        )
                        state.last_snapshot_cap_log_at = now
            except Exception as exc:
                print(f"[edgewatch-agent] media capture failed: {exc!r}")

            if now >= state.next_network_attempt_at:
                try:
                    uploaded_asset = media_runtime.maybe_upload_pending(
                        session=session,
                        api_url=api_url,
                        token=token,
                        now_s=time.time(),
                    )
                    if uploaded_asset is not None:
                        print(
                            "[edgewatch-agent] media uploaded camera=%s reason=%s bytes=%s asset=%s"
                            % (
                                uploaded_asset.metadata.camera_id,
                                uploaded_asset.metadata.reason,
                                uploaded_asset.metadata.bytes,
                                uploaded_asset.asset_path.name,
                            )
                        )
                except MediaUploadError as exc:
                    print(f"[edgewatch-agent] media upload deferred: {exc}")
                except Exception as exc:
                    print(f"[edgewatch-agent] media upload failed: {exc!r}")

        _sleep(sample_s)


if __name__ == "__main__":
    main()
