from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Response, status

from ..config import settings
from ..db import db_session
from ..models import IngestionBatch
from ..services.ingest_pipeline import parse_pubsub_batch_payload
from ..services.ingestion_runtime import persist_points_for_batch, update_ingestion_batch
from ..services.pubsub import decode_pubsub_push_request


router = APIRouter(prefix="/api/v1/internal", tags=["ingest-pipeline"])


@router.post(
    "/pubsub/push",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def pubsub_push(
    body: dict[str, Any],
    x_edgewatch_push_token: str | None = Header(default=None, alias="X-EdgeWatch-Push-Token"),
) -> Response:
    if settings.ingest_pipeline_mode != "pubsub":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="pubsub ingest mode disabled")

    expected_token = settings.ingest_pubsub_push_shared_token
    if expected_token:
        provided = (x_edgewatch_push_token or "").strip()
        if not provided or not hmac.compare_digest(provided, expected_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid push token")

    try:
        payload, _ = decode_pubsub_push_request(body)
        parsed = parse_pubsub_batch_payload(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    with db_session() as session:
        accepted, duplicates, _ = persist_points_for_batch(
            session,
            batch_id=parsed.batch_id,
            device_id=parsed.device_id,
            points=parsed.points,
        )

        batch = session.query(IngestionBatch).filter(IngestionBatch.id == parsed.batch_id).one_or_none()
        if batch is not None:
            batch.pipeline_mode = "pubsub"
            batch.source = parsed.source

        update_ingestion_batch(
            session,
            batch_id=parsed.batch_id,
            points_accepted=accepted,
            duplicates=duplicates,
            processing_status="completed",
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
