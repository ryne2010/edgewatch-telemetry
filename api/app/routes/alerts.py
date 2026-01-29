from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Query
from sqlalchemy import desc

from ..db import db_session
from ..models import Alert
from ..schemas import AlertOut

router = APIRouter(prefix="/api/v1", tags=["alerts"])


@router.get("/alerts", response_model=List[AlertOut])
def list_alerts(
    device_id: Optional[str] = Query(default=None),
    open_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=1000),
):
    with db_session() as session:
        q = session.query(Alert)
        if device_id:
            q = q.filter(Alert.device_id == device_id)
        if open_only:
            q = q.filter(Alert.resolved_at.is_(None))
        q = q.order_by(desc(Alert.created_at)).limit(limit)
        rows = q.all()
        return [
            AlertOut(
                id=r.id,
                device_id=r.device_id,
                alert_type=r.alert_type,
                severity=r.severity,
                message=r.message,
                created_at=r.created_at,
                resolved_at=r.resolved_at,
            )
            for r in rows
        ]
