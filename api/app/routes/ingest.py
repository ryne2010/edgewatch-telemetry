from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status

from ..config import settings
from ..contracts import load_telemetry_contract
from ..db import db_session
from ..models import Device, IngestionBatch
from ..schemas import IngestRequest, IngestResponse
from ..security import require_device_auth
from ..rate_limit import ingest_points_limiter
from ..observability import record_ingest_points_metric
from ..services.ingest_pipeline import (
    CandidatePoint,
    build_pubsub_batch_payload,
    parse_ingest_source,
    prepare_points,
)
from ..services.ingestion_runtime import (
    persist_points_for_batch,
    record_drift_events,
    record_quarantined_points,
    update_ingestion_batch,
)
from ..services.pubsub import publish_ingestion_batch


router = APIRouter(prefix="/api/v1", tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
def ingest(
    req: IngestRequest,
    device: Device = Depends(require_device_auth),
    x_edgewatch_ingest_source: str | None = Header(default=None, alias="X-EdgeWatch-Ingest-Source"),
) -> IngestResponse:
    """Ingest telemetry for an authenticated device.

    Pipeline modes:
    - direct: persist points synchronously
    - pubsub: enqueue one pubsub message per ingestion batch and return quickly

    Regardless of mode, each request records an ingestion lineage artifact.
    """

    points_count = len(req.points)
    if points_count > settings.max_points_per_request:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error": {
                    "code": "TOO_MANY_POINTS",
                    "message": f"Too many points in one request: {points_count} > {settings.max_points_per_request}",
                    "max_points_per_request": settings.max_points_per_request,
                }
            },
        )

    # Defense-in-depth: device-scoped rate limiting based on points/minute.
    allowed, retry_after_s = ingest_points_limiter.allow(key=device.device_id, cost=points_count)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": {
                    "code": "RATE_LIMITED",
                    "message": "Ingest rate limit exceeded.",
                    "retry_after_s": retry_after_s,
                    "limit_points_per_min": settings.ingest_rate_limit_points_per_min,
                }
            },
            headers={"Retry-After": str(retry_after_s)},
        )

    try:
        contract = load_telemetry_contract(settings.telemetry_contract_version)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="telemetry contract is not available",
        ) from exc

    source = parse_ingest_source(x_edgewatch_ingest_source)
    batch_id = str(uuid.uuid4())

    candidates = [
        CandidatePoint(message_id=point.message_id, ts=point.ts, metrics=dict(point.metrics))
        for point in req.points
    ]

    prepared = prepare_points(
        points=candidates,
        contract=contract,
        unknown_keys_mode=settings.telemetry_contract_unknown_keys_mode,
        type_mismatch_mode=settings.telemetry_contract_type_mismatch_mode,
    )

    ingest_response: IngestResponse | None = None
    reject_detail: dict[str, object] | None = None
    publish_payload: dict[str, object] | None = None

    with db_session() as session:
        batch = IngestionBatch(
            id=batch_id,
            device_id=device.device_id,
            contract_version=contract.version,
            contract_hash=contract.sha256,
            points_submitted=len(req.points),
            points_accepted=0,
            duplicates=0,
            points_quarantined=len(prepared.quarantined_points),
            client_ts_min=prepared.client_ts_min,
            client_ts_max=prepared.client_ts_max,
            unknown_metric_keys=prepared.unknown_metric_keys,
            type_mismatch_keys=prepared.type_mismatch_keys,
            drift_summary=prepared.drift_summary,
            source=source,
            pipeline_mode=settings.ingest_pipeline_mode,
            processing_status="pending",
        )
        session.add(batch)
        session.flush()

        record_drift_events(
            session,
            batch_id=batch_id,
            device_id=device.device_id,
            unknown_metric_keys=prepared.unknown_metric_keys,
            type_mismatch_keys=prepared.type_mismatch_keys,
            type_mismatch_count=prepared.type_mismatch_count,
            unknown_keys_mode=settings.telemetry_contract_unknown_keys_mode,
            type_mismatch_mode=settings.telemetry_contract_type_mismatch_mode,
        )
        record_quarantined_points(
            session,
            batch_id=batch_id,
            device_id=device.device_id,
            points=prepared.quarantined_points,
        )

        if prepared.reject_errors:
            batch.processing_status = "rejected"
            reject_sample = prepared.reject_errors[:10]
            reject_detail = {
                "error": "telemetry metrics failed contract validation",
                "batch_id": batch_id,
                "contract_version": contract.version,
                "contract_hash": contract.sha256,
                "errors": reject_sample,
                "error_count": len(prepared.reject_errors),
            }
        elif settings.ingest_pipeline_mode == "direct":
            accepted, duplicates, _ = persist_points_for_batch(
                session,
                batch_id=batch_id,
                device_id=device.device_id,
                points=prepared.accepted_points,
            )
            update_ingestion_batch(
                session,
                batch_id=batch_id,
                points_accepted=accepted,
                duplicates=duplicates,
                processing_status="completed",
            )
            ingest_response = IngestResponse(
                device_id=device.device_id,
                batch_id=batch_id,
                accepted=accepted,
                duplicates=duplicates,
                quarantined=len(prepared.quarantined_points),
            )
        else:
            if prepared.accepted_points:
                publish_payload = build_pubsub_batch_payload(
                    batch_id=batch_id,
                    device_id=device.device_id,
                    source=source,
                    points=prepared.accepted_points,
                )
                batch.processing_status = "queued"
            else:
                batch.processing_status = "completed"

            ingest_response = IngestResponse(
                device_id=device.device_id,
                batch_id=batch_id,
                accepted=len(prepared.accepted_points),
                duplicates=0,
                quarantined=len(prepared.quarantined_points),
            )

    if reject_detail is not None:
        record_ingest_points_metric(
            accepted=0,
            rejected=points_count,
            source=source,
            pipeline_mode=settings.ingest_pipeline_mode,
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=reject_detail)

    if publish_payload is not None:
        try:
            publish_ingestion_batch(publish_payload)
        except Exception as exc:
            with db_session() as session:
                update_ingestion_batch(
                    session,
                    batch_id=batch_id,
                    points_accepted=0,
                    duplicates=0,
                    processing_status="publish_failed",
                )
            record_ingest_points_metric(
                accepted=0,
                rejected=len(prepared.accepted_points) + len(prepared.quarantined_points),
                source=source,
                pipeline_mode=settings.ingest_pipeline_mode,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "failed to publish telemetry batch",
                    "batch_id": batch_id,
                },
            ) from exc

    if ingest_response is None:
        # Defensive fallback; should not happen due flow above.
        ingest_response = IngestResponse(
            device_id=device.device_id,
            batch_id=batch_id,
            accepted=0,
            duplicates=0,
            quarantined=len(prepared.quarantined_points),
        )

    record_ingest_points_metric(
        accepted=int(ingest_response.accepted),
        rejected=len(prepared.quarantined_points),
        source=source,
        pipeline_mode=settings.ingest_pipeline_mode,
    )

    return ingest_response
