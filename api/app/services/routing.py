from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AlertPolicy, Device, NotificationEvent


@dataclass(frozen=True)
class AlertCandidate:
    alert_id: str
    device_id: str
    alert_type: str
    severity: str
    message: str


@dataclass(frozen=True)
class RoutingPolicy:
    dedupe_window_s: int
    throttle_window_s: int
    throttle_max_notifications: int
    quiet_hours_start_minute: int | None
    quiet_hours_end_minute: int | None
    quiet_hours_tz: str
    enabled: bool
    alerts_muted_until: datetime | None
    alerts_muted_reason: str | None
    policy_id: str | None = None


@dataclass(frozen=True)
class RoutingDecision:
    should_notify: bool
    decision: str
    reason: str
    channel: str
    policy_id: str | None


def _parse_hhmm(value: str | None) -> int | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    parts = raw.split(":")
    if len(parts) != 2:
        return None
    try:
        hh = int(parts[0])
        mm = int(parts[1])
    except ValueError:
        return None
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        return None
    return hh * 60 + mm


def in_quiet_hours(
    *,
    now: datetime,
    start_minute: int | None,
    end_minute: int | None,
    tz_name: str,
) -> bool:
    if start_minute is None or end_minute is None:
        return False
    if start_minute == end_minute:
        return False

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    local_now = now.astimezone(tz)
    minute_of_day = local_now.hour * 60 + local_now.minute

    if start_minute < end_minute:
        return start_minute <= minute_of_day < end_minute

    # Cross-midnight window, e.g. 22:00 -> 06:00.
    return minute_of_day >= start_minute or minute_of_day < end_minute


def _default_policy() -> RoutingPolicy:
    return RoutingPolicy(
        dedupe_window_s=max(0, settings.alert_dedupe_window_s),
        throttle_window_s=max(0, settings.alert_throttle_window_s),
        throttle_max_notifications=max(0, settings.alert_throttle_max_notifications),
        quiet_hours_start_minute=_parse_hhmm(settings.alert_quiet_hours_start),
        quiet_hours_end_minute=_parse_hhmm(settings.alert_quiet_hours_end),
        quiet_hours_tz=settings.alert_quiet_hours_tz,
        enabled=True,
        alerts_muted_until=None,
        alerts_muted_reason=None,
        policy_id=None,
    )


class AlertRouter:
    def _load_policy(self, session: Session, device_id: str) -> RoutingPolicy:
        device_row = (
            session.query(Device.alerts_muted_until, Device.alerts_muted_reason)
            .filter(Device.device_id == device_id)
            .one_or_none()
        )
        muted_until = None
        muted_reason = None
        if device_row is not None:
            muted_until = device_row[0]
            muted_reason = str(device_row[1]).strip() if device_row[1] else None
            if muted_until is not None and muted_until.tzinfo is None:
                muted_until = muted_until.replace(tzinfo=timezone.utc)

        row = session.query(AlertPolicy).filter(AlertPolicy.device_id == device_id).one_or_none()
        if row is None:
            row = (
                session.query(AlertPolicy)
                .filter(AlertPolicy.device_id.is_(None))
                .order_by(AlertPolicy.created_at.desc())
                .first()
            )
        if row is None:
            default = _default_policy()
            return RoutingPolicy(
                dedupe_window_s=default.dedupe_window_s,
                throttle_window_s=default.throttle_window_s,
                throttle_max_notifications=default.throttle_max_notifications,
                quiet_hours_start_minute=default.quiet_hours_start_minute,
                quiet_hours_end_minute=default.quiet_hours_end_minute,
                quiet_hours_tz=default.quiet_hours_tz,
                enabled=default.enabled,
                alerts_muted_until=muted_until,
                alerts_muted_reason=muted_reason,
                policy_id=default.policy_id,
            )

        return RoutingPolicy(
            dedupe_window_s=max(0, row.dedupe_window_s),
            throttle_window_s=max(0, row.throttle_window_s),
            throttle_max_notifications=max(0, row.throttle_max_notifications),
            quiet_hours_start_minute=row.quiet_hours_start_minute,
            quiet_hours_end_minute=row.quiet_hours_end_minute,
            quiet_hours_tz=row.quiet_hours_tz,
            enabled=bool(row.enabled),
            alerts_muted_until=muted_until,
            alerts_muted_reason=muted_reason,
            policy_id=row.id,
        )

    def should_notify(
        self,
        session: Session,
        candidate: AlertCandidate,
        *,
        now: datetime | None = None,
        channel: str = "webhook",
    ) -> RoutingDecision:
        now_utc = now or datetime.now(timezone.utc)
        policy = self._load_policy(session, candidate.device_id)

        if not policy.enabled:
            return RoutingDecision(
                should_notify=False,
                decision="suppressed_disabled",
                reason="alert policy disabled",
                channel=channel,
                policy_id=policy.policy_id,
            )

        if policy.alerts_muted_until is not None and now_utc < policy.alerts_muted_until:
            reason = "alerts muted"
            if policy.alerts_muted_reason:
                reason = f"{reason}: {policy.alerts_muted_reason}"
            return RoutingDecision(
                should_notify=False,
                decision="suppressed_muted",
                reason=reason,
                channel=channel,
                policy_id=policy.policy_id,
            )

        if in_quiet_hours(
            now=now_utc,
            start_minute=policy.quiet_hours_start_minute,
            end_minute=policy.quiet_hours_end_minute,
            tz_name=policy.quiet_hours_tz,
        ):
            return RoutingDecision(
                should_notify=False,
                decision="suppressed_quiet_hours",
                reason="quiet hours active",
                channel=channel,
                policy_id=policy.policy_id,
            )

        if policy.dedupe_window_s > 0:
            dedupe_cutoff = now_utc - timedelta(seconds=policy.dedupe_window_s)
            exists = (
                session.query(NotificationEvent.id)
                .filter(
                    NotificationEvent.device_id == candidate.device_id,
                    NotificationEvent.alert_type == candidate.alert_type,
                    NotificationEvent.delivered.is_(True),
                    NotificationEvent.created_at >= dedupe_cutoff,
                )
                .order_by(NotificationEvent.created_at.desc())
                .first()
            )
            if exists is not None:
                return RoutingDecision(
                    should_notify=False,
                    decision="suppressed_dedupe",
                    reason="dedupe window",
                    channel=channel,
                    policy_id=policy.policy_id,
                )

        if policy.throttle_window_s > 0 and policy.throttle_max_notifications > 0:
            throttle_cutoff = now_utc - timedelta(seconds=policy.throttle_window_s)
            sent_count = (
                session.query(func.count(NotificationEvent.id))
                .filter(
                    NotificationEvent.device_id == candidate.device_id,
                    NotificationEvent.delivered.is_(True),
                    NotificationEvent.created_at >= throttle_cutoff,
                )
                .scalar()
            )
            if int(sent_count or 0) >= policy.throttle_max_notifications:
                return RoutingDecision(
                    should_notify=False,
                    decision="suppressed_throttle",
                    reason="throttle limit reached",
                    channel=channel,
                    policy_id=policy.policy_id,
                )

        return RoutingDecision(
            should_notify=True,
            decision="deliver",
            reason="policy allows delivery",
            channel=channel,
            policy_id=policy.policy_id,
        )
