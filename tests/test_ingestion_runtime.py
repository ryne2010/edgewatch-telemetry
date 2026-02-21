from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from api.app.db import Base
from api.app.models import Device, IngestionBatch, TelemetryIngestDedupe, TelemetryPoint
from api.app.services.ingest_pipeline import CandidatePoint
from api.app.services.ingestion_runtime import persist_points_for_batch


def _session(tmp_path: Path) -> Session:
    db_path = tmp_path / "ingestion_runtime.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return maker()


def _seed_device(session: Session) -> None:
    session.add(
        Device(
            device_id="demo-well-001",
            display_name="Demo",
            token_hash="hash",
            token_fingerprint="fingerprint",
            heartbeat_interval_s=300,
            offline_after_s=900,
            enabled=True,
        )
    )
    session.commit()


def _seed_batch(session: Session, *, batch_id: str, points_submitted: int) -> None:
    session.add(
        IngestionBatch(
            id=batch_id,
            device_id="demo-well-001",
            contract_version="v1",
            contract_hash="abc123",
            points_submitted=points_submitted,
            points_accepted=0,
            duplicates=0,
            points_quarantined=0,
            unknown_metric_keys=[],
            type_mismatch_keys=[],
            drift_summary={},
            source="device",
            pipeline_mode="direct",
            processing_status="pending",
        )
    )
    session.commit()


def test_persist_points_uses_dedupe_registry(tmp_path: Path) -> None:
    session = _session(tmp_path)
    try:
        _seed_device(session)
        _seed_batch(session, batch_id="batch-1", points_submitted=3)

        points = [
            CandidatePoint(
                message_id="m-1",
                ts=datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc),
                metrics={"custom_metric": 1.0},
            ),
            CandidatePoint(
                message_id="m-2",
                ts=datetime(2026, 2, 21, 12, 1, tzinfo=timezone.utc),
                metrics={"custom_metric": 2.0},
            ),
            CandidatePoint(
                message_id="m-1",
                ts=datetime(2026, 2, 21, 12, 2, tzinfo=timezone.utc),
                metrics={"custom_metric": 9.0},
            ),
        ]

        accepted, duplicates, newest_ts = persist_points_for_batch(
            session,
            batch_id="batch-1",
            device_id="demo-well-001",
            points=points,
        )
        session.commit()

        assert accepted == 2
        assert duplicates == 1
        assert newest_ts == datetime(2026, 2, 21, 12, 1, tzinfo=timezone.utc)
        assert session.query(TelemetryPoint).count() == 2
        assert session.query(TelemetryIngestDedupe).count() == 2

        _seed_batch(session, batch_id="batch-2", points_submitted=2)
        second_points = [
            CandidatePoint(
                message_id="m-1",
                ts=datetime(2026, 2, 21, 12, 3, tzinfo=timezone.utc),
                metrics={"custom_metric": 7.0},
            ),
            CandidatePoint(
                message_id="m-3",
                ts=datetime(2026, 2, 21, 12, 4, tzinfo=timezone.utc),
                metrics={"custom_metric": 3.0},
            ),
        ]

        accepted2, duplicates2, newest_ts2 = persist_points_for_batch(
            session,
            batch_id="batch-2",
            device_id="demo-well-001",
            points=second_points,
        )
        session.commit()

        assert accepted2 == 1
        assert duplicates2 == 1
        assert newest_ts2 == datetime(2026, 2, 21, 12, 4, tzinfo=timezone.utc)
        assert session.query(TelemetryPoint).count() == 3
        assert session.query(TelemetryIngestDedupe).count() == 3
    finally:
        session.close()
