from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..config import settings
from ..edge_policy import load_edge_policy
from ..models import Device, Alert
from .notifications import process_alert_notification


logger = logging.getLogger("edgewatch.monitor")


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
            _resolve_offline_alert_if_any(session, d, now)


def compute_status(device: Device, now: datetime | None = None) -> tuple[str, int | None]:
    if now is None:
        now = utcnow()
    if device.last_seen_at is None:
        return "unknown", None
    delta = now - device.last_seen_at
    seconds = int(delta.total_seconds())
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


def _resolve_offline_alert_if_any(session: Session, device: Device, now: datetime) -> None:
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
        a.resolved_at = now

    # Optional: create an explicit online event when it returns
    if open_alerts:
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
            open_alert.resolved_at = now
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
            open_alert.resolved_at = now
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
            open_alert.resolved_at = now
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
            open_alert.resolved_at = now
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
            open_alert.resolved_at = now
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
            open_alert.resolved_at = now
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
            open_alert.resolved_at = now
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


def _create_alert(session: Session, alert: Alert, *, now: datetime) -> None:
    session.add(alert)
    session.flush()
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
