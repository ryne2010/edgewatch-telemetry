from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_

from ..auth.principal import Principal
from ..auth.rbac import require_viewer_role
from ..db import db_session
from ..models import Alert
from ..schemas import AlertOut
from ..services.device_access import accessible_device_ids_subquery, ensure_device_access

router = APIRouter(prefix="/api/v1", tags=["alerts"])


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    device_id: str | None = None,
    open_only: bool = False,
    severity: str | None = None,
    alert_type: str | None = None,
    before: datetime | None = Query(
        None,
        description=(
            "Cursor pagination: return alerts created *before* this timestamp. "
            "Use the created_at + id of the last row from the previous page."
        ),
    ),
    before_id: str | None = Query(
        None,
        description="Cursor pagination tie-breaker when multiple alerts share the same created_at.",
    ),
    limit: int = Query(100, ge=1, le=1000),
    principal: Principal = Depends(require_viewer_role),
) -> list[AlertOut]:
    """List alerts.

    - Ordered by (created_at desc, id desc).
    - Cursor pagination uses (before, before_id) from the last row.
    - Filtering is optional and safe to combine.
    """

    if before_id is not None and before is None:
        raise HTTPException(status_code=400, detail="before_id requires before")

    with db_session() as session:
        q = session.query(Alert)

        if device_id:
            ensure_device_access(session, principal=principal, device_id=device_id, min_access_role="viewer")
        accessible_ids = accessible_device_ids_subquery(
            session, principal=principal, min_access_role="viewer"
        )
        if accessible_ids is not None:
            q = q.filter(Alert.device_id.in_(accessible_ids))

        if device_id:
            q = q.filter(Alert.device_id == device_id)
        if open_only:
            q = q.filter(Alert.resolved_at.is_(None))
        if severity:
            q = q.filter(Alert.severity == severity)
        if alert_type:
            q = q.filter(Alert.alert_type == alert_type)

        if before is not None:
            if before_id is not None:
                q = q.filter(
                    or_(
                        Alert.created_at < before,
                        and_(Alert.created_at == before, Alert.id < before_id),
                    )
                )
            else:
                q = q.filter(Alert.created_at < before)

        q = q.order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit)

        rows = q.all()

        return [
            AlertOut(
                id=a.id,
                device_id=a.device_id,
                alert_type=a.alert_type,
                severity=a.severity,
                message=a.message,
                created_at=a.created_at,
                resolved_at=a.resolved_at,
            )
            for a in rows
        ]
