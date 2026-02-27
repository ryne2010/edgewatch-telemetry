from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.orm import Session

from ..config import settings
from ..edge_policy import load_edge_policy
from ..models import Device, Alert, TelemetryPoint
from ..observability import record_alert_transition_metric
from .notifications import process_alert_notification


logger = logging.getLogger("edgewatch.monitor")

DeviceStatus = Literal["online", "offline", "unknown", "sleep", "disabled"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_offline_alerts(session: Session) -> None:
    """Create/resolve DEVICE_OFFLINE alerts based on last_seen_at."""
    now = utcnow()
    devices = session.query(Device).filter(Device.enabled.is_(True)).all()
    for d in devices:
        status, _ = compute_status(d, now)
        if status == "offline":
            _open_or_create_offline_alert(session, d, now)
        else:
            _resolve_offline_alert_if_any(session, d, now, emit_online_event=(status == "online"))


def compute_status(device: Device, now: datetime | None = None) -> tuple[DeviceStatus, int | None]:
    if now is None:
        now = utcnow()
    operation_mode = str(getattr(device, "operation_mode", "active") or "active").strip().lower()
    if operation_mode not in {"active", "sleep", "disabled"}:
        operation_mode = "active"

    if device.last_seen_at is None:
        if not device.enabled or operation_mode == "disabled":
            return "disabled", None
        if operation_mode == "sleep":
            return "sleep", None
        return "unknown", None

    delta = now - device.last_seen_at
    seconds = int(delta.total_seconds())
    if not device.enabled or operation_mode == "disabled":
        return "disabled", seconds
    if operation_mode == "sleep":
        return "sleep", seconds
    if seconds > device.offline_after_s:
        return "offline", seconds
    return "online", seconds


def _open_or_create_offline_alert(session: Session, device: Device, now: datetime) -> None:
    open_alert = (
        session.query(Alert)
        .filter(
            Alert.device_id == device.device_id,
            Alert.alert_type == "DEVICE_OFFLINE",
            Alert.resolved_at.is_(None),
        )
        .order_by(Alert.created_at.desc())
        .first()
    )
    if open_alert:
        return

    msg = f"Device '{device.device_id}' is offline (last seen: {device.last_seen_at})."
    _create_alert(
        session,
        Alert(
            device_id=device.device_id,
            alert_type="DEVICE_OFFLINE",
            severity="warning",
            message=msg,
            created_at=now,
        ),
        now=now,
    )


def _resolve_offline_alert_if_any(
    session: Session, device: Device, now: datetime, *, emit_online_event: bool = True
) -> None:
    open_alerts = (
        session.query(Alert)
        .filter(
            Alert.device_id == device.device_id,
            Alert.alert_type == "DEVICE_OFFLINE",
            Alert.resolved_at.is_(None),
        )
        .all()
    )
    for a in open_alerts:
        _resolve_alert(a, now=now)

    # Optional: create an explicit online event when it returns
    if open_alerts and emit_online_event:
        _create_alert(
            session,
            Alert(
                device_id=device.device_id,
                alert_type="DEVICE_ONLINE",
                severity="info",
                message=f"Device '{device.device_id}' is back online.",
                created_at=now,
            ),
            now=now,
        )


def ensure_water_pressure_alerts(
    session: Session, device_id: str, water_pressure_psi: float, now: datetime
) -> None:
    """Example threshold alert with stateful open/resolve behavior.

    We intentionally implement a small amount of hysteresis to prevent "flapping":
    - Open when pressure < low
    - Resolve only when pressure >= recover

    Thresholds are sourced from the edge policy contract (contracts/edge_policy/*)
    with an optional env override for quick experimentation.
    """

    policy = load_edge_policy(settings.edge_policy_version)
    low = (
        settings.default_water_pressure_low_psi
        if settings.default_water_pressure_low_psi is not None
        else policy.alert_thresholds.water_pressure_low_psi
    )
    recover = policy.alert_thresholds.water_pressure_recover_psi

    open_alert = (
        session.query(Alert)
        .filter(
            Alert.device_id == device_id,
            Alert.alert_type == "WATER_PRESSURE_LOW",
            Alert.resolved_at.is_(None),
        )
        .order_by(Alert.created_at.desc())
        .first()
    )

    if water_pressure_psi < low:
        if not open_alert:
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="WATER_PRESSURE_LOW",
                    severity="warning",
                    message=f"Water pressure low: {water_pressure_psi:.1f} psi (threshold: {low:.1f} psi).",
                    created_at=now,
                ),
                now=now,
            )
    else:
        if open_alert and water_pressure_psi >= recover:
            _resolve_alert(open_alert, now=now)
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="WATER_PRESSURE_OK",
                    severity="info",
                    message=f"Water pressure recovered: {water_pressure_psi:.1f} psi.",
                    created_at=now,
                ),
                now=now,
            )


