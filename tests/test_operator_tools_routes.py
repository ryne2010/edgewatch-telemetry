from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.app.auth.principal import Principal
from api.app.db import Base
from api.app.models import (
    AdminEvent,
    Alert,
    Deployment,
    DeploymentEvent,
    Device,
    DeviceEvent,
    DeviceProcedureDefinition,
    DeviceProcedureInvocation,
    DriftEvent,
    ExportBatch,
    Fleet,
    IngestionBatch,
    NotificationDestination,
    NotificationEvent,
    ReleaseManifest,
)
from api.app.routes import operator_tools as operator_tools_routes
from starlette.requests import Request


def _db_override(tmp_path: Path):
    db_path = tmp_path / "operator-tools.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    @contextmanager
    def _db_session():
        session = session_local()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return session_local, _db_session


def test_operator_search_returns_mixed_results(tmp_path: Path, monkeypatch) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(operator_tools_routes, "db_session", db_override)

    with session_local() as session:
        device = Device(
            device_id="well-777",
            display_name="Pilot Well 777",
            token_hash="hash",
            token_fingerprint="fp-well-777",
            heartbeat_interval_s=300,
            offline_after_s=900,
            enabled=True,
        )
        fleet = Fleet(name="Pilot Fleet", default_ota_channel="pilot")
        definition = DeviceProcedureDefinition(
            name="capture_snapshot",
            description="Pilot capture a photo",
            request_schema={},
            response_schema={},
            timeout_s=120,
            enabled=True,
            created_by="admin@example.com",
        )
        session.add_all([device, fleet, definition])
        session.flush()
        session.add(
            DeviceEvent(
                device_id=device.device_id,
                event_type="procedure.capture_snapshot.requested",
                severity="info",
                body={"camera_id": "cam1"},
            )
        )
        session.add(
            Alert(
                device_id=device.device_id,
                alert_type="BATTERY_LOW",
                severity="warning",
                message="Pilot battery low",
            )
        )
        session.add(
            IngestionBatch(
                device_id=device.device_id,
                contract_version="pilot-v1",
                contract_hash="pilot-hash",
                points_submitted=10,
                points_accepted=9,
                duplicates=1,
                points_quarantined=0,
                client_ts_min=None,
                client_ts_max=None,
                unknown_metric_keys=[],
                type_mismatch_keys=[],
                drift_summary={},
                source="device",
                pipeline_mode="strict",
                processing_status="accepted",
            )
        )
        session.flush()
        batch = session.query(IngestionBatch).filter(IngestionBatch.device_id == device.device_id).one()
        session.add(
            DriftEvent(
                batch_id=batch.id,
                device_id=device.device_id,
                event_type="unknown_metric",
                action="warn",
                details={"metric": "pilot_metric"},
            )
        )
        session.add(
            DeviceProcedureInvocation(
                device_id=device.device_id,
                definition_id=definition.id,
                request_payload={"camera_id": "cam1"},
                status="queued",
                requester_email="operator@example.com",
                issued_at=operator_tools_routes._utcnow(),
                expires_at=operator_tools_routes._utcnow(),
            )
        )
        session.add(
            Deployment(
                manifest_id="manifest-1",
                strategy={"rollout_stages_pct": [100]},
                stage=0,
                status="active",
                created_by="admin@example.com",
                failure_rate_threshold=0.2,
                no_quorum_timeout_s=1800,
                stage_timeout_s=1800,
                defer_rate_threshold=0.5,
                command_expires_at=operator_tools_routes._utcnow(),
                power_guard_required=True,
                health_timeout_s=300,
                target_selector={"mode": "all"},
            )
        )
        session.add(
            ReleaseManifest(
                git_tag="Pilot Release",
                commit_sha="c" * 40,
                update_type="application_bundle",
                artifact_uri="https://example.com/pilot-release.tar",
                artifact_size=1024,
                artifact_sha256="d" * 64,
                artifact_signature="",
                artifact_signature_scheme="none",
                compatibility={},
                signature="sig",
                signature_key_id="ops-key-1",
                constraints={},
                created_by="admin@example.com",
                status="active",
            )
        )
        session.add(
            AdminEvent(
                actor_email="admin@example.com",
                actor_subject=None,
                action="pilot.device.update",
                target_type="device",
                target_device_id=device.device_id,
                details={"field": "display_name"},
                created_at=operator_tools_routes._utcnow(),
            )
        )
        session.add(
            NotificationEvent(
                alert_id=None,
                device_id=device.device_id,
                source_kind="alert",
                source_id=None,
                alert_type="BATTERY_LOW",
                channel="webhook",
                decision="delivered",
                delivered=True,
                reason="Pilot notification",
                payload={},
                created_at=operator_tools_routes._utcnow(),
            )
        )
        session.add(
            NotificationDestination(
                name="Pilot Webhook",
                channel="webhook",
                kind="generic",
                source_types=["alert", "device_event"],
                event_types=["BATTERY_LOW"],
                enabled=True,
                webhook_url="https://example.com/pilot-webhook",
            )
        )
        session.add(
            ExportBatch(
                started_at=operator_tools_routes._utcnow(),
                finished_at=operator_tools_routes._utcnow(),
                watermark_from=None,
                watermark_to=None,
                contract_version="v1",
                contract_hash="hash",
                gcs_uri="gs://pilot/export.ndjson",
                row_count=10,
                status="completed",
                error_message=None,
            )
        )
        session.commit()

    results = operator_tools_routes.operator_search(
        q="Pilot",
        limit=20,
        principal=Principal(email="admin@example.com", role="admin", source="test"),
    )

    entity_types = {row.entity_type for row in results}
    assert "device" in entity_types
    assert "fleet" in entity_types
    assert "alert" in entity_types
    assert "ingestion_batch" in entity_types
    assert "drift_event" in entity_types
    assert "procedure_definition" in entity_types
    assert "notification_event" in entity_types
    assert "notification_destination" in entity_types
    assert "release_manifest" in entity_types
    assert "admin_event" in entity_types
    assert "notification_event" in entity_types
    assert "export_batch" in entity_types

    notification_result = next(row for row in results if row.entity_type == "notification_event")
    assert notification_result.metadata["channel"] == "webhook"
    assert notification_result.metadata["decision"] == "delivered"
    assert notification_result.metadata["source_kind"] == "alert"
    assert notification_result.metadata["delivered"] is True


