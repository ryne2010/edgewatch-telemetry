from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from api.app.auth.principal import Principal
from api.app.db import Base
from api.app.models import Device, DeviceAccessGrant
from api.app.services.device_access import (
    accessible_device_ids_subquery,
    ensure_device_access,
)


def _session(tmp_path: Path) -> Session:
    db_path = tmp_path / "device_access.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return maker()


def _seed_device(session: Session, *, device_id: str) -> None:
    session.add(
        Device(
            device_id=device_id,
            display_name=device_id,
            token_hash="hash",
            token_fingerprint=f"fp-{device_id}",
            heartbeat_interval_s=300,
            offline_after_s=900,
            enabled=True,
        )
    )
    session.commit()


def _seed_grant(session: Session, *, device_id: str, email: str, role: str) -> None:
    session.add(
        DeviceAccessGrant(
            device_id=device_id,
            principal_email=email,
            access_role=role,
        )
    )
    session.commit()


def test_ensure_device_access_requires_explicit_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("api.app.services.device_access.settings", SimpleNamespace(authz_enabled=True))
    principal = Principal(email="owner@example.com", role="viewer", source="test")
    session = _session(tmp_path)
    try:
        _seed_device(session, device_id="well-001")
        with pytest.raises(HTTPException) as err:
            ensure_device_access(
                session,
                principal=principal,
                device_id="well-001",
                min_access_role="viewer",
            )
        assert err.value.status_code == 403
    finally:
        session.close()


def test_ensure_device_access_allows_owner_for_operator_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("api.app.services.device_access.settings", SimpleNamespace(authz_enabled=True))
    principal = Principal(email="owner@example.com", role="viewer", source="test")
    session = _session(tmp_path)
    try:
        _seed_device(session, device_id="well-001")
        _seed_grant(session, device_id="well-001", email="owner@example.com", role="owner")
        ensure_device_access(
            session,
            principal=principal,
            device_id="well-001",
            min_access_role="operator",
        )
    finally:
        session.close()


def test_accessible_device_ids_subquery_filters_by_grant_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("api.app.services.device_access.settings", SimpleNamespace(authz_enabled=True))
    principal = Principal(email="viewer@example.com", role="viewer", source="test")
    session = _session(tmp_path)
    try:
        _seed_device(session, device_id="well-001")
        _seed_device(session, device_id="well-002")
        _seed_grant(session, device_id="well-001", email="viewer@example.com", role="viewer")
        _seed_grant(session, device_id="well-002", email="viewer@example.com", role="operator")

        viewer_ids = accessible_device_ids_subquery(
            session,
            principal=principal,
            min_access_role="viewer",
        )
        assert viewer_ids is not None
        rows = (
            session.query(Device.device_id)
            .filter(Device.device_id.in_(viewer_ids))
            .order_by(Device.device_id.asc())
            .all()
        )
        assert [row[0] for row in rows] == ["well-001", "well-002"]

        operator_ids = accessible_device_ids_subquery(
            session,
            principal=principal,
            min_access_role="operator",
        )
        assert operator_ids is not None
        rows_operator = (
            session.query(Device.device_id)
            .filter(Device.device_id.in_(operator_ids))
            .order_by(Device.device_id.asc())
            .all()
        )
        assert [row[0] for row in rows_operator] == ["well-002"]
    finally:
        session.close()
