from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..config import settings
from ..edge_policy import load_edge_policy
from ..models import Device, Alert


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
    session.add(
        Alert(
            device_id=device.device_id,
            alert_type="DEVICE_OFFLINE",
            severity="warning",
            message=msg,
            created_at=now,
        )
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
        session.add(
            Alert(
                device_id=device.device_id,
                alert_type="DEVICE_ONLINE",
                severity="info",
                message=f"Device '{device.device_id}' is back online.",
                created_at=now,
            )
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
            session.add(
                Alert(
                    device_id=device_id,
                    alert_type="WATER_PRESSURE_LOW",
                    severity="warning",
                    message=f"Water pressure low: {water_pressure_psi:.1f} psi (threshold: {low:.1f} psi).",
                    created_at=now,
                )
            )
    else:
        if open_alert and water_pressure_psi >= recover:
            open_alert.resolved_at = now
            session.add(
                Alert(
                    device_id=device_id,
                    alert_type="WATER_PRESSURE_OK",
                    severity="info",
                    message=f"Water pressure recovered: {water_pressure_psi:.1f} psi.",
                    created_at=now,
                )
            )
