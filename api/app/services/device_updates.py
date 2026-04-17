from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from ..models import (
    Deployment,
    DeploymentEvent,
    DeploymentTarget,
    Device,
    DeviceReleaseState,
    ReleaseManifest,
)
from .notifications import PlatformEvent, process_platform_event


DEPLOYMENT_STATUS_ACTIVE = "active"
DEPLOYMENT_STATUS_PAUSED = "paused"
DEPLOYMENT_STATUS_ABORTED = "aborted"
DEPLOYMENT_STATUS_HALTED = "halted"
DEPLOYMENT_STATUS_COMPLETED = "completed"

TARGET_STATUS_QUEUED = "queued"
TARGET_STATUS_DOWNLOADING = "downloading"
TARGET_STATUS_DOWNLOADED = "downloaded"
TARGET_STATUS_VERIFYING = "verifying"
TARGET_STATUS_APPLYING = "applying"
TARGET_STATUS_STAGED = "staged"
TARGET_STATUS_SWITCHING = "switching"
TARGET_STATUS_RESTARTING = "restarting"
TARGET_STATUS_HEALTHY = "healthy"
TARGET_STATUS_ROLLED_BACK = "rolled_back"
TARGET_STATUS_FAILED = "failed"
TARGET_STATUS_DEFERRED = "deferred"

TERMINAL_TARGET_STATUSES = {
    TARGET_STATUS_HEALTHY,
    TARGET_STATUS_ROLLED_BACK,
    TARGET_STATUS_FAILED,
}

PROGRESSING_TARGET_STATUSES = {
    TARGET_STATUS_QUEUED,
    TARGET_STATUS_DEFERRED,
    TARGET_STATUS_DOWNLOADING,
    TARGET_STATUS_DOWNLOADED,
    TARGET_STATUS_VERIFYING,
    TARGET_STATUS_APPLYING,
    TARGET_STATUS_STAGED,
    TARGET_STATUS_SWITCHING,
    TARGET_STATUS_RESTARTING,
}

REPORTABLE_TARGET_STATUSES = PROGRESSING_TARGET_STATUSES | TERMINAL_TARGET_STATUSES

DEFAULT_ROLLOUT_STAGES_PCT = [1, 10, 50, 100]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_rollout_stages(stages: Iterable[int] | None) -> list[int]:
    values = []
    for raw in stages or DEFAULT_ROLLOUT_STAGES_PCT:
        value = int(raw)
        if value < 1 or value > 100:
            raise ValueError("rollout stages must be in range [1, 100]")
        values.append(value)
    if not values:
        values = list(DEFAULT_ROLLOUT_STAGES_PCT)
    values = sorted(set(values))
    if values[-1] != 100:
        values.append(100)
    return values


