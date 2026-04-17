from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.app.auth.principal import Principal
from api.app.db import Base
from api.app.models import Device
from api.app.models import NotificationEvent
from api.app.routes import admin as admin_routes
from api.app.schemas import (
    AdminDeviceUpdate,
    DeploymentCreateIn,
    ReleaseManifestCreateIn,
    ReleaseManifestUpdateIn,
)


def _db_override(tmp_path: Path):
    db_path = tmp_path / "admin-deployments.db"
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


def _seed_devices(session_local, *, count: int) -> None:
    with session_local() as session:
        for idx in range(count):
            session.add(
                Device(
                    device_id=f"well-{idx:03d}",
                    display_name=f"Well {idx:03d}",
                    token_hash="hash",
                    token_fingerprint=f"fp-{idx:03d}",
                    heartbeat_interval_s=600,
                    offline_after_s=1800,
                    enabled=True,
                )
            )
        session.commit()


def test_admin_release_manifest_and_deployment_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(admin_routes, "db_session", db_override)
    monkeypatch.setattr(admin_routes, "settings", SimpleNamespace(enable_ota_updates=True))
    _seed_devices(session_local, count=10)

    principal = Principal(email="admin@example.com", role="admin", source="test")

    manifest = admin_routes.create_release_manifest_admin(
        ReleaseManifestCreateIn(
            git_tag="v1.2.3",
            commit_sha="a" * 40,
            artifact_uri="https://example.com/releases/v1.2.3.tar",
            artifact_size=1024,
            artifact_sha256="b" * 64,
            artifact_signature="",
            signature="sig",
            signature_key_id="key-1",
            constraints={},
            status="active",
        ),
        principal=principal,
    )
    assert manifest.git_tag == "v1.2.3"

    deployment = admin_routes.create_deployment_admin(
        DeploymentCreateIn(
            manifest_id=manifest.id,
            target_selector={"mode": "all"},
            rollout_stages_pct=[1, 10, 50, 100],
            failure_rate_threshold=0.2,
            no_quorum_timeout_s=1800,
            stage_timeout_s=1800,
            defer_rate_threshold=0.5,
            health_timeout_s=300,
            command_ttl_s=180 * 24 * 3600,
            power_guard_required=True,
            rollback_to_tag=None,
        ),
        principal=principal,
    )
    assert deployment.total_targets == 10
    assert deployment.status == "active"

    paused = admin_routes.pause_deployment_admin(deployment.id, principal=principal)
    assert paused.status == "paused"

    resumed = admin_routes.resume_deployment_admin(deployment.id, principal=principal)
    assert resumed.status == "active"

    aborted = admin_routes.abort_deployment_admin(deployment.id, reason="manual", principal=principal)
    assert aborted.status == "aborted"
    assert aborted.halt_reason == "manual"


def test_admin_can_list_deployments_with_channel_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(admin_routes, "db_session", db_override)
    monkeypatch.setattr(admin_routes, "settings", SimpleNamespace(enable_ota_updates=True))
    _seed_devices(session_local, count=4)

    principal = Principal(email="admin@example.com", role="admin", source="test")
    manifest = admin_routes.create_release_manifest_admin(
        ReleaseManifestCreateIn(
            git_tag="v2.0.0",
            commit_sha="c" * 40,
            artifact_uri="https://example.com/releases/v2.0.0.tar",
            artifact_size=2048,
            artifact_sha256="d" * 64,
            artifact_signature="",
            signature="sig",
            signature_key_id="key-2",
            constraints={},
            status="active",
        ),
        principal=principal,
    )

    channel_deployment = admin_routes.create_deployment_admin(
        DeploymentCreateIn(
            manifest_id=manifest.id,
            target_selector={"mode": "channel", "channel": "stable"},
            rollout_stages_pct=[100],
            failure_rate_threshold=0.2,
            no_quorum_timeout_s=1800,
            stage_timeout_s=1800,
            defer_rate_threshold=0.5,
            health_timeout_s=300,
            command_ttl_s=180 * 24 * 3600,
            power_guard_required=True,
            rollback_to_tag=None,
        ),
        principal=principal,
    )
    all_deployments = admin_routes.list_deployments_admin(limit=50)
    stable_deployments = admin_routes.list_deployments_admin(limit=50, selector_channel="stable")
    pilot_deployments = admin_routes.list_deployments_admin(limit=50, selector_channel="pilot")

    assert any(row.id == channel_deployment.id for row in all_deployments)
    assert [row.id for row in stable_deployments] == [channel_deployment.id]
    assert pilot_deployments == []


