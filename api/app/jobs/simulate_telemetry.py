from __future__ import annotations

import logging
import math
import os
import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import SQLAlchemyError

from ..config import settings
from ..demo_fleet import derive_nth
from ..contracts import load_telemetry_contract
from ..db import engine, db_session
from ..edge_policy import load_edge_policy
from ..migrations import maybe_run_startup_migrations
from ..models import Device, IngestionBatch
from ..observability import configure_logging
from ..security import hash_token, token_fingerprint
from ..services.ingest_pipeline import CandidatePoint, prepare_points
from ..services.ingestion_runtime import (
    persist_points_for_batch,
    record_drift_events,
    record_quarantined_points,
    update_ingestion_batch,
)


logger = logging.getLogger("edgewatch.job.simulate_telemetry")


def _simulation_allowed_in_env(*, app_env: str, allow_in_prod: bool) -> bool:
    return app_env != "prod" or allow_in_prod


def _ensure_demo_fleet(session) -> list[str]:
    """Ensure the demo fleet exists.

    This is used by the simulator job so a fresh Cloud Run deployment can
    immediately generate synthetic telemetry without requiring a web request
    to warm the service.

    If demo bootstrap is disabled, we still return the derived device ids.
    """

    fleet_size = max(1, int(getattr(settings, "demo_fleet_size", 1) or 1))

    # Align demo defaults with edge policy contract for deterministic behavior.
    pol = load_edge_policy(settings.edge_policy_version)
    demo_heartbeat = int(pol.reporting.heartbeat_interval_s)
    demo_offline_after = max(3 * demo_heartbeat, 120)

    device_ids: list[str] = []
    for n in range(1, fleet_size + 1):
        device_id = derive_nth(settings.demo_device_id, n)
        display_name = derive_nth(settings.demo_device_name, n)
        token = derive_nth(settings.demo_device_token, n)
        device_ids.append(device_id)

        desired_fp = token_fingerprint(token)
        existing = session.query(Device).filter(Device.device_id == device_id).one_or_none()
        if existing:
            # Keep these in sync so a developer can run the edge simulator against
            # the same fleet even if the infra was recreated.
            if existing.display_name != display_name:
                existing.display_name = display_name
            if existing.token_fingerprint != desired_fp:
                existing.token_fingerprint = desired_fp
            existing.token_hash = hash_token(token)
            existing.heartbeat_interval_s = demo_heartbeat
            existing.offline_after_s = demo_offline_after
            existing.enabled = True
        else:
            session.add(
                Device(
                    device_id=device_id,
                    display_name=display_name,
                    token_hash=hash_token(token),
                    token_fingerprint=desired_fp,
                    heartbeat_interval_s=demo_heartbeat,
                    offline_after_s=demo_offline_after,
                    enabled=True,
                )
            )

    return device_ids


def _float_metric(val: float, *, jitter: float = 0.0) -> float:
    if jitter <= 0:
        return float(val)
    return float(val + random.uniform(-jitter, jitter))


