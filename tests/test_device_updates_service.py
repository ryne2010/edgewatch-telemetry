from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.app.db import Base
from api.app.models import DeploymentTarget, Device
from api.app.services import device_updates


def _setup_db(tmp_path: Path):
    db_path = tmp_path / "device-updates-service.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


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


def test_create_deployment_and_pending_update_command_selection(tmp_path: Path) -> None:
    session_local = _setup_db(tmp_path)
    _seed_devices(session_local, count=20)

    with session_local() as session:
        manifest = device_updates.create_release_manifest(
            session,
            git_tag="v1.2.3",
            commit_sha="a" * 40,
            signature="sig",
            signature_key_id="key-1",
            constraints={},
            created_by="admin@example.com",
        )
        deployment = device_updates.create_deployment(
            session,
            manifest=manifest,
            created_by="admin@example.com",
            target_selector={"mode": "all"},
            rollout_stages_pct=[1, 10, 50, 100],
            failure_rate_threshold=0.2,
            no_quorum_timeout_s=1800,
            health_timeout_s=300,
            command_ttl_s=180 * 24 * 3600,
            power_guard_required=True,
            rollback_to_tag="v1.2.2",
        )
        session.commit()

        counts = device_updates.deployment_counts(session, deployment_id=deployment.id)
        assert counts["total_targets"] == 20
        assert counts["queued_targets"] == 20

        first_target = (
            session.query(DeploymentTarget)
            .filter(DeploymentTarget.deployment_id == deployment.id)
            .order_by(DeploymentTarget.device_id.asc())
            .first()
        )
        assert first_target is not None
        assert first_target.stage_assigned == 0

        pending_first = device_updates.get_pending_update_command(
            session,
            device_id=first_target.device_id,
        )
        assert pending_first is not None
        assert pending_first["git_tag"] == "v1.2.3"
        assert pending_first["rollback_to_tag"] == "v1.2.2"

        last_target = (
            session.query(DeploymentTarget)
            .filter(DeploymentTarget.deployment_id == deployment.id)
            .order_by(DeploymentTarget.device_id.desc())
            .first()
        )
        assert last_target is not None
        assert last_target.stage_assigned > 0
        pending_last = device_updates.get_pending_update_command(
            session,
            device_id=last_target.device_id,
        )
        assert pending_last is None


def test_report_device_update_advances_stage_and_halts_on_failure_threshold(tmp_path: Path) -> None:
    session_local = _setup_db(tmp_path)
    _seed_devices(session_local, count=20)

    with session_local() as session:
        manifest = device_updates.create_release_manifest(
            session,
            git_tag="v2.0.0",
            commit_sha="b" * 40,
            signature="sig",
            signature_key_id="key-2",
            constraints={},
            created_by="admin@example.com",
        )
        deployment = device_updates.create_deployment(
            session,
            manifest=manifest,
            created_by="admin@example.com",
            target_selector={"mode": "all"},
            rollout_stages_pct=[1, 10, 50, 100],
            failure_rate_threshold=0.0,
            no_quorum_timeout_s=1800,
            health_timeout_s=300,
            command_ttl_s=180 * 24 * 3600,
            power_guard_required=True,
            rollback_to_tag=None,
        )
        session.commit()

        stage_zero_target = (
            session.query(DeploymentTarget)
            .filter(
                DeploymentTarget.deployment_id == deployment.id,
                DeploymentTarget.stage_assigned == 0,
            )
            .order_by(DeploymentTarget.device_id.asc())
            .first()
        )
        assert stage_zero_target is not None

        updated_deployment, _ = device_updates.report_device_update(
            session,
            deployment_id=deployment.id,
            device_id=stage_zero_target.device_id,
            state="healthy",
        )
        assert updated_deployment.stage >= 1

        stage_one_target = (
            session.query(DeploymentTarget)
            .filter(
                DeploymentTarget.deployment_id == deployment.id,
                DeploymentTarget.stage_assigned <= updated_deployment.stage,
                DeploymentTarget.device_id != stage_zero_target.device_id,
            )
            .order_by(DeploymentTarget.device_id.asc())
            .first()
        )
        assert stage_one_target is not None
        updated_deployment, _ = device_updates.report_device_update(
            session,
            deployment_id=deployment.id,
            device_id=stage_one_target.device_id,
            state="failed",
            reason_code="health_check_failed",
            reason_detail="policy fetch timeout",
        )
        assert updated_deployment.status == device_updates.DEPLOYMENT_STATUS_HALTED
        assert "failure_rate_exceeded" in (updated_deployment.halt_reason or "")
        session.commit()

        events = device_updates.list_deployment_events(session, deployment_id=deployment.id, limit=50)
        assert any(evt.event_type == "deployment.halted" for evt in events)
        assert any(evt.event_type == "device.report.failed" for evt in events)