def test_operator_search_supports_entity_type_filter(tmp_path: Path, monkeypatch) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(operator_tools_routes, "db_session", db_override)

    with session_local() as session:
        device = Device(
            device_id="well-999",
            display_name="Search Well 999",
            token_hash="hash",
            token_fingerprint="fp-well-999",
            heartbeat_interval_s=300,
            offline_after_s=900,
            enabled=True,
        )
        session.add(device)
        session.add(
            Alert(
                device_id=device.device_id,
                alert_type="SEARCHABLE_ALERT",
                severity="warning",
                message="Search test alert",
            )
        )
        session.commit()

    results = operator_tools_routes.operator_search(
        q="Search",
        limit=20,
        entity_types=["alert"],
        principal=Principal(email="admin@example.com", role="admin", source="test"),
    )

    assert results
    assert {row.entity_type for row in results} == {"alert"}


def test_operator_search_supports_offset_pagination(tmp_path: Path, monkeypatch) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(operator_tools_routes, "db_session", db_override)

    with session_local() as session:
        for idx in range(3):
            session.add(
                Device(
                    device_id=f"search-{idx}",
                    display_name=f"Search Device {idx}",
                    token_hash="hash",
                    token_fingerprint=f"fp-search-{idx}",
                    heartbeat_interval_s=300,
                    offline_after_s=900,
                    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=idx),
                    enabled=True,
                )
            )
        session.commit()

    page = operator_tools_routes.operator_search(
        q="Search Device",
        limit=1,
        offset=1,
        entity_types=["device"],
        principal=Principal(email="admin@example.com", role="admin", source="test"),
    )

    assert len(page) == 1
    assert page[0].entity_id == "search-1"