def _generate_metrics(
    *, device_index: int, ts: datetime, include_legacy_metrics: bool = False
) -> dict[str, object]:
    """Generate a realistic-looking telemetry payload.

    The goal is:
    - stable-ish baselines per device
    - gentle periodic motion
    - occasional threshold crossings (to validate alerting + UI flows)
    """

    # Minute-resolution phase for periodic waves.
    t = ts.timestamp()
    phase = (t / 60.0) + device_index * 7.0

    # Pump toggles on/off in ~15 minute cycles, offset per device.
    pump_on = int((phase // 15) % 2) == 1

    microphone_level_db = 67.0 + 3.0 * math.sin(phase / 2.5)
    if device_index == 1 and int(phase) % 45 in {10, 11, 12}:
        microphone_level_db -= 12.0

    is_daylight = 6 <= ts.hour < 19
    power_source = "solar" if is_daylight else "battery"
    power_input_v = (13.6 if is_daylight else 12.4) + 0.4 * math.sin(phase / 7.0)
    if device_index == 3 and int(phase) % 90 in {0, 1, 2, 3, 4, 5}:
        power_input_v -= 1.4
    power_input_a = 0.8 + (0.7 if pump_on else 0.2) + 0.2 * math.sin(phase / 5.0)
    power_input_a = max(0.2, power_input_a)
    power_input_w = power_input_v * power_input_a
    power_input_out_of_range = power_input_v < 11.8 or power_input_v > 14.8
    power_unsustainable = power_input_w > 15.0
    power_saver_active = power_input_out_of_range or power_unsustainable

    minimal = {
        "microphone_level_db": round(_float_metric(microphone_level_db, jitter=0.3), 2),
        "power_input_v": round(_float_metric(power_input_v, jitter=0.03), 2),
        "power_input_a": round(_float_metric(power_input_a, jitter=0.01), 2),
        "power_input_w": round(_float_metric(power_input_w, jitter=0.08), 2),
        "power_source": power_source,
        "power_input_out_of_range": bool(power_input_out_of_range),
        "power_unsustainable": bool(power_unsustainable),
        "power_saver_active": bool(power_saver_active),
    }
    if not include_legacy_metrics:
        return minimal

    # Water pressure oscillates; on some devices it dips below threshold.
    base_wp = 44.0 + device_index * 1.5
    wp = base_wp + 6.0 * math.sin(phase / 3.0)
    if device_index == 2 and int(phase) % 30 in {0, 1, 2, 3}:
        wp -= 20.0

    # Oil pressure roughly tracks pump state.
    oil_p = (40.0 + 5.0 * math.sin(phase / 5.0)) if pump_on else (2.0 + math.sin(phase) * 0.2)

    # Temperature/humidity drift slowly.
    temp = 18.0 + 6.0 * math.sin(phase / 12.0)
    hum = 45.0 + 20.0 * math.sin(phase / 10.0 + 1.2)
    hum = max(0.0, min(100.0, hum))

    # Battery slowly droops with occasional recovery.
    batt = 12.4 - 0.02 * (phase % 60)
    if int(phase) % 120 in {0, 1}:
        batt += 0.4
    if device_index == 3 and int(phase) % 50 in {10, 11, 12}:
        batt -= 1.0

    # Signal fluctuates; occasional dips.
    sig = -72.0 - 8.0 * math.sin(phase / 6.0)
    if device_index == 1 and int(phase) % 40 in {20, 21, 22, 23}:
        sig -= 25.0

    # Oil level and drip level.
    oil_level = 82.0 - (phase % 300) * 0.02
    drip_level = 25.0 + 3.0 * math.sin(phase / 8.0)

    # Oil life is a sawtooth (manual reset modeled elsewhere; this is visual).
    oil_life = 100.0 - (phase % (24 * 60)) * (100.0 / (24 * 60))
    flow = (22.0 + 4.0 * math.sin(phase / 4.0)) if pump_on else 0.0

    state = "OK"
    if (
        wp < 25.0
        or batt < 11.8
        or sig < -95
        or microphone_level_db < 60.0
        or power_input_out_of_range
        or power_unsustainable
    ):
        state = "WARN"

    minimal.update(
        {
            "temperature_c": round(_float_metric(temp, jitter=0.2), 2),
            "humidity_pct": round(_float_metric(hum, jitter=0.5), 2),
            "water_pressure_psi": round(_float_metric(wp, jitter=0.3), 2),
            "oil_pressure_psi": round(_float_metric(oil_p, jitter=0.2), 2),
            "oil_level_pct": round(max(0.0, min(100.0, _float_metric(oil_level, jitter=0.2))), 2),
            "oil_life_pct": round(max(0.0, min(100.0, _float_metric(oil_life, jitter=0.1))), 2),
            "drip_oil_level_pct": round(max(0.0, min(100.0, _float_metric(drip_level, jitter=0.2))), 2),
            "battery_v": round(_float_metric(batt, jitter=0.02), 2),
            "signal_rssi_dbm": int(round(_float_metric(sig, jitter=1.0))),
            "pump_on": bool(pump_on),
            "flow_rate_gpm": round(_float_metric(flow, jitter=0.3), 2),
            "device_state": state,
        }
    )
    return minimal


def main() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    configure_logging(level=level, log_format=settings.log_format)

    if not _simulation_allowed_in_env(
        app_env=settings.app_env,
        allow_in_prod=bool(settings.simulation_allow_in_prod),
    ):
        logger.warning("simulation_disabled_in_prod")
        return

    # Allow operators to control how much data each run generates.
    points_per_device = int(os.getenv("SIMULATION_POINTS_PER_DEVICE", "1") or "1")
    points_per_device = max(1, min(points_per_device, 60))
    simulation_profile = (
        (os.getenv("SIMULATION_PROFILE", "rpi_microphone_power_v1") or "rpi_microphone_power_v1")
        .strip()
        .lower()
    )
    include_legacy_metrics = simulation_profile in {"legacy_full", "full", "all"}

    # For job runners, it's convenient to ensure schema exists.
    maybe_run_startup_migrations(engine=engine)

    contract = load_telemetry_contract(settings.telemetry_contract_version)

    now = datetime.now(timezone.utc)

    with db_session() as session:
        try:
            device_ids = _ensure_demo_fleet(session)
            session.flush()
        except SQLAlchemyError:
            logger.exception("simulation_bootstrap_failed")
            return

        # Generate points for each demo device.
        for idx, device_id in enumerate(device_ids, start=1):
            batch_id = str(uuid.uuid4())

            points: list[CandidatePoint] = []
            for i in range(points_per_device):
                ts = now - timedelta(seconds=(points_per_device - 1 - i))
                points.append(
                    CandidatePoint(
                        message_id=str(uuid.uuid4()),
                        ts=ts,
                        metrics=_generate_metrics(
                            device_index=idx,
                            ts=ts,
                            include_legacy_metrics=include_legacy_metrics,
                        ),
                    )
                )

            prepared = prepare_points(
                points=points,
                contract=contract,
                unknown_keys_mode=settings.telemetry_contract_unknown_keys_mode,
                type_mismatch_mode=settings.telemetry_contract_type_mismatch_mode,
            )

            batch = IngestionBatch(
                id=batch_id,
                device_id=device_id,
                contract_version=contract.version,
                contract_hash=contract.sha256,
                points_submitted=len(points),
                points_accepted=0,
                duplicates=0,
                points_quarantined=len(prepared.quarantined_points),
                client_ts_min=prepared.client_ts_min,
                client_ts_max=prepared.client_ts_max,
                unknown_metric_keys=prepared.unknown_metric_keys,
                type_mismatch_keys=prepared.type_mismatch_keys,
                drift_summary=prepared.drift_summary,
                source="simulation",
                pipeline_mode="simulation",
                processing_status="pending",
            )
            session.add(batch)
            session.flush()

            record_drift_events(
                session,
                batch_id=batch_id,
                device_id=device_id,
                unknown_metric_keys=prepared.unknown_metric_keys,
                type_mismatch_keys=prepared.type_mismatch_keys,
                type_mismatch_count=prepared.type_mismatch_count,
                unknown_keys_mode=settings.telemetry_contract_unknown_keys_mode,
                type_mismatch_mode=settings.telemetry_contract_type_mismatch_mode,
            )
            record_quarantined_points(
                session,
                batch_id=batch_id,
                device_id=device_id,
                points=prepared.quarantined_points,
            )

            if prepared.reject_errors:
                update_ingestion_batch(
                    session,
                    batch_id=batch_id,
                    points_accepted=0,
                    duplicates=0,
                    processing_status="rejected",
                )
                continue

            accepted, duplicates, newest_ts = persist_points_for_batch(
                session,
                batch_id=batch_id,
                device_id=device_id,
                points=prepared.accepted_points,
            )
            update_ingestion_batch(
                session,
                batch_id=batch_id,
                points_accepted=accepted,
                duplicates=duplicates,
                processing_status="completed",
            )

            logger.info(
                "simulated_telemetry",
                extra={
                    "fields": {
                        "device_id": device_id,
                        "batch_id": batch_id,
                        "accepted": accepted,
                        "duplicates": duplicates,
                        "newest_ts": newest_ts.isoformat() if newest_ts else None,
                    }
                },
            )


if __name__ == "__main__":
    main()
