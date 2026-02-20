from __future__ import annotations

import base64
import json
from typing import Any, Mapping

from ..config import settings


def publish_ingestion_batch(payload: Mapping[str, Any], *, timeout_s: float = 10.0) -> str:
    project_id = settings.ingest_pubsub_project_id
    if not project_id:
        raise RuntimeError("INGEST_PUBSUB_PROJECT_ID (or GCP_PROJECT_ID) is required for pubsub mode")

    try:
        from google.cloud import pubsub_v1  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("google-cloud-pubsub is not installed") from exc

    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(project_id, settings.ingest_pubsub_topic)
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    future = publisher.publish(topic_path, data=data)
    message_id = future.result(timeout=timeout_s)
    return str(message_id)


def decode_pubsub_push_request(body: Mapping[str, Any]) -> tuple[dict[str, Any], str | None]:
    message = body.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("missing pubsub message")

    encoded_data = message.get("data")
    if not isinstance(encoded_data, str) or not encoded_data:
        raise ValueError("missing pubsub message data")

    try:
        decoded_bytes = base64.b64decode(encoded_data.encode("utf-8"), validate=True)
    except Exception as exc:
        raise ValueError("invalid pubsub message data") from exc

    try:
        payload = json.loads(decoded_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid pubsub payload json") from exc

    if not isinstance(payload, dict):
        raise ValueError("pubsub payload must be a json object")

    message_id_raw = message.get("messageId") or message.get("message_id")
    message_id = str(message_id_raw).strip() if message_id_raw is not None else None
    return payload, (message_id or None)