def test_operator_search_includes_release_manifest_results(tmp_path: Path, monkeypatch) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(operator_tools_routes, "db_session", db_override)

    with session_local() as session:
        session.add(
            ReleaseManifest(
                git_tag="searchable-release",
                commit_sha="a" * 40,
                update_type="application_bundle",
                artifact_uri="https://example.com/release.tar",
                artifact_size=1024,
                artifact_sha256="b" * 64,
                artifact_signature="",
                artifact_signature_scheme="none",
                compatibility={},
                signature="sig",
                signature_key_id="ops-key-1",
                constraints={},
                created_by="admin@example.com",
                status="active",
            )
        )
        session.commit()

    results = operator_tools_routes.operator_search(
        q="searchable-release",
        limit=20,
        entity_types=["release_manifest"],
        principal=Principal(email="admin@example.com", role="admin", source="test"),
    )

    assert len(results) == 1
    assert results[0].entity_type == "release_manifest"
    assert results[0].title == "searchable-release"


def test_operator_search_page_reports_total_and_items(tmp_path: Path, monkeypatch) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(operator_tools_routes, "db_session", db_override)

    with session_local() as session:
        for idx in range(3):
            session.add(
                Device(
                    device_id=f"page-{idx}",
                    display_name=f"Page Device {idx}",
                    token_hash="hash",
                    token_fingerprint=f"fp-page-{idx}",
                    heartbeat_interval_s=300,
                    offline_after_s=900,
                    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=idx),
                    enabled=True,
                )
            )
        session.commit()

    page = operator_tools_routes.operator_search_page(
        q="Page Device",
        limit=1,
        offset=1,
        entity_types=["device"],
        principal=Principal(email="admin@example.com", role="admin", source="test"),
    )

    assert page.total == 3
    assert page.limit == 1
    assert page.offset == 1
    assert len(page.items) == 1
    assert page.items[0].entity_id == "page-1"


def test_operator_events_returns_mixed_paged_history(tmp_path: Path, monkeypatch) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(operator_tools_routes, "db_session", db_override)
    base_now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    with session_local() as session:
        device = Device(
            device_id="well-990",
            display_name="History Well 990",
            token_hash="hash",
            token_fingerprint="fp-well-990",
            heartbeat_interval_s=300,
            offline_after_s=900,
            enabled=True,
        )
        definition = DeviceProcedureDefinition(
            name="capture_snapshot",
            description="Capture",
            request_schema={},
            response_schema={},
            timeout_s=120,
            enabled=True,
            created_by="admin@example.com",
        )
        session.add_all([device, definition])
        session.flush()
        session.add(
            Alert(
                device_id=device.device_id,
                alert_type="ALERT_ONE",
                severity="warning",
                message="First",
                created_at=base_now - timedelta(seconds=30),
            )
        )
        session.add(
            DeviceEvent(
                device_id=device.device_id,
                event_type="device.custom",
                severity="info",
                body={"ok": True},
                created_at=base_now - timedelta(seconds=20),
            )
        )
        session.add(
            DeviceProcedureInvocation(
                device_id=device.device_id,
                definition_id=definition.id,
                request_payload={"camera_id": "cam1"},
                status="queued",
                requester_email="operator@example.com",
                issued_at=base_now - timedelta(seconds=10),
                expires_at=base_now + timedelta(minutes=5),
            )
        )
        deployment = Deployment(
            manifest_id="manifest-xyz",
            strategy={"rollout_stages_pct": [100]},
            stage=0,
            status="active",
            created_by="admin@example.com",
            failure_rate_threshold=0.2,
            no_quorum_timeout_s=1800,
            stage_timeout_s=1800,
            defer_rate_threshold=0.5,
            command_expires_at=base_now + timedelta(hours=1),
            power_guard_required=True,
            health_timeout_s=300,
            target_selector={"mode": "all"},
        )
        session.add(deployment)
        session.flush()
        session.add(
            DeploymentEvent(
                deployment_id=deployment.id,
                event_type="deployment.stage_advanced",
                device_id=device.device_id,
                details={"stage": 1},
                created_at=base_now - timedelta(seconds=5),
            )
        )
        session.add(
            AdminEvent(
                actor_email="admin@example.com",
                actor_subject=None,
                action="release_manifest.update",
                target_type="release_manifest",
                target_device_id=None,
                details={"manifest_id": "manifest-xyz", "git_tag": "v1.2.3"},
                created_at=base_now - timedelta(seconds=2),
            )
        )
        session.add(
            AdminEvent(
                actor_email="admin@example.com",
                actor_subject=None,
                action="edge_policy_contract.update",
                target_type="edge_policy_contract",
                target_device_id=None,
                details={"policy_version": "v1"},
                created_at=base_now - timedelta(seconds=1),
            )
        )
        session.commit()

    page = operator_tools_routes.operator_events(
        limit=2,
        offset=0,
        device_id="well-990",
        source_kinds=[
            "alert",
            "device_event",
            "procedure_invocation",
            "deployment_event",
            "release_manifest_event",
            "admin_event",
        ],
        event_name=None,
        principal=Principal(email="admin@example.com", role="admin", source="test"),
    )

    assert page.total == 6
    assert page.limit == 2
    assert page.offset == 0
    assert len(page.items) == 2
    assert page.items[0].source_kind == "admin_event"


