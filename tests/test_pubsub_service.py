from __future__ import annotations

import base64
import json
import sys
import types

from api.app.services import pubsub


def test_decode_pubsub_push_request() -> None:
    payload = {
        "batch_id": "b-1",
        "device_id": "d-1",
        "points": [{"message_id": "m-1", "ts": "2026-01-01T00:00:00+00:00", "metrics": {}}],
    }
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")

    body = {"message": {"data": encoded, "messageId": "123"}}
    decoded, message_id = pubsub.decode_pubsub_push_request(body)

    assert decoded == payload
    assert message_id == "123"


def test_publish_ingestion_batch_with_mocked_pubsub_client(monkeypatch) -> None:
    class _FakeFuture:
        def result(self, timeout: float | None = None) -> str:
            assert timeout == 10.0
            return "msg-123"

    class _FakePublisherClient:
        last_topic_path = ""
        last_payload = b""

        def topic_path(self, project_id: str, topic: str) -> str:
            return f"projects/{project_id}/topics/{topic}"

        def publish(self, topic_path: str, data: bytes) -> _FakeFuture:
            _FakePublisherClient.last_topic_path = topic_path
            _FakePublisherClient.last_payload = data
            return _FakeFuture()

    fake_google = types.ModuleType("google")
    fake_cloud = types.ModuleType("google.cloud")
    fake_pubsub_v1 = types.ModuleType("google.cloud.pubsub_v1")
    fake_pubsub_v1.PublisherClient = _FakePublisherClient  # type: ignore[attr-defined]

    fake_google.cloud = fake_cloud  # type: ignore[attr-defined]
    fake_cloud.pubsub_v1 = fake_pubsub_v1  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.cloud", fake_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.pubsub_v1", fake_pubsub_v1)

    monkeypatch.setattr(
        pubsub,
        "settings",
        types.SimpleNamespace(
            ingest_pubsub_project_id="demo-project",
            ingest_pubsub_topic="telemetry-raw",
        ),
    )

    message_id = pubsub.publish_ingestion_batch({"k": "v"})

    assert message_id == "msg-123"
    assert _FakePublisherClient.last_topic_path == "projects/demo-project/topics/telemetry-raw"
    assert json.loads(_FakePublisherClient.last_payload.decode("utf-8")) == {"k": "v"}