def test_admin_can_update_release_manifest_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(admin_routes, "db_session", db_override)
    monkeypatch.setattr(admin_routes, "settings", SimpleNamespace(enable_ota_updates=True))
    principal = Principal(email="admin@example.com", role="admin", source="test")

    manifest = admin_routes.create_release_manifest_admin(
        ReleaseManifestCreateIn(
            git_tag="v2.1.0",
            commit_sha="e" * 40,
            artifact_uri="https://example.com/releases/v2.1.0.tar",
            artifact_size=2048,
            artifact_sha256="f" * 64,
            artifact_signature="",
            signature="sig",
            signature_key_id="key-3",
            constraints={},
            status="draft",
        ),
        principal=principal,
    )

    updated = admin_routes.update_release_manifest_admin(
        manifest.id,
        ReleaseManifestUpdateIn(status="active"),
        principal=principal,
    )
    assert updated.status == "active"


def test_admin_can_page_deployment_targets_with_filters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(admin_routes, "db_session", db_override)
    monkeypatch.setattr(admin_routes, "settings", SimpleNamespace(enable_ota_updates=True))
    _seed_devices(session_local, count=3)
    principal = Principal(email="admin@example.com", role="admin", source="test")

    manifest = admin_routes.create_release_manifest_admin(
        ReleaseManifestCreateIn(
            git_tag="v2.2.0",
            commit_sha="1" * 40,
            artifact_uri="https://example.com/releases/v2.2.0.tar",
            artifact_size=2048,
            artifact_sha256="2" * 64,
            artifact_signature="",
            signature="sig",
            signature_key_id="key-4",
            constraints={},
            status="active",
        ),
        principal=principal,
    )
    deployment = admin_routes.create_deployment_admin(
        DeploymentCreateIn(
            manifest_id=manifest.id,
            target_selector={"mode": "all"},
            rollout_stages_pct=[100],
            failure_rate_threshold=0.2,
            no_quorum_timeout_s=1800,
            stage_timeout_s=1800,
            defer_rate_threshold=0.5,
            health_timeout_s=300,
            command_ttl_s=180 * 24 * 3600,
            power_guard_required=True,
            rollback_to_tag=None,
        ),
        principal=principal,
    )

    with session_local() as session:
        target = (
            session.query(admin_routes.DeploymentTarget)
            .filter(admin_routes.DeploymentTarget.deployment_id == deployment.id)
            .order_by(admin_routes.DeploymentTarget.device_id.asc())
            .first()
        )
        assert target is not None
        target.status = "failed"
        target.failure_reason = "verify_failed"
        session.commit()

    page = admin_routes.list_deployment_targets_admin(
        deployment.id,
        status_filter="failed",
        q="verify",
        limit=10,
        offset=0,
    )

    assert page.total == 1


def test_admin_can_page_notifications_with_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(admin_routes, "db_session", db_override)

    with session_local() as session:
        session.add(
            Device(
                device_id="well-notify",
                display_name="Well Notify",
                token_hash="hash",
                token_fingerprint="fp-notify",
                heartbeat_interval_s=600,
                offline_after_s=1800,
                enabled=True,
            )
        )
        session.flush()
        session.add(
            NotificationEvent(
                alert_id=None,
                device_id="well-notify",
                source_kind="alert",
                source_id="alert-1",
                alert_type="BATTERY_LOW",
                channel="webhook",
                decision="delivered",
                delivered=True,
                reason="ok",
                payload={"destination": "ops"},
            )
        )
        session.add(
            NotificationEvent(
                alert_id=None,
                device_id="well-notify",
                source_kind="alert",
                source_id="alert-2",
                alert_type="BATTERY_LOW",
                channel="webhook",
                decision="blocked",
                delivered=False,
                reason="disabled_destination",
                payload={"destination": "ops"},
            )
        )
        session.commit()

    page = admin_routes.list_notifications_page_admin(
        device_id="well-notify",
        source_kind="alert",
        channel="webhook",
        decision="blocked",
        delivered=False,
        limit=10,
        offset=0,
    )

    assert page.total == 1
    assert len(page.items) == 1
    assert page.items[0].decision == "blocked"
    assert page.items[0].delivered is False
    assert page.limit == 10
    assert page.offset == 0