def test_operator_events_includes_notification_events_for_admin(tmp_path: Path, monkeypatch) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(operator_tools_routes, "db_session", db_override)
    base_now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    with session_local() as session:
        device = Device(
            device_id="well-991",
            display_name="Notify Well 991",
            token_hash="hash",
            token_fingerprint="fp-well-991",
            heartbeat_interval_s=300,
            offline_after_s=900,
            enabled=True,
        )
        session.add(device)
        session.flush()
        session.add(
            NotificationEvent(
                alert_id=None,
                device_id=device.device_id,
                source_kind="alert",
                source_id=None,
                alert_type="BATTERY_LOW",
                channel="webhook",
                decision="delivered",
                delivered=True,
                reason="Recent notification",
                payload={"destination": "ops-webhook"},
                created_at=base_now - timedelta(seconds=5),
            )
        )
        session.commit()

    page = operator_tools_routes.operator_events(
        limit=10,
        offset=0,
        device_id="well-991",
        source_kinds=["notification_event"],
        event_name="BATTERY_LOW",
        principal=Principal(email="admin@example.com", role="admin", source="test"),
    )

    assert page.total == 1
    assert len(page.items) == 1
    assert page.items[0].source_kind == "notification_event"
    assert page.items[0].event_name == "BATTERY_LOW"
    assert page.items[0].payload["channel"] == "webhook"


class _DisconnectAfterOneLoop:
    def __init__(self) -> None:
        self.calls = 0

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return self.calls > 1