def ensure_oil_pressure_alerts(
    session: Session, device_id: str, oil_pressure_psi: float, now: datetime
) -> None:
    """Oil pressure threshold alert with hysteresis."""

    policy = load_edge_policy(settings.edge_policy_version)
    low = policy.alert_thresholds.oil_pressure_low_psi
    recover = policy.alert_thresholds.oil_pressure_recover_psi

    open_alert = (
        session.query(Alert)
        .filter(
            Alert.device_id == device_id,
            Alert.alert_type == "OIL_PRESSURE_LOW",
            Alert.resolved_at.is_(None),
        )
        .order_by(Alert.created_at.desc())
        .first()
    )

    if oil_pressure_psi < low:
        if not open_alert:
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="OIL_PRESSURE_LOW",
                    severity="warning",
                    message=f"Oil pressure low: {oil_pressure_psi:.1f} psi (threshold: {low:.1f} psi).",
                    created_at=now,
                ),
                now=now,
            )
    else:
        if open_alert and oil_pressure_psi >= recover:
            _resolve_alert(open_alert, now=now)
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="OIL_PRESSURE_OK",
                    severity="info",
                    message=f"Oil pressure recovered: {oil_pressure_psi:.1f} psi.",
                    created_at=now,
                ),
                now=now,
            )


def ensure_oil_level_alerts(session: Session, device_id: str, oil_level_pct: float, now: datetime) -> None:
    """Oil level threshold alert with hysteresis."""

    policy = load_edge_policy(settings.edge_policy_version)
    low = policy.alert_thresholds.oil_level_low_pct
    recover = policy.alert_thresholds.oil_level_recover_pct

    open_alert = (
        session.query(Alert)
        .filter(
            Alert.device_id == device_id,
            Alert.alert_type == "OIL_LEVEL_LOW",
            Alert.resolved_at.is_(None),
        )
        .order_by(Alert.created_at.desc())
        .first()
    )

    if oil_level_pct < low:
        if not open_alert:
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="OIL_LEVEL_LOW",
                    severity="warning",
                    message=f"Oil level low: {oil_level_pct:.1f}% (threshold: {low:.1f}%).",
                    created_at=now,
                ),
                now=now,
            )
    else:
        if open_alert and oil_level_pct >= recover:
            _resolve_alert(open_alert, now=now)
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="OIL_LEVEL_OK",
                    severity="info",
                    message=f"Oil level recovered: {oil_level_pct:.1f}%.",
                    created_at=now,
                ),
                now=now,
            )


def ensure_drip_oil_level_alerts(
    session: Session, device_id: str, drip_oil_level_pct: float, now: datetime
) -> None:
    """Drip oiler reservoir level threshold alert with hysteresis."""

    policy = load_edge_policy(settings.edge_policy_version)
    low = policy.alert_thresholds.drip_oil_level_low_pct
    recover = policy.alert_thresholds.drip_oil_level_recover_pct

    open_alert = (
        session.query(Alert)
        .filter(
            Alert.device_id == device_id,
            Alert.alert_type == "DRIP_OIL_LEVEL_LOW",
            Alert.resolved_at.is_(None),
        )
        .order_by(Alert.created_at.desc())
        .first()
    )

    if drip_oil_level_pct < low:
        if not open_alert:
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="DRIP_OIL_LEVEL_LOW",
                    severity="warning",
                    message=f"Drip oil level low: {drip_oil_level_pct:.1f}% (threshold: {low:.1f}%).",
                    created_at=now,
                ),
                now=now,
            )
    else:
        if open_alert and drip_oil_level_pct >= recover:
            _resolve_alert(open_alert, now=now)
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="DRIP_OIL_LEVEL_OK",
                    severity="info",
                    message=f"Drip oil level recovered: {drip_oil_level_pct:.1f}%.",
                    created_at=now,
                ),
                now=now,
            )


def ensure_oil_life_alerts(session: Session, device_id: str, oil_life_pct: float, now: datetime) -> None:
    """Oil life remaining alert with hysteresis.

    Oil life is a runtime-derived metric and typically reset manually after service.
    """

    policy = load_edge_policy(settings.edge_policy_version)
    low = policy.alert_thresholds.oil_life_low_pct
    recover = policy.alert_thresholds.oil_life_recover_pct

    open_alert = (
        session.query(Alert)
        .filter(
            Alert.device_id == device_id,
            Alert.alert_type == "OIL_LIFE_LOW",
            Alert.resolved_at.is_(None),
        )
        .order_by(Alert.created_at.desc())
        .first()
    )

    if oil_life_pct < low:
        if not open_alert:
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="OIL_LIFE_LOW",
                    severity="warning",
                    message=f"Oil life low: {oil_life_pct:.1f}% remaining (threshold: {low:.1f}%).",
                    created_at=now,
                ),
                now=now,
            )
    else:
        if open_alert and oil_life_pct >= recover:
            _resolve_alert(open_alert, now=now)
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="OIL_LIFE_OK",
                    severity="info",
                    message=f"Oil life recovered: {oil_life_pct:.1f}%.",
                    created_at=now,
                ),
                now=now,
            )


