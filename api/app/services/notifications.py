from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Alert, NotificationDestination, NotificationEvent
from .routing import AlertCandidate, AlertRouter


logger = logging.getLogger("edgewatch.notifications")


@dataclass(frozen=True)
class DeliveryResult:
    delivered: bool
    decision: str
    reason: str
    error_class: str | None = None


@dataclass(frozen=True)
class NotificationDestinationConfig:
    name: str
    channel: str
    kind: str
    webhook_url: str
    source_types: tuple[str, ...]
    event_types: tuple[str, ...]
    destination_fingerprint: str


@dataclass(frozen=True)
class PlatformEvent:
    source_kind: str
    source_id: str | None
    device_id: str
    event_type: str
    severity: str
    message: str
    payload: dict[str, Any]
    created_at: datetime


class WebhookNotificationAdapter:
    def __init__(self, *, webhook_url: str, kind: str, timeout_s: float) -> None:
        self.webhook_url = webhook_url
        self.kind = kind
        self.timeout_s = timeout_s

    def deliver(self, alert: Alert) -> DeliveryResult:
        message = f"[{alert.severity.upper()}] {alert.alert_type} for {alert.device_id}: {alert.message}"

        if self.kind == "slack":
            payload: dict[str, Any] = {"text": message}
        elif self.kind == "discord":
            payload = {"content": message}
        elif self.kind == "telegram":
            parsed = urlsplit(self.webhook_url)
            chat_id = parse_qs(parsed.query).get("chat_id", [""])[0].strip()
            if not chat_id:
                return DeliveryResult(
                    delivered=False,
                    decision="delivery_failed",
                    reason="telegram chat_id missing in webhook URL query",
                    error_class="MISSING_CHAT_ID",
                )
            payload = {"chat_id": chat_id, "text": message}
        else:
            payload = {
                "id": alert.id,
                "device_id": alert.device_id,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "message": alert.message,
                "created_at": alert.created_at.isoformat(),
                "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
            }

        response = requests.post(self.webhook_url, json=payload, timeout=self.timeout_s)
        if 200 <= response.status_code < 300:
            return DeliveryResult(delivered=True, decision="delivered", reason="webhook delivered")

        return DeliveryResult(
            delivered=False,
            decision="delivery_failed",
            reason="webhook non-success response",
            error_class=f"HTTP_{response.status_code}",
        )

    def deliver_platform_event(self, event: PlatformEvent) -> DeliveryResult:
        message = f"[{event.severity.upper()}] {event.event_type} for {event.device_id}: {event.message}"

        if self.kind == "slack":
            payload: dict[str, Any] = {"text": message}
        elif self.kind == "discord":
            payload = {"content": message}
        elif self.kind == "telegram":
            parsed = urlsplit(self.webhook_url)
            chat_id = parse_qs(parsed.query).get("chat_id", [""])[0].strip()
            if not chat_id:
                return DeliveryResult(
                    delivered=False,
                    decision="delivery_failed",
                    reason="telegram chat_id missing in webhook URL query",
                    error_class="MISSING_CHAT_ID",
                )
            payload = {"chat_id": chat_id, "text": message}
        else:
            payload = {
                "source_kind": event.source_kind,
                "source_id": event.source_id,
                "device_id": event.device_id,
                "event_type": event.event_type,
                "severity": event.severity,
                "message": event.message,
                "payload": event.payload,
                "created_at": event.created_at.isoformat(),
            }

        response = requests.post(self.webhook_url, json=payload, timeout=self.timeout_s)
        if 200 <= response.status_code < 300:
            return DeliveryResult(delivered=True, decision="delivered", reason="webhook delivered")

        return DeliveryResult(
            delivered=False,
            decision="delivery_failed",
            reason="webhook non-success response",
            error_class=f"HTTP_{response.status_code}",
        )


def _fingerprint_destination(raw: str | None) -> str | None:
    if not raw:
        return None
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def mask_webhook_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
    except Exception:
        return "***"

    host = parsed.hostname or ""
    scheme = parsed.scheme or "https"
    if not host:
        return "***"
    return f"{scheme}://{host}/***"