@pytest.mark.anyio
async def test_event_stream_supports_server_side_source_and_event_name_filters(
    tmp_path: Path, monkeypatch
) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(operator_tools_routes, "db_session", db_override)

    with session_local() as session:
        device = Device(
            device_id="well-888",
            display_name="Pilot Well 888",
            token_hash="hash",
            token_fingerprint="fp-well-888",
            heartbeat_interval_s=300,
            offline_after_s=900,
            enabled=True,
        )
        definition = DeviceProcedureDefinition(
            name="capture_snapshot",
            description="Capture a photo",
            request_schema={},
            response_schema={},
            timeout_s=120,
            enabled=True,
            created_by="admin@example.com",
        )
        session.add_all([device, definition])
        session.flush()
        session.add(
            Alert(
                device_id=device.device_id,
                alert_type="BATTERY_LOW",
                severity="warning",
                message="Battery low",
            )
        )
        session.add(
            DeviceEvent(
                device_id=device.device_id,
                event_type="procedure.capture_snapshot.requested",
                severity="info",
                body={"camera_id": "cam1"},
            )
        )
        session.add(
            DeviceProcedureInvocation(
                device_id=device.device_id,
                definition_id=definition.id,
                request_payload={"camera_id": "cam1"},
                status="queued",
                requester_email="operator@example.com",
                issued_at=operator_tools_routes._utcnow(),
                expires_at=operator_tools_routes._utcnow(),
            )
        )
        session.commit()

    request = _DisconnectAfterOneLoop()
    principal = Principal(email="admin@example.com", role="admin", source="test")
    monkeypatch.setattr(
        operator_tools_routes,
        "_utcnow",
        lambda: datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    chunks: list[str] = []
    async for chunk in operator_tools_routes._stream_events(
        request=cast(Request, request),
        principal=principal,
        device_id="well-888",
        source_kinds=["alert"],
        event_name="BATTERY_LOW",
        since_seconds=0,
    ):
        chunks.append(chunk)

    data_chunks = [chunk for chunk in chunks if chunk.startswith("data: ")]
    assert len(data_chunks) >= 1
    payload = json.loads(data_chunks[0].removeprefix("data: "))
    assert payload["type"] == "alert"
    assert payload["event_type"] == "BATTERY_LOW"


@pytest.mark.anyio
async def test_event_stream_since_seconds_replays_recent_events(tmp_path: Path, monkeypatch) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(operator_tools_routes, "db_session", db_override)
    base_now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    with session_local() as session:
        device = Device(
            device_id="well-889",
            display_name="Replay Well 889",
            token_hash="hash",
            token_fingerprint="fp-well-889",
            heartbeat_interval_s=300,
            offline_after_s=900,
            enabled=True,
        )
        session.add(device)
        session.flush()
        session.add(
            Alert(
                device_id=device.device_id,
                alert_type="RECENT_ALERT",
                severity="warning",
                message="Recent",
                created_at=base_now - timedelta(seconds=120),
            )
        )
        session.add(
            Alert(
                device_id=device.device_id,
                alert_type="OLD_ALERT",
                severity="warning",
                message="Old",
                created_at=base_now - timedelta(seconds=900),
            )
        )
        session.commit()

    request = _DisconnectAfterOneLoop()
    principal = Principal(email="admin@example.com", role="admin", source="test")
    monkeypatch.setattr(operator_tools_routes, "_utcnow", lambda: base_now)
    chunks: list[str] = []
    async for chunk in operator_tools_routes._stream_events(
        request=cast(Request, request),
        principal=principal,
        device_id="well-889",
        source_kinds=["alert"],
        event_name="",
        since_seconds=300,
    ):
        chunks.append(chunk)

    payloads = [
        json.loads(chunk.removeprefix("data: "))
        for chunk in chunks
        if chunk.startswith("data: ") and "RECENT_ALERT" in chunk
    ]
    assert len(payloads) == 1
    assert payloads[0]["event_type"] == "RECENT_ALERT"


@pytest.mark.anyio
async def test_event_stream_supports_notification_event_source_kind(tmp_path: Path, monkeypatch) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(operator_tools_routes, "db_session", db_override)
    base_now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    with session_local() as session:
        device = Device(
            device_id="well-892",
            display_name="Notify Stream Well 892",
            token_hash="hash",
            token_fingerprint="fp-well-892",
            heartbeat_interval_s=300,
            offline_after_s=900,
            enabled=True,
        )
        session.add(device)
        session.flush()
        session.add(
            NotificationEvent(
                alert_id=None,
                device_id=device.device_id,
                source_kind="alert",
                source_id=None,
                alert_type="BATTERY_LOW",
                channel="webhook",
                decision="delivered",
                delivered=True,
                reason="Recent notification",
                payload={"destination": "ops-webhook"},
                created_at=base_now - timedelta(seconds=30),
            )
        )
        session.commit()

    request = _DisconnectAfterOneLoop()
    principal = Principal(email="admin@example.com", role="admin", source="test")
    monkeypatch.setattr(operator_tools_routes, "_utcnow", lambda: base_now)
    chunks: list[str] = []
    async for chunk in operator_tools_routes._stream_events(
        request=cast(Request, request),
        principal=principal,
        device_id="well-892",
        source_kinds=["notification_event"],
        event_name="BATTERY_LOW",
        since_seconds=300,
    ):
        chunks.append(chunk)

    payloads = [
        json.loads(chunk.removeprefix("data: "))
        for chunk in chunks
        if chunk.startswith("data: ") and '"type": "notification_event"' in chunk
    ]
    assert len(payloads) == 1
    assert payloads[0]["type"] == "notification_event"
    assert payloads[0]["event_type"] == "BATTERY_LOW"
    assert payloads[0]["body"]["channel"] == "webhook"