def ensure_battery_alerts(session: Session, device_id: str, battery_v: float, now: datetime) -> None:
    """Battery threshold alert with hysteresis.

    - Open when battery_v < low
    - Resolve only when battery_v >= recover

    Thresholds are sourced from the edge policy contract.
    """

    policy = load_edge_policy(settings.edge_policy_version)
    low = (
        settings.default_battery_low_v
        if settings.default_battery_low_v is not None
        else policy.alert_thresholds.battery_low_v
    )
    recover = policy.alert_thresholds.battery_recover_v

    open_alert = (
        session.query(Alert)
        .filter(
            Alert.device_id == device_id,
            Alert.alert_type == "BATTERY_LOW",
            Alert.resolved_at.is_(None),
        )
        .order_by(Alert.created_at.desc())
        .first()
    )

    if battery_v < low:
        if not open_alert:
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="BATTERY_LOW",
                    severity="warning",
                    message=f"Battery low: {battery_v:.2f} V (threshold: {low:.2f} V).",
                    created_at=now,
                ),
                now=now,
            )
    else:
        if open_alert and battery_v >= recover:
            _resolve_alert(open_alert, now=now)
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="BATTERY_OK",
                    severity="info",
                    message=f"Battery recovered: {battery_v:.2f} V.",
                    created_at=now,
                ),
                now=now,
            )


def ensure_signal_alerts(session: Session, device_id: str, signal_rssi_dbm: float, now: datetime) -> None:
    """Cellular/WiFi RSSI alert with hysteresis.

    Note: RSSI is negative (dBm). "Lower" means weaker signal.
    - Open when signal_rssi_dbm < low
    - Resolve only when signal_rssi_dbm >= recover
    """

    policy = load_edge_policy(settings.edge_policy_version)
    low = (
        settings.default_signal_low_rssi_dbm
        if settings.default_signal_low_rssi_dbm is not None
        else policy.alert_thresholds.signal_low_rssi_dbm
    )
    recover = policy.alert_thresholds.signal_recover_rssi_dbm

    open_alert = (
        session.query(Alert)
        .filter(
            Alert.device_id == device_id,
            Alert.alert_type == "SIGNAL_LOW",
            Alert.resolved_at.is_(None),
        )
        .order_by(Alert.created_at.desc())
        .first()
    )

    if signal_rssi_dbm < low:
        if not open_alert:
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="SIGNAL_LOW",
                    severity="warning",
                    message=f"Signal weak: {signal_rssi_dbm:.0f} dBm (threshold: {low:.0f} dBm).",
                    created_at=now,
                ),
                now=now,
            )
    else:
        if open_alert and signal_rssi_dbm >= recover:
            _resolve_alert(open_alert, now=now)
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="SIGNAL_OK",
                    severity="info",
                    message=f"Signal recovered: {signal_rssi_dbm:.0f} dBm.",
                    created_at=now,
                ),
                now=now,
            )


def ensure_microphone_offline_alerts(
    session: Session, device_id: str, microphone_level_db: float, now: datetime
) -> None:
    """Microphone-based offline signal.

    Open when microphone level falls below threshold. Resolve when it returns
    to or above threshold.
    """

    policy = load_edge_policy(settings.edge_policy_version)
    offline_db = policy.alert_thresholds.microphone_offline_db
    open_samples = max(1, int(policy.alert_thresholds.microphone_offline_open_consecutive_samples))
    resolve_samples = max(1, int(policy.alert_thresholds.microphone_offline_resolve_consecutive_samples))

    open_alert = (
        session.query(Alert)
        .filter(
            Alert.device_id == device_id,
            Alert.alert_type == "MICROPHONE_OFFLINE",
            Alert.resolved_at.is_(None),
        )
        .order_by(Alert.created_at.desc())
        .first()
    )

    levels = _recent_microphone_levels(
        session,
        device_id=device_id,
        limit=max(open_samples, resolve_samples),
    )

    if open_alert:
        if len(levels) >= resolve_samples and all(level >= offline_db for level in levels[:resolve_samples]):
            _resolve_alert(open_alert, now=now)
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="MICROPHONE_ONLINE",
                    severity="info",
                    message=f"Microphone level recovered: {microphone_level_db:.1f} dB.",
                    created_at=now,
                ),
                now=now,
            )
    else:
        if len(levels) >= open_samples and all(level < offline_db for level in levels[:open_samples]):
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="MICROPHONE_OFFLINE",
                    severity="warning",
                    message=(
                        f"Microphone level low: {microphone_level_db:.1f} dB "
                        f"(offline threshold: {offline_db:.1f} dB)."
                    ),
                    created_at=now,
                ),
                now=now,
            )


