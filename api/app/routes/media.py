from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response

from ..db import db_session
from ..models import Device, MediaObject
from ..schemas import (
    MediaCreateRequest,
    MediaCreateResponse,
    MediaObjectOut,
    MediaUploadInstructionOut,
)
from ..security import require_device_auth
from ..services.media import (
    MediaConfigError,
    MediaConflictError,
    MediaCreateInput,
    MediaNotUploadedError,
    MediaValidationError,
    build_media_store,
    create_or_get_media_object,
    get_media_for_device,
    list_device_media,
    read_media_payload,
    upload_media_payload,
)

router = APIRouter(prefix="/api/v1", tags=["media"])


def _to_media_out(media: MediaObject) -> MediaObjectOut:
    return MediaObjectOut(
        id=media.id,
        device_id=media.device_id,
        camera_id=media.camera_id,
        message_id=media.message_id,
        captured_at=media.captured_at,
        reason=media.reason,
        sha256=media.sha256,
        bytes=media.bytes,
        mime_type=media.mime_type,
        object_path=media.object_path,
        gcs_uri=media.gcs_uri,
        local_path=media.local_path,
        uploaded_at=media.uploaded_at,
        created_at=media.created_at,
    )


@router.post("/media", response_model=MediaCreateResponse)
def create_media_object(
    req: MediaCreateRequest,
    device: Device = Depends(require_device_auth),
) -> MediaCreateResponse:
    try:
        store = build_media_store()
    except MediaConfigError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    with db_session() as session:
        try:
            media, _ = create_or_get_media_object(
                session,
                device_id=device.device_id,
                create=MediaCreateInput(
                    message_id=req.message_id,
                    camera_id=req.camera_id,
                    captured_at=req.captured_at,
                    reason=req.reason,
                    sha256=req.sha256,
                    bytes=req.bytes,
                    mime_type=req.mime_type,
                ),
                store=store,
            )
        except MediaValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except MediaConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        media_out = _to_media_out(media)
        upload = MediaUploadInstructionOut(
            method="PUT",
            url=f"/api/v1/media/{media.id}/upload",
            headers={"Content-Type": media.mime_type},
        )
        return MediaCreateResponse(media=media_out, upload=upload)


@router.put("/media/{media_id}/upload", response_model=MediaObjectOut)
async def upload_media_object(
    media_id: str,
    request: Request,
    content_type: str | None = Header(default=None, alias="Content-Type"),
    device: Device = Depends(require_device_auth),
) -> MediaObjectOut:
    payload = await request.body()
    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty payload")

    try:
        store = build_media_store()
    except MediaConfigError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    with db_session() as session:
        media = get_media_for_device(session, media_id=media_id, device_id=device.device_id)
        if media is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="media not found")

        try:
            updated = upload_media_payload(
                session,
                media=media,
                payload=payload,
                content_type=content_type,
                store=store,
            )
        except MediaValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        return _to_media_out(updated)


@router.get("/devices/{device_id}/media", response_model=list[MediaObjectOut])
def list_media_objects(
    device_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    device: Device = Depends(require_device_auth),
) -> list[MediaObjectOut]:
    if device_id != device.device_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    with db_session() as session:
        rows = list_device_media(session, device_id=device_id, limit=limit)
        return [_to_media_out(row) for row in rows]


@router.get("/media/{media_id}", response_model=MediaObjectOut)
def get_media_object(
    media_id: str,
    device: Device = Depends(require_device_auth),
) -> MediaObjectOut:
    with db_session() as session:
        media = get_media_for_device(session, media_id=media_id, device_id=device.device_id)
        if media is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="media not found")
        return _to_media_out(media)


@router.get("/media/{media_id}/download")
def download_media_object(
    media_id: str,
    device: Device = Depends(require_device_auth),
) -> Response:
    try:
        store = build_media_store()
    except MediaConfigError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    with db_session() as session:
        media = get_media_for_device(session, media_id=media_id, device_id=device.device_id)
        if media is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="media not found")
        try:
            payload = read_media_payload(media=media, store=store)
        except MediaNotUploadedError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    filename = media.object_path.rsplit("/", 1)[-1]
    return Response(
        content=payload,
        media_type=media.mime_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
