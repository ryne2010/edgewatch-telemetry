from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.app.db import Base
from api.app.models import Deployment, DeploymentTarget, Device, ReleaseManifest
from api.app.routes import device_updates as device_updates_routes
from api.app.schemas import DeviceUpdateReportIn


def _db_override(tmp_path: Path):
    db_path = tmp_path / "device-updates-routes.db"
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


def _seed_deployment(session_local, *, device_id: str, deployment_id: str = "dep-1") -> Device:
    with session_local() as session:
        device = Device(
            device_id=device_id,
            display_name=device_id,
            token_hash="hash",
            token_fingerprint=f"fp-{device_id}",
            heartbeat_interval_s=600,
            offline_after_s=1800,
            enabled=True,
        )
        session.add(device)
        session.flush()
        manifest = ReleaseManifest(
            git_tag="v1.2.3",
            commit_sha="a" * 40,
            update_type="application_bundle",
            artifact_uri="https://example.com/releases/v1.2.3.tar",
            artifact_size=1024,
            artifact_sha256="b" * 64,
            artifact_signature="",
            artifact_signature_scheme="none",
            compatibility={},
            signature="sig",
            signature_key_id="key-1",
            constraints={},
            created_by="admin@example.com",
            status="active",
        )
        session.add(manifest)
        session.flush()
        deployment = Deployment(
            id=deployment_id,
            manifest_id=manifest.id,
            strategy={"rollout_stages_pct": [1, 10, 50, 100]},
            stage=0,
            status="active",
            created_by="admin@example.com",
            failure_rate_threshold=0.2,
            no_quorum_timeout_s=1800,
            stage_timeout_s=1800,
            defer_rate_threshold=0.5,
            command_expires_at=datetime.now(timezone.utc) + timedelta(days=10),
            power_guard_required=True,
            health_timeout_s=300,
            target_selector={"mode": "all"},
        )
        session.add(deployment)
        session.flush()
        session.add(
            DeploymentTarget(
                deployment_id=deployment.id,
                device_id=device_id,
                stage_assigned=0,
                status="queued",
            )
        )
        session.commit()
        session.refresh(device)
        return device


def test_device_update_report_route_updates_target_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(device_updates_routes, "db_session", db_override)
    device = _seed_deployment(session_local, device_id="well-001")

    out = device_updates_routes.report_update_state(
        deployment_id="dep-1",
        req=DeviceUpdateReportIn(state="downloading", reason_code=None, reason_detail=None),
        device=device,
    )
    assert out.deployment_id == "dep-1"
    assert out.device_id == "well-001"
    assert out.status == "downloading"
    assert out.deployment_status == "active"


def test_device_update_report_route_returns_404_for_unknown_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(device_updates_routes, "db_session", db_override)
    device = _seed_deployment(session_local, device_id="well-002")

    with pytest.raises(HTTPException) as err:
        device_updates_routes.report_update_state(
            deployment_id="dep-missing",
            req=DeviceUpdateReportIn(state="failed", reason_code="x", reason_detail="y"),
            device=device,
        )
    assert err.value.status_code == 404