def test_admin_can_page_ingestions_and_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(admin_routes, "db_session", db_override)

    with session_local() as session:
        session.add(
            Device(
                device_id="well-page",
                display_name="Well Page",
                token_hash="hash",
                token_fingerprint="fp-page",
                heartbeat_interval_s=600,
                offline_after_s=1800,
                enabled=True,
            )
        )
        session.add(
            admin_routes.IngestionBatch(
                device_id="well-page",
                contract_version="v1",
                contract_hash="hash-v1",
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
        batch = session.query(admin_routes.IngestionBatch).filter_by(device_id="well-page").one()
        session.add(
            admin_routes.DriftEvent(
                batch_id=batch.id,
                device_id="well-page",
                event_type="unknown_metric",
                action="warn",
                details={"metric": "mystery"},
            )
        )
        session.commit()

    ingestions_page = admin_routes.list_ingestions_page_admin(
        device_id="well-page",
        limit=10,
        offset=0,
    )
    drift_page = admin_routes.list_drift_events_page_admin(
        device_id="well-page",
        limit=10,
        offset=0,
    )

    assert ingestions_page.total == 1
    assert len(ingestions_page.items) == 1
    assert ingestions_page.items[0].device_id == "well-page"
    assert drift_page.total == 1
    assert len(drift_page.items) == 1
    assert drift_page.items[0].device_id == "well-page"


def test_admin_can_page_exports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(admin_routes, "db_session", db_override)

    with db_override() as session:
        session.add(
            admin_routes.ExportBatch(
                contract_version="v1",
                contract_hash="hash-v1",
                status="completed",
                row_count=42,
                gcs_uri="gs://bucket/export.ndjson",
            )
        )

    page = admin_routes.list_exports_page_admin(
        status_filter="completed",
        limit=10,
        offset=0,
    )

    assert page.total == 1
    assert len(page.items) == 1
    assert page.items[0].status == "completed"
    assert page.items[0].row_count == 42


def test_admin_events_support_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(admin_routes, "db_session", db_override)

    principal = Principal(email="admin@example.com", role="admin", source="test")
    with db_override() as session:
        admin_routes.record_admin_event(
            session,
            actor_email=principal.email,
            actor_subject=None,
            action="device.update",
            target_type="device",
            target_device_id="well-001",
            details={},
            request_id=None,
        )

    rows = admin_routes.list_admin_events(
        limit=50, action="device.update", target_type="device", device_id="well-001"
    )
    assert len(rows) == 1
    assert rows[0].action == "device.update"


def test_admin_events_page_reports_total_and_items(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(admin_routes, "db_session", db_override)

    with db_override() as session:
        admin_routes.record_admin_event(
            session,
            actor_email="admin@example.com",
            actor_subject=None,
            action="device.update",
            target_type="device",
            target_device_id="well-001",
            details={},
            request_id=None,
        )
        admin_routes.record_admin_event(
            session,
            actor_email="admin@example.com",
            actor_subject=None,
            action="device.update",
            target_type="device",
            target_device_id="well-002",
            details={},
            request_id=None,
        )

    page = admin_routes.list_admin_events_page(
        limit=1, offset=1, action="device.update", target_type="device"
    )
    assert page.total == 2
    assert page.limit == 1
    assert page.offset == 1
    assert len(page.items) == 1


def test_admin_ota_routes_return_404_when_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(admin_routes, "db_session", db_override)
    monkeypatch.setattr(admin_routes, "settings", SimpleNamespace(enable_ota_updates=False))

    with pytest.raises(HTTPException) as err:
        admin_routes.list_release_manifests_admin()
    assert err.value.status_code == 404


def test_admin_device_update_can_clear_ota_governance_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(admin_routes, "db_session", db_override)
    principal = Principal(email="admin@example.com", role="admin", source="test")

    with session_local() as session:
        session.add(
            Device(
                device_id="well-001",
                display_name="Well 001",
                token_hash="hash",
                token_fingerprint="fp-001",
                heartbeat_interval_s=600,
                offline_after_s=1800,
                enabled=True,
                ota_channel="pilot",
                ota_updates_enabled=True,
                ota_busy_reason="maintenance",
                ota_is_development=True,
                ota_locked_manifest_id="manifest-123",
            )
        )
        session.commit()

    updated = admin_routes.update_device(
        "well-001",
        AdminDeviceUpdate(
            display_name=None,
            token=None,
            heartbeat_interval_s=None,
            offline_after_s=None,
            enabled=None,
            ota_channel="stable",
            ota_updates_enabled=False,
            ota_busy_reason=None,
            ota_is_development=False,
            ota_locked_manifest_id=None,
        ),
        principal=principal,
    )

    assert updated.ota_channel == "stable"
    assert updated.ota_updates_enabled is False
    assert updated.ota_busy_reason is None
    assert updated.ota_is_development is False
    assert updated.ota_locked_manifest_id is None
