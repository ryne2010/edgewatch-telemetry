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
from api.app.routes import admin as admin_routes
from api.app.schemas import DeploymentCreateIn, ReleaseManifestCreateIn


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


def test_admin_ota_routes_return_404_when_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _session_local, db_override = _db_override(tmp_path)
    monkeypatch.setattr(admin_routes, "db_session", db_override)
    monkeypatch.setattr(admin_routes, "settings", SimpleNamespace(enable_ota_updates=False))

    with pytest.raises(HTTPException) as err:
        admin_routes.list_release_manifests_admin()
    assert err.value.status_code == 404
