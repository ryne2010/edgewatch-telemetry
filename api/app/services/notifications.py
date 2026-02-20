from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Alert, NotificationEvent
from .routing import AlertCandidate, AlertRouter


logger = logging.getLogger("edgewatch.notifications")


@dataclass(frozen=True)
class DeliveryResult:
    delivered: bool
    decision: str
    reason: str
    error_class: str | None = None


class WebhookNotificationAdapter:
    def __init__(self, *, webhook_url: str, kind: str, timeout_s: float) -> None:
        self.webhook_url = webhook_url
        self.kind = kind
        self.timeout_s = timeout_s

    def deliver(self, alert: Alert) -> DeliveryResult:
        if self.kind == "slack":
            payload: dict[str, Any] = {
                "text": f"[{alert.severity.upper()}] {alert.alert_type} for {alert.device_id}: {alert.message}"
            }
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


def _fingerprint_destination(raw: str | None) -> str | None:
    if not raw:
        return None
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _record_event(
    session: Session,
    *,
    alert: Alert,
    decision: str,
    delivered: bool,
    reason: str,
    channel: str,
    destination_fingerprint: str | None,
    error_class: str | None,
    created_at: datetime,
) -> None:
    session.add(
        NotificationEvent(
            alert_id=alert.id,
            device_id=alert.device_id,
            alert_type=alert.alert_type,
            channel=channel,
            decision=decision,
            delivered=delivered,
            reason=reason,
            destination_fingerprint=destination_fingerprint,
            error_class=error_class,
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
    webhook_url = settings.alert_webhook_url
    destination_fingerprint = _fingerprint_destination(webhook_url)

    if not webhook_url:
        _record_event(
            session,
            alert=alert,
            decision="suppressed_no_adapter",
            delivered=False,
            reason="no notification adapter configured",
            channel="webhook",
            destination_fingerprint=destination_fingerprint,
            error_class=None,
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
            alert=alert,
            decision=decision.decision,
            delivered=False,
            reason=decision.reason,
            channel=decision.channel,
            destination_fingerprint=destination_fingerprint,
            error_class=None,
            created_at=now_utc,
        )
        return

    adapter = WebhookNotificationAdapter(
        webhook_url=webhook_url,
        kind=settings.alert_webhook_kind,
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
        alert=alert,
        decision=delivery.decision,
        delivered=delivery.delivered,
        reason=delivery.reason,
        channel=decision.channel,
        destination_fingerprint=destination_fingerprint,
        error_class=delivery.error_class,
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
                }
            },
        )