def normalize_target_selector(selector: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(selector or {})
    mode = str(raw.get("mode") or "all").strip().lower()
    if mode not in {"all", "cohort", "labels", "explicit_ids", "channel"}:
        raise ValueError("target selector mode must be one of: all, cohort, labels, explicit_ids, channel")

    normalized: dict[str, Any] = {"mode": mode}
    cohort = raw.get("cohort")
    if cohort is not None:
        c = str(cohort).strip()
        if c:
            normalized["cohort"] = c

    channel = raw.get("channel")
    if channel is not None:
        c = str(channel).strip()
        if c:
            normalized["channel"] = c

    labels_raw = raw.get("labels")
    labels: dict[str, str] = {}
    if isinstance(labels_raw, dict):
        for k, v in labels_raw.items():
            key = str(k).strip()
            value = str(v).strip()
            if key and value:
                labels[key] = value
    if labels:
        normalized["labels"] = labels

    ids: list[str] = []
    ids_raw = raw.get("device_ids")
    if isinstance(ids_raw, list):
        for item in ids_raw:
            value = str(item).strip()
            if value:
                ids.append(value)
    if ids:
        normalized["device_ids"] = sorted(set(ids))

    if mode == "cohort" and "cohort" not in normalized:
        raise ValueError("target selector 'cohort' mode requires selector.cohort")
    if mode == "channel" and "channel" not in normalized:
        raise ValueError("target selector 'channel' mode requires selector.channel")
    if mode == "labels" and "labels" not in normalized:
        raise ValueError("target selector 'labels' mode requires selector.labels")
    if mode == "explicit_ids" and "device_ids" not in normalized:
        raise ValueError("target selector 'explicit_ids' mode requires selector.device_ids")
    return normalized


def _target_device_ids(session: Session, *, selector: dict[str, Any]) -> list[str]:
    mode = selector.get("mode", "all")
    if mode == "explicit_ids":
        ids = [str(v).strip() for v in selector.get("device_ids", [])]
        ids = [v for v in ids if v]
        if not ids:
            return []
        rows = (
            session.query(Device.device_id)
            .filter(Device.enabled.is_(True), Device.device_id.in_(ids))
            .order_by(Device.device_id.asc())
            .all()
        )
        return [str(r[0]) for r in rows]

    if mode == "cohort":
        cohort = str(selector.get("cohort") or "").strip()
        if not cohort:
            return []
        rows = (
            session.query(Device.device_id)
            .filter(Device.enabled.is_(True), Device.cohort == cohort)
            .order_by(Device.device_id.asc())
            .all()
        )
        return [str(r[0]) for r in rows]

    if mode == "channel":
        channel = str(selector.get("channel") or "").strip()
        if not channel:
            return []
        rows = (
            session.query(Device.device_id)
            .filter(
                Device.enabled.is_(True),
                Device.ota_is_development.is_(False),
                Device.ota_channel == channel,
            )
            .order_by(Device.device_id.asc())
            .all()
        )
        return [str(r[0]) for r in rows]

    if mode == "labels":
        required = selector.get("labels", {})
        if not isinstance(required, dict) or not required:
            return []
        rows = (
            session.query(Device.device_id, Device.labels)
            .filter(Device.enabled.is_(True))
            .order_by(Device.device_id.asc())
            .all()
        )
        out: list[str] = []
        for device_id, labels in rows:
            labels_map = labels if isinstance(labels, dict) else {}
            if all(str(labels_map.get(k, "")).strip() == str(v).strip() for k, v in required.items()):
                out.append(str(device_id))
        return out

    rows = (
        session.query(Device.device_id)
        .filter(Device.enabled.is_(True))
        .order_by(Device.device_id.asc())
        .all()
    )
    return [str(r[0]) for r in rows]


def _stage_threshold_counts(total_targets: int, rollout_stages_pct: list[int]) -> list[int]:
    if total_targets <= 0:
        return [0]
    counts: list[int] = []
    prior = 0
    for pct in rollout_stages_pct:
        raw = int(math.ceil((float(total_targets) * float(pct)) / 100.0))
        bounded = max(prior, min(total_targets, max(1, raw)))
        counts.append(bounded)
        prior = bounded
    if counts[-1] != total_targets:
        counts[-1] = total_targets
    return counts


def _stage_for_index(index: int, *, stage_counts: list[int]) -> int:
    for stage_idx, cutoff in enumerate(stage_counts):
        if index < cutoff:
            return stage_idx
    return len(stage_counts) - 1


def _event(
    session: Session,
    *,
    deployment_id: str,
    event_type: str,
    device_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> DeploymentEvent:
    row = DeploymentEvent(
        deployment_id=deployment_id,
        event_type=event_type,
        device_id=device_id,
        details=dict(details or {}),
    )
    session.add(row)
    process_platform_event(
        session,
        PlatformEvent(
            source_kind="deployment_event",
            source_id=None,
            device_id=device_id or "",
            event_type=event_type,
            severity="info",
            message=event_type,
            payload={"deployment_id": deployment_id, **dict(details or {})},
            created_at=row.created_at,
        ),
    )
    return row


def create_release_manifest(
    session: Session,
    *,
    git_tag: str,
    commit_sha: str,
    update_type: str = "application_bundle",
    artifact_uri: str = "",
    artifact_size: int = 1,
    artifact_sha256: str = "",
    artifact_signature: str = "",
    artifact_signature_scheme: str = "none",
    compatibility: dict[str, Any] | None = None,
    signature: str,
    signature_key_id: str,
    constraints: dict[str, Any] | None,
    created_by: str,
    status: str = "active",
) -> ReleaseManifest:
    normalized_update_type = (update_type or "application_bundle").strip().lower()
    if normalized_update_type not in {"application_bundle", "asset_bundle", "system_image"}:
        raise ValueError("update_type must be one of: application_bundle, asset_bundle, system_image")
    normalized_sig_scheme = (artifact_signature_scheme or "none").strip().lower()
    if normalized_sig_scheme not in {"none", "openssl_rsa_sha256"}:
        raise ValueError("artifact_signature_scheme must be one of: none, openssl_rsa_sha256")
    normalized_artifact_uri = artifact_uri.strip() or f"memory://{git_tag.strip()}"
    normalized_artifact_sha256 = artifact_sha256.strip().lower() or ("0" * 64)
    if len(normalized_artifact_sha256) != 64:
        raise ValueError("artifact_sha256 must be a 64-character hex digest")
    row = ReleaseManifest(
        git_tag=git_tag.strip(),
        commit_sha=commit_sha.strip(),
        update_type=normalized_update_type,
        artifact_uri=normalized_artifact_uri,
        artifact_size=max(1, int(artifact_size)),
        artifact_sha256=normalized_artifact_sha256,
        artifact_signature=artifact_signature.strip(),
        artifact_signature_scheme=normalized_sig_scheme,
        compatibility=dict(compatibility or {}),
        signature=signature.strip(),
        signature_key_id=signature_key_id.strip(),
        constraints=dict(constraints or {}),
        created_by=created_by.strip(),
        status=(status or "active").strip().lower() or "active",
    )
    session.add(row)
    session.flush()
    return row


def list_release_manifests(
    session: Session,
    *,
    limit: int = 200,
    status: str | None = None,
) -> list[ReleaseManifest]:
    q = session.query(ReleaseManifest)
    if status:
        q = q.filter(ReleaseManifest.status == status)
    return q.order_by(ReleaseManifest.created_at.desc()).limit(max(1, min(limit, 2000))).all()


def create_deployment(
    session: Session,
    *,
    manifest: ReleaseManifest,
    created_by: str,
    target_selector: dict[str, Any],
    rollout_stages_pct: list[int] | None,
    failure_rate_threshold: float,
    no_quorum_timeout_s: int,
    stage_timeout_s: int | None = None,
    defer_rate_threshold: float = 0.5,
    health_timeout_s: int,
    command_ttl_s: int,
    power_guard_required: bool,
    rollback_to_tag: str | None,
) -> Deployment:
    selector = normalize_target_selector(target_selector)
    stages = normalize_rollout_stages(rollout_stages_pct)
    target_ids = _target_device_ids(session, selector=selector)
    if not target_ids:
        raise ValueError("deployment target selector matched no enabled devices")

    ts = utcnow()
    command_expires_at = ts + timedelta(seconds=max(60, int(command_ttl_s)))
    deployment = Deployment(
        manifest_id=manifest.id,
        strategy={"rollout_stages_pct": stages},
        stage=0,
        status=DEPLOYMENT_STATUS_ACTIVE,
        halt_reason=None,
        created_by=created_by.strip(),
        created_at=ts,
        updated_at=ts,
        failure_rate_threshold=float(failure_rate_threshold),
        no_quorum_timeout_s=int(no_quorum_timeout_s),
        stage_timeout_s=int(stage_timeout_s if stage_timeout_s is not None else no_quorum_timeout_s),
        defer_rate_threshold=float(defer_rate_threshold),
        command_expires_at=command_expires_at,
        power_guard_required=bool(power_guard_required),
        health_timeout_s=int(health_timeout_s),
        rollback_to_tag=(rollback_to_tag.strip() if rollback_to_tag else None),
        target_selector=selector,
    )
    session.add(deployment)
    session.flush()

    stage_counts = _stage_threshold_counts(len(target_ids), stages)
    for idx, device_id in enumerate(target_ids):
        session.add(
            DeploymentTarget(
                deployment_id=deployment.id,
                device_id=device_id,
                stage_assigned=_stage_for_index(idx, stage_counts=stage_counts),
                status=TARGET_STATUS_QUEUED,
            )
        )
    session.flush()

    _event(
        session,
        deployment_id=deployment.id,
        event_type="deployment.created",
        details={
            "manifest_id": manifest.id,
            "target_count": len(target_ids),
            "rollout_stages_pct": stages,
            "target_selector": selector,
        },
    )
    return deployment


def _set_deployment_status(
    session: Session,
    *,
    deployment: Deployment,
    status: str,
    reason: str | None,
    event_type: str,
) -> Deployment:
    deployment.status = status
    deployment.halt_reason = reason
    deployment.updated_at = utcnow()
    _event(
        session,
        deployment_id=deployment.id,
        event_type=event_type,
        details={"status": status, "reason": reason},
    )
    return deployment


def pause_deployment(session: Session, *, deployment: Deployment) -> Deployment:
    if deployment.status != DEPLOYMENT_STATUS_ACTIVE:
        raise ValueError("deployment is not active")
    return _set_deployment_status(
        session,
        deployment=deployment,
        status=DEPLOYMENT_STATUS_PAUSED,
        reason=deployment.halt_reason,
        event_type="deployment.paused",
    )


def resume_deployment(session: Session, *, deployment: Deployment) -> Deployment:
    if deployment.status != DEPLOYMENT_STATUS_PAUSED:
        raise ValueError("deployment is not paused")
    return _set_deployment_status(
        session,
        deployment=deployment,
        status=DEPLOYMENT_STATUS_ACTIVE,
        reason=None,
        event_type="deployment.resumed",
    )


def abort_deployment(session: Session, *, deployment: Deployment, reason: str | None) -> Deployment:
    if deployment.status in {DEPLOYMENT_STATUS_ABORTED, DEPLOYMENT_STATUS_COMPLETED}:
        raise ValueError("deployment is already terminal")
    message = (reason or "").strip() or "aborted by operator"
    return _set_deployment_status(
        session,
        deployment=deployment,
        status=DEPLOYMENT_STATUS_ABORTED,
        reason=message,
        event_type="deployment.aborted",
    )


def deployment_counts(session: Session, *, deployment_id: str) -> dict[str, int]:
    rows = (
        session.query(DeploymentTarget.status).filter(DeploymentTarget.deployment_id == deployment_id).all()
    )
    counts = {
        "total_targets": 0,
        "queued_targets": 0,
        "in_progress_targets": 0,
        "deferred_targets": 0,
        "healthy_targets": 0,
        "failed_targets": 0,
        "rolled_back_targets": 0,
    }
    for (status,) in rows:
        counts["total_targets"] += 1
        if status == TARGET_STATUS_QUEUED:
            counts["queued_targets"] += 1
        elif status in {
            TARGET_STATUS_DOWNLOADING,
            TARGET_STATUS_DOWNLOADED,
            TARGET_STATUS_VERIFYING,
            TARGET_STATUS_APPLYING,
            TARGET_STATUS_STAGED,
            TARGET_STATUS_SWITCHING,
            TARGET_STATUS_RESTARTING,
        }:
            counts["in_progress_targets"] += 1
        elif status == TARGET_STATUS_DEFERRED:
            counts["deferred_targets"] += 1
        elif status == TARGET_STATUS_HEALTHY:
            counts["healthy_targets"] += 1
        elif status == TARGET_STATUS_FAILED:
            counts["failed_targets"] += 1
        elif status == TARGET_STATUS_ROLLED_BACK:
            counts["rolled_back_targets"] += 1
    return counts


def _evaluate_rollout_progress(session: Session, *, deployment: Deployment) -> None:
    if deployment.status != DEPLOYMENT_STATUS_ACTIVE:
        return
    now = utcnow()
    strategy = deployment.strategy if isinstance(deployment.strategy, dict) else {}
    stages = normalize_rollout_stages(strategy.get("rollout_stages_pct"))
    current_stage = max(0, int(deployment.stage))
    stage_targets = (
        session.query(DeploymentTarget)
        .filter(
            DeploymentTarget.deployment_id == deployment.id,
            DeploymentTarget.stage_assigned <= current_stage,
        )
        .all()
    )
    if not stage_targets:
        return
    deferred = [row for row in stage_targets if row.status == TARGET_STATUS_DEFERRED]
    defer_rate = float(len(deferred)) / float(len(stage_targets))
    if defer_rate > float(getattr(deployment, "defer_rate_threshold", 0.5)):
        deployment.status = DEPLOYMENT_STATUS_HALTED
        deployment.halt_reason = "defer_rate_exceeded %.3f > %.3f" % (
            defer_rate,
            float(getattr(deployment, "defer_rate_threshold", 0.5)),
        )
        deployment.updated_at = now
        _event(
            session,
            deployment_id=deployment.id,
            event_type="deployment.halted",
            details={
                "defer_rate": defer_rate,
                "threshold": float(getattr(deployment, "defer_rate_threshold", 0.5)),
                "stage": current_stage,
            },
        )
        return
    observed = [row for row in stage_targets if row.status in TERMINAL_TARGET_STATUSES]
    failures = [row for row in observed if row.status in {TARGET_STATUS_FAILED, TARGET_STATUS_ROLLED_BACK}]

    if observed:
        failure_rate = float(len(failures)) / float(len(observed))
        if failure_rate > float(deployment.failure_rate_threshold):
            deployment.status = DEPLOYMENT_STATUS_HALTED
            deployment.halt_reason = "failure_rate_exceeded %.3f > %.3f" % (
                failure_rate,
                deployment.failure_rate_threshold,
            )
            deployment.updated_at = now
            _event(
                session,
                deployment_id=deployment.id,
                event_type="deployment.halted",
                details={
                    "failure_rate": failure_rate,
                    "threshold": float(deployment.failure_rate_threshold),
                    "stage": current_stage,
                },
            )
            return

    if not observed and (now - deployment.updated_at).total_seconds() > float(
        max(60, int(getattr(deployment, "no_quorum_timeout_s", 1800)))
    ):
        deployment.status = DEPLOYMENT_STATUS_HALTED
        deployment.halt_reason = "no_quorum_timeout_exceeded"
        deployment.updated_at = now
        _event(
            session,
            deployment_id=deployment.id,
            event_type="deployment.halted",
            details={"reason": "no_quorum_timeout_exceeded", "stage": current_stage},
        )
        return

    if (
        observed
        and len(observed) != len(stage_targets)
        and (now - deployment.updated_at).total_seconds()
        > float(
            max(
                60,
                int(getattr(deployment, "stage_timeout_s", getattr(deployment, "no_quorum_timeout_s", 1800))),
            )
        )
    ):
        deployment.status = DEPLOYMENT_STATUS_HALTED
        deployment.halt_reason = "stage_timeout_exceeded"
        deployment.updated_at = now
        _event(
            session,
            deployment_id=deployment.id,
            event_type="deployment.halted",
            details={"reason": "stage_timeout_exceeded", "stage": current_stage},
        )
        return

    if len(observed) != len(stage_targets):
        return

    if current_stage + 1 < len(stages):
        deployment.stage = current_stage + 1
        deployment.updated_at = now
        _event(
            session,
            deployment_id=deployment.id,
            event_type="deployment.stage_advanced",
            details={
                "stage": int(deployment.stage),
                "rollout_stages_pct": stages,
            },
        )
        return

    deployment.status = DEPLOYMENT_STATUS_COMPLETED
    deployment.halt_reason = None
    deployment.updated_at = now
    _event(
        session,
        deployment_id=deployment.id,
        event_type="deployment.completed",
        details={"stage": current_stage},
    )


def get_deployment(session: Session, *, deployment_id: str) -> Deployment | None:
    return (
        session.query(Deployment)
        .options(joinedload(Deployment.manifest))
        .filter(Deployment.id == deployment_id)
        .one_or_none()
    )


def list_deployments(
    session: Session,
    *,
    limit: int = 200,
    status: str | None = None,
    manifest_id: str | None = None,
    selector_channel: str | None = None,
) -> list[Deployment]:
    q = session.query(Deployment).options(joinedload(Deployment.manifest))
    if status:
        q = q.filter(Deployment.status == status)
    if manifest_id:
        q = q.filter(Deployment.manifest_id == manifest_id)
    rows = q.order_by(Deployment.created_at.desc()).limit(max(1, min(limit, 2000))).all()
    if selector_channel:
        channel = selector_channel.strip()
        if not channel:
            return rows
        return [
            row
            for row in rows
            if isinstance(row.target_selector, dict)
            and str(row.target_selector.get("mode") or "").strip().lower() == "channel"
            and str(row.target_selector.get("channel") or "").strip() == channel
        ]
    return rows


def list_deployment_events(
    session: Session, *, deployment_id: str, limit: int = 500
) -> list[DeploymentEvent]:
    return (
        session.query(DeploymentEvent)
        .filter(DeploymentEvent.deployment_id == deployment_id)
        .order_by(DeploymentEvent.created_at.desc())
        .limit(max(1, min(limit, 5000)))
        .all()
    )


def list_deployment_targets(
    session: Session,
    *,
    deployment_id: str,
    status: str | None = None,
    search: str | None = None,
    limit: int = 5000,
    offset: int = 0,
) -> tuple[list[DeploymentTarget], int]:
    q = session.query(DeploymentTarget).filter(DeploymentTarget.deployment_id == deployment_id)
    if status:
        q = q.filter(DeploymentTarget.status == status)
    if search:
        pattern = f"%{search.strip()}%"
        q = q.filter(
            (DeploymentTarget.device_id.ilike(pattern))
            | (DeploymentTarget.failure_reason.ilike(pattern))
            | (DeploymentTarget.status.ilike(pattern))
        )
    total = int(q.with_entities(func.count()).scalar() or 0)
    rows = (
        q.order_by(DeploymentTarget.device_id.asc())
        .offset(max(0, int(offset)))
        .limit(max(1, min(limit, 20_000)))
        .all()
    )
    return rows, total


def get_pending_update_command(
    session: Session,
    *,
    device_id: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    ts = now or utcnow()
    device = session.query(Device).filter(Device.device_id == device_id).one_or_none()
    if device is None:
        return None
    if bool(getattr(device, "ota_is_development", False)):
        return None
    row = (
        session.query(DeploymentTarget, Deployment, ReleaseManifest)
        .join(Deployment, Deployment.id == DeploymentTarget.deployment_id)
        .join(ReleaseManifest, ReleaseManifest.id == Deployment.manifest_id)
        .filter(
            DeploymentTarget.device_id == device_id,
            Deployment.status == DEPLOYMENT_STATUS_ACTIVE,
            Deployment.command_expires_at > ts,
            DeploymentTarget.stage_assigned <= Deployment.stage,
            DeploymentTarget.status.in_(tuple(PROGRESSING_TARGET_STATUSES)),
            ReleaseManifest.status == "active",
        )
        .order_by(Deployment.updated_at.desc(), Deployment.created_at.desc())
        .first()
    )
    if row is None:
        return None
    target, deployment, manifest = row
    locked_manifest_id = str(getattr(device, "ota_locked_manifest_id", "") or "").strip() or None
    if locked_manifest_id is not None and manifest.id != locked_manifest_id:
        return None
    return {
        "deployment_id": deployment.id,
        "manifest_id": manifest.id,
        "git_tag": manifest.git_tag,
        "commit_sha": manifest.commit_sha,
        "update_type": manifest.update_type,
        "artifact_uri": manifest.artifact_uri,
        "artifact_size": int(manifest.artifact_size),
        "artifact_sha256": manifest.artifact_sha256,
        "artifact_signature": manifest.artifact_signature,
        "artifact_signature_scheme": manifest.artifact_signature_scheme,
        "compatibility": dict(manifest.compatibility or {}),
        "issued_at": deployment.updated_at,
        "expires_at": deployment.command_expires_at,
        "signature": manifest.signature,
        "signature_key_id": manifest.signature_key_id,
        "rollback_to_tag": deployment.rollback_to_tag,
        "health_timeout_s": deployment.health_timeout_s,
        "power_guard_required": deployment.power_guard_required,
        "target_status": target.status,
        "updates_enabled": bool(getattr(device, "ota_updates_enabled", True)),
        "busy_reason": getattr(device, "ota_busy_reason", None),
    }


def update_command_etag_fragment(
    session: Session,
    *,
    device_id: str,
    now: datetime | None = None,
) -> str:
    pending = get_pending_update_command(session, device_id=device_id, now=now)
    if pending is None:
        return "none"
    return (
        f"{pending['deployment_id']}:"
        f"{pending['manifest_id']}:"
        f"{pending['git_tag']}:"
        f"{pending['commit_sha']}:"
        f"{pending['artifact_sha256']}:"
        f"{pending['expires_at'].isoformat()}"
    )


def _device_release_state(session: Session, *, device_id: str, now: datetime) -> DeviceReleaseState:
    row = session.query(DeviceReleaseState).filter(DeviceReleaseState.device_id == device_id).one_or_none()
    if row is None:
        row = DeviceReleaseState(device_id=device_id, updated_at=now)
        session.add(row)
        session.flush()
    return row


def report_device_update(
    session: Session,
    *,
    deployment_id: str,
    device_id: str,
    state: str,
    reason_code: str | None = None,
    reason_detail: str | None = None,
    now: datetime | None = None,
) -> tuple[Deployment, DeploymentTarget]:
    normalized_state = (state or "").strip().lower()
    if normalized_state not in REPORTABLE_TARGET_STATUSES:
        raise ValueError(f"unsupported update state: {state!r}")
    ts = now or utcnow()

    row = (
        session.query(DeploymentTarget, Deployment, ReleaseManifest)
        .join(Deployment, Deployment.id == DeploymentTarget.deployment_id)
        .join(ReleaseManifest, ReleaseManifest.id == Deployment.manifest_id)
        .filter(
            DeploymentTarget.deployment_id == deployment_id,
            DeploymentTarget.device_id == device_id,
        )
        .first()
    )
    if row is None:
        raise LookupError("deployment target not found")

    target, deployment, manifest = row
    if (
        deployment.status in {DEPLOYMENT_STATUS_ABORTED, DEPLOYMENT_STATUS_COMPLETED}
        and normalized_state in PROGRESSING_TARGET_STATUSES
    ):
        raise ValueError(f"deployment status {deployment.status!r} does not accept progressing reports")

    target.status = normalized_state
    target.last_report_at = ts
    details = dict(target.report_details or {})
    if reason_code:
        details["reason_code"] = reason_code.strip()
    if reason_detail:
        details["reason_detail"] = reason_detail.strip()
    target.report_details = details
    if normalized_state in {TARGET_STATUS_FAILED, TARGET_STATUS_ROLLED_BACK}:
        target.failure_reason = (reason_code or reason_detail or normalized_state).strip()
    elif normalized_state in {TARGET_STATUS_HEALTHY, TARGET_STATUS_DEFERRED}:
        target.failure_reason = None

    deployment.updated_at = ts
    _event(
        session,
        deployment_id=deployment.id,
        event_type=f"device.report.{normalized_state}",
        device_id=device_id,
        details={
            "reason_code": reason_code,
            "reason_detail": reason_detail,
            "target_stage_assigned": int(target.stage_assigned),
        },
    )

    release_state = _device_release_state(session, device_id=device_id, now=ts)
    if normalized_state == TARGET_STATUS_HEALTHY:
        release_state.current_tag = manifest.git_tag
        release_state.current_commit = manifest.commit_sha
        release_state.current_manifest_id = manifest.id
        release_state.current_artifact_sha256 = manifest.artifact_sha256
        release_state.pending_manifest_id = None
        release_state.pending_artifact_sha256 = None
        release_state.last_healthy_at = ts
        release_state.last_deployment_id = deployment.id
        release_state.updated_at = ts
    elif normalized_state == TARGET_STATUS_FAILED:
        release_state.last_failed_tag = manifest.git_tag
        release_state.last_failed_manifest_id = manifest.id
        release_state.rollback_tag = deployment.rollback_to_tag
        release_state.last_deployment_id = deployment.id
        release_state.updated_at = ts
    elif normalized_state in {
        TARGET_STATUS_DOWNLOADING,
        TARGET_STATUS_DOWNLOADED,
        TARGET_STATUS_VERIFYING,
        TARGET_STATUS_APPLYING,
        TARGET_STATUS_STAGED,
        TARGET_STATUS_SWITCHING,
        TARGET_STATUS_RESTARTING,
    }:
        release_state.pending_manifest_id = manifest.id
        release_state.pending_artifact_sha256 = manifest.artifact_sha256
        release_state.last_deployment_id = deployment.id
        release_state.updated_at = ts
    elif normalized_state == TARGET_STATUS_ROLLED_BACK:
        if deployment.rollback_to_tag:
            release_state.current_tag = deployment.rollback_to_tag
        release_state.pending_manifest_id = None
        release_state.pending_artifact_sha256 = None
        release_state.last_deployment_id = deployment.id
        release_state.updated_at = ts

    _evaluate_rollout_progress(session, deployment=deployment)
    return deployment, target
