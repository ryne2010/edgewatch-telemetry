from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from ..models import AdminEvent


logger = logging.getLogger("edgewatch.admin")


def record_admin_event(
    session: Session,
    *,
    actor_email: str,
    actor_subject: str | None,
    action: str,
    target_type: str,
    target_device_id: str | None,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AdminEvent:
    event = AdminEvent(
        actor_email=actor_email,
        actor_subject=actor_subject,
        action=action,
        target_type=target_type,
        target_device_id=target_device_id,
        details=dict(details or {}),
        request_id=request_id,
    )
    session.add(event)
    logger.info(
        "admin_event",
        extra={
            "fields": {
                "actor_email": actor_email,
                "actor_subject": actor_subject,
                "action": action,
                "target_type": target_type,
                "target_device_id": target_device_id,
                "request_id": request_id,
            }
        },
    )
    return event