def destination_fingerprint(raw: str) -> str:
    fp = _fingerprint_destination(raw)
    return fp or ""


def _configured_destinations(session: Session) -> list[NotificationDestinationConfig]:
    try:
        rows = (
            session.query(NotificationDestination)
            .filter(NotificationDestination.enabled.is_(True))
            .order_by(NotificationDestination.created_at.asc())
            .all()
        )
    except SQLAlchemyError:
        # Older databases may not have the new table yet; keep env-based fallback
        # working until migrations are applied.
        rows = []

    out: list[NotificationDestinationConfig] = []
    seen: set[str] = set()
    for row in rows:
        webhook_url = (row.webhook_url or "").strip()
        if not webhook_url:
            continue
        fp = destination_fingerprint(webhook_url)
        if not fp or fp in seen:
            continue
        seen.add(fp)
        out.append(
            NotificationDestinationConfig(
                name=row.name,
                channel=row.channel,
                kind=row.kind,
                webhook_url=webhook_url,
                source_types=tuple(str(v).strip() for v in (row.source_types or ["alert"]) if str(v).strip()),
                event_types=tuple(str(v).strip() for v in (row.event_types or []) if str(v).strip()),
                destination_fingerprint=fp,
            )
        )

    if out:
        return out

    # Backward-compatibility: if DB destinations are not configured, continue
    # honoring environment-based webhook settings.
    env_webhook_url = (settings.alert_webhook_url or "").strip()
    if not env_webhook_url:
        return []

    fp = destination_fingerprint(env_webhook_url)
    if not fp:
        return []

    return [
        NotificationDestinationConfig(
            name="env-default",
            channel="webhook",
            kind=settings.alert_webhook_kind,
            webhook_url=env_webhook_url,
            source_types=("alert",),
            event_types=(),
            destination_fingerprint=fp,
        )
    ]


def _record_event(
    session: Session,
    *,
    source_kind: str,
    source_id: str | None,
    device_id: str,
    alert_id: str | None,
    alert_type: str,
    decision: str,
    delivered: bool,
    reason: str,
    channel: str,
    destination_fingerprint: str | None,
    error_class: str | None,
    payload: dict[str, Any] | None,
    created_at: datetime,
) -> None:
    session.add(
        NotificationEvent(
            alert_id=alert_id,
            device_id=device_id,
            source_kind=source_kind,
            source_id=source_id,
            alert_type=alert_type,
            channel=channel,
            decision=decision,
            delivered=delivered,
            reason=reason,
            destination_fingerprint=destination_fingerprint,
            error_class=error_class,
            payload=dict(payload or {}),
            created_at=created_at,
        )
    )