def _recent_microphone_levels(session: Session, *, device_id: str, limit: int) -> list[float]:
    if limit <= 0:
        return []
    rows = (
        session.query(TelemetryPoint.metrics)
        .filter(TelemetryPoint.device_id == device_id)
        .order_by(TelemetryPoint.ts.desc(), TelemetryPoint.created_at.desc())
        .limit(max(10, limit * 5))
        .all()
    )

    out: list[float] = []
    for (metrics,) in rows:
        if not isinstance(metrics, dict):
            continue
        value = metrics.get("microphone_level_db")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        out.append(float(value))
        if len(out) >= limit:
            break
    return out


def ensure_power_input_out_of_range_alerts(
    session: Session,
    device_id: str,
    input_out_of_range: bool,
    now: datetime,
) -> None:
    """Power input range lifecycle.

    - Open POWER_INPUT_OUT_OF_RANGE when the boolean flag is true.
    - Resolve and emit POWER_INPUT_OK when the flag returns false.
    """

    open_alert = (
        session.query(Alert)
        .filter(
            Alert.device_id == device_id,
            Alert.alert_type == "POWER_INPUT_OUT_OF_RANGE",
            Alert.resolved_at.is_(None),
        )
        .order_by(Alert.created_at.desc())
        .first()
    )

    if input_out_of_range:
        if not open_alert:
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="POWER_INPUT_OUT_OF_RANGE",
                    severity="warning",
                    message="Power input voltage is out of configured range.",
                    created_at=now,
                ),
                now=now,
            )
    else:
        if open_alert:
            _resolve_alert(open_alert, now=now)
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="POWER_INPUT_OK",
                    severity="info",
                    message="Power input voltage returned to configured range.",
                    created_at=now,
                ),
                now=now,
            )


def ensure_power_unsustainable_alerts(
    session: Session,
    device_id: str,
    power_unsustainable: bool,
    now: datetime,
) -> None:
    """Power sustainability lifecycle.

    - Open POWER_UNSUSTAINABLE when the boolean flag is true.
    - Resolve and emit POWER_SUSTAINABLE when the flag returns false.
    """

    open_alert = (
        session.query(Alert)
        .filter(
            Alert.device_id == device_id,
            Alert.alert_type == "POWER_UNSUSTAINABLE",
            Alert.resolved_at.is_(None),
        )
        .order_by(Alert.created_at.desc())
        .first()
    )

    if power_unsustainable:
        if not open_alert:
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="POWER_UNSUSTAINABLE",
                    severity="warning",
                    message="Power consumption is unsustainable for configured window.",
                    created_at=now,
                ),
                now=now,
            )
    else:
        if open_alert:
            _resolve_alert(open_alert, now=now)
            _create_alert(
                session,
                Alert(
                    device_id=device_id,
                    alert_type="POWER_SUSTAINABLE",
                    severity="info",
                    message="Power consumption returned to sustainable range.",
                    created_at=now,
                ),
                now=now,
            )


def _is_resolution_event(alert_type: str) -> bool:
    return alert_type in {"DEVICE_ONLINE", "MICROPHONE_ONLINE", "POWER_SUSTAINABLE"} or alert_type.endswith(
        "_OK"
    )


def _resolve_alert(alert: Alert, *, now: datetime) -> None:
    if alert.resolved_at is not None:
        return
    alert.resolved_at = now
    record_alert_transition_metric(
        state="close",
        alert_type=alert.alert_type,
        severity=alert.severity,
    )


def _create_alert(session: Session, alert: Alert, *, now: datetime) -> None:
    session.add(alert)
    session.flush()
    if not _is_resolution_event(alert.alert_type):
        record_alert_transition_metric(
            state="open",
            alert_type=alert.alert_type,
            severity=alert.severity,
        )
    try:
        process_alert_notification(session, alert, now=now)
    except Exception:
        logger.exception(
            "notification_processing_failed",
            extra={
                "fields": {
                    "alert_id": alert.id,
                    "device_id": alert.device_id,
                    "alert_type": alert.alert_type,
                }
            },
        )