def process_alert_notification(
    session: Session,
    alert: Alert,
    *,
    now: datetime | None = None,
) -> None:
    now_utc = now or datetime.now(timezone.utc)
    destinations = _configured_destinations(session)

    if not destinations:
        _record_event(
            session,
            source_kind="alert",
            source_id=alert.id,
            device_id=alert.device_id,
            alert_id=alert.id,
            alert_type=alert.alert_type,
            decision="suppressed_no_adapter",
            delivered=False,
            reason="no notification adapter configured",
            channel="webhook",
            destination_fingerprint=None,
            error_class=None,
            payload={"severity": alert.severity, "message": alert.message},
            created_at=now_utc,
        )
        return

    router = AlertRouter()
    candidate = AlertCandidate(
        alert_id=alert.id,
        device_id=alert.device_id,
        alert_type=alert.alert_type,
        severity=alert.severity,
        message=alert.message,
    )

    decision = router.should_notify(session, candidate, now=now_utc, channel="webhook")
    if not decision.should_notify:
        _record_event(
            session,
            source_kind="alert",
            source_id=alert.id,
            device_id=alert.device_id,
            alert_id=alert.id,
            alert_type=alert.alert_type,
            decision=decision.decision,
            delivered=False,
            reason=decision.reason,
            channel=decision.channel,
            destination_fingerprint=None,
            error_class=None,
            payload={"severity": alert.severity, "message": alert.message},
            created_at=now_utc,
        )
        return

    matched = False
    for destination in destinations:
        if "alert" not in destination.source_types:
            continue
        if destination.event_types and alert.alert_type not in destination.event_types:
            continue
        matched = True
        adapter = WebhookNotificationAdapter(
            webhook_url=destination.webhook_url,
            kind=destination.kind,
            timeout_s=settings.alert_webhook_timeout_s,
        )

        try:
            delivery = adapter.deliver(alert)
        except Exception as exc:  # pragma: no cover - safety guard
            delivery = DeliveryResult(
                delivered=False,
                decision="delivery_failed",
                reason="exception while delivering",
                error_class=type(exc).__name__,
            )

        _record_event(
            session,
            source_kind="alert",
            source_id=alert.id,
            device_id=alert.device_id,
            alert_id=alert.id,
            alert_type=alert.alert_type,
            decision=delivery.decision,
            delivered=delivery.delivered,
            reason=delivery.reason,
            channel=destination.channel,
            destination_fingerprint=destination.destination_fingerprint,
            error_class=delivery.error_class,
            payload={"severity": alert.severity, "message": alert.message},
            created_at=now_utc,
        )

        if not delivery.delivered:
            logger.warning(
                "notification_delivery_failed",
                extra={
                    "fields": {
                        "alert_id": alert.id,
                        "device_id": alert.device_id,
                        "alert_type": alert.alert_type,
                        "error_class": delivery.error_class,
                        "decision": delivery.decision,
                        "destination_fingerprint": destination.destination_fingerprint,
                    }
                },
            )
    if not matched:
        _record_event(
            session,
            source_kind="alert",
            source_id=alert.id,
            device_id=alert.device_id,
            alert_id=alert.id,
            alert_type=alert.alert_type,
            decision="suppressed_no_matching_destination",
            delivered=False,
            reason="no enabled destination matched source/event filters",
            channel="webhook",
            destination_fingerprint=None,
            error_class=None,
            payload={"severity": alert.severity, "message": alert.message},
            created_at=now_utc,
        )


def process_platform_event(
    session: Session,
    event: PlatformEvent,
) -> None:
    destinations = _configured_destinations(session)
    if not destinations:
        _record_event(
            session,
            source_kind=event.source_kind,
            source_id=event.source_id,
            device_id=event.device_id,
            alert_id=None,
            alert_type=event.event_type,
            decision="suppressed_no_adapter",
            delivered=False,
            reason="no notification adapter configured",
            channel="webhook",
            destination_fingerprint=None,
            error_class=None,
            payload=event.payload,
            created_at=event.created_at,
        )
        return

    matched = False
    for destination in destinations:
        if event.source_kind not in destination.source_types:
            continue
        if destination.event_types and event.event_type not in destination.event_types:
            continue
        matched = True
        adapter = WebhookNotificationAdapter(
            webhook_url=destination.webhook_url,
            kind=destination.kind,
            timeout_s=settings.alert_webhook_timeout_s,
        )
        try:
            delivery = adapter.deliver_platform_event(event)
        except Exception as exc:  # pragma: no cover - safety guard
            delivery = DeliveryResult(
                delivered=False,
                decision="delivery_failed",
                reason="exception while delivering",
                error_class=type(exc).__name__,
            )
        _record_event(
            session,
            source_kind=event.source_kind,
            source_id=event.source_id,
            device_id=event.device_id,
            alert_id=None,
            alert_type=event.event_type,
            decision=delivery.decision,
            delivered=delivery.delivered,
            reason=delivery.reason,
            channel=destination.channel,
            destination_fingerprint=destination.destination_fingerprint,
            error_class=delivery.error_class,
            payload=event.payload,
            created_at=event.created_at,
        )
    if not matched:
        _record_event(
            session,
            source_kind=event.source_kind,
            source_id=event.source_id,
            device_id=event.device_id,
            alert_id=None,
            alert_type=event.event_type,
            decision="suppressed_no_matching_destination",
            delivered=False,
            reason="no enabled destination matched source/event filters",
            channel="webhook",
            destination_fingerprint=None,
            error_class=None,
            payload=event.payload,
            created_at=event.created_at,
        )
