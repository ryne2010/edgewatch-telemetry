from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Mapping

EquipmentState = Literal["running", "stopped", "fault", "unknown"]
_CLASSIFIED_STATES: tuple[EquipmentState, ...] = ("fault", "running", "stopped")
_ALL_STATES: tuple[EquipmentState, ...] = (*_CLASSIFIED_STATES, "unknown")


@dataclass(frozen=True)
class FusionPolicy:
    minimum_state_confidence: float = 0.80
    minimum_state_margin: float = 0.15
    fault_audio_threshold: float = 0.85
    fault_visual_threshold: float = 0.85

    def __post_init__(self) -> None:
        for field_name in (
            "minimum_state_confidence",
            "minimum_state_margin",
            "fault_audio_threshold",
            "fault_visual_threshold",
        ):
            value = float(getattr(self, field_name))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be within 0..1")


@dataclass(frozen=True)
class InferenceOutput:
    equipment_state: EquipmentState
    state_confidence: float
    audio_anomaly_score: float
    visual_change: float
    model_version: str

    def as_scalars(self) -> dict[str, str | float]:
        return {
            "equipment_state": self.equipment_state,
            "state_confidence": self.state_confidence,
            "audio_anomaly_score": self.audio_anomaly_score,
            "visual_change": self.visual_change,
            "model_version": self.model_version,
        }


@dataclass(frozen=True)
class PromotionEvidence:
    held_out_alert_precision: float
    false_alert_count: int
    device_days: float

    @property
    def false_alerts_per_device_day(self) -> float:
        if self.device_days <= 0:
            return math.inf
        return self.false_alert_count / self.device_days


@dataclass(frozen=True)
class AlertDecision:
    eligible: bool
    reason: str
    repeated_observations: int


@dataclass(frozen=True)
class AlertGateSnapshot:
    candidate: EquipmentState | None
    observations: int


def _validated_score(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{field} must be within 0..1")
    return normalized


def fuse_equipment_state(
    *,
    vision_scores: Mapping[str, float],
    audio_anomaly_score: float,
    visual_change: float,
    model_version: str,
    policy: FusionPolicy | None = None,
) -> InferenceOutput:
    """Fuse vision/audio deterministically and fail ambiguous inputs to unknown."""

    if not model_version.strip():
        raise ValueError("model_version must be non-empty")
    selected_policy = policy or FusionPolicy()
    audio = _validated_score(audio_anomaly_score, field="audio_anomaly_score")
    visual = _validated_score(visual_change, field="visual_change")

    missing: set[str] = {str(item) for item in _ALL_STATES if item not in vision_scores}
    unknown: set[str] = set(vision_scores).difference(_ALL_STATES)
    if missing:
        raise ValueError(f"vision scores are missing: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"vision scores contain unknown labels: {', '.join(sorted(unknown))}")
    scores: dict[EquipmentState, float] = {
        state: _validated_score(vision_scores.get(state, 0.0), field=f"vision_scores.{state}")
        for state in _ALL_STATES
    }

    ranked: list[tuple[float, EquipmentState]] = sorted(
        ((scores[state], state) for state in _CLASSIFIED_STATES),
        key=lambda item: (-item[0], item[1]),
    )
    best_score, best_state = ranked[0]
    runner_up_score = max(ranked[1][0], scores["unknown"])
    ambiguous = (
        scores["unknown"] >= best_score
        or best_score < selected_policy.minimum_state_confidence
        or best_score - runner_up_score < selected_policy.minimum_state_margin
    )
    conflicting_anomaly = best_state != "fault" and (
        audio >= selected_policy.fault_audio_threshold or visual >= selected_policy.fault_visual_threshold
    )
    # Fault is intentionally conservative: both independent evidence streams
    # must corroborate the vision classifier.
    uncorroborated_fault = best_state == "fault" and not (
        audio >= selected_policy.fault_audio_threshold and visual >= selected_policy.fault_visual_threshold
    )

    if ambiguous or conflicting_anomaly or uncorroborated_fault:
        state: EquipmentState = "unknown"
        confidence = max(scores["unknown"], 1.0 - best_score)
    else:
        state = best_state
        confidence = best_score

    return InferenceOutput(
        equipment_state=state,
        state_confidence=round(confidence, 6),
        audio_anomaly_score=round(audio, 6),
        visual_change=round(visual, 6),
        model_version=model_version.strip(),
    )


class ShadowAlertGate:
    """Stateful high-precision gate for stopped/fault alert promotion."""

    def __init__(
        self,
        *,
        shadow_mode: bool = True,
        minimum_alert_confidence: float = 0.90,
        consecutive_required: int = 2,
        minimum_precision: float = 0.95,
        maximum_false_alerts_per_device_day: float = 1.0,
    ) -> None:
        self.minimum_alert_confidence = _validated_score(
            minimum_alert_confidence,
            field="minimum_alert_confidence",
        )
        if consecutive_required < 2:
            raise ValueError("consecutive_required must be at least 2")
        self.consecutive_required = int(consecutive_required)
        self.minimum_precision = _validated_score(minimum_precision, field="minimum_precision")
        if not math.isfinite(maximum_false_alerts_per_device_day) or maximum_false_alerts_per_device_day < 0:
            raise ValueError("maximum_false_alerts_per_device_day must be >= 0")
        self.maximum_false_alerts_per_device_day = float(maximum_false_alerts_per_device_day)
        self.shadow_mode = bool(shadow_mode)
        self._candidate: EquipmentState | None = None
        self._observations = 0

    def evaluate(self, output: InferenceOutput) -> AlertDecision:
        _validated_score(output.state_confidence, field="state_confidence")
        candidate = output.equipment_state
        if candidate not in {"stopped", "fault"}:
            self._candidate = None
            self._observations = 0
            return AlertDecision(False, "normal_or_unknown", 0)
        if output.state_confidence < self.minimum_alert_confidence:
            self._candidate = None
            self._observations = 0
            return AlertDecision(False, "below_alert_confidence", 0)

        if candidate == self._candidate:
            self._observations = min(self.consecutive_required, self._observations + 1)
        else:
            self._candidate = candidate
            self._observations = 1

        if self.shadow_mode:
            return AlertDecision(False, "shadow_mode", self._observations)
        if self._observations < self.consecutive_required:
            return AlertDecision(False, "awaiting_repeated_agreement", self._observations)
        return AlertDecision(True, "eligible", self._observations)

    def enable_live_alerts(self, evidence: PromotionEvidence) -> None:
        precision = _validated_score(
            evidence.held_out_alert_precision,
            field="held_out_alert_precision",
        )
        if (
            isinstance(evidence.false_alert_count, bool)
            or not isinstance(evidence.false_alert_count, int)
            or evidence.false_alert_count < 0
        ):
            raise ValueError("false_alert_count must be >= 0")
        if (
            isinstance(evidence.device_days, bool)
            or not isinstance(evidence.device_days, (int, float))
            or not math.isfinite(float(evidence.device_days))
            or evidence.device_days <= 0
        ):
            raise ValueError("device_days must be > 0")
        if precision < self.minimum_precision:
            raise ValueError("held-out alert precision is below the promotion threshold")
        if evidence.false_alerts_per_device_day > self.maximum_false_alerts_per_device_day:
            raise ValueError("false alerts per device-day exceed the promotion threshold")
        self.shadow_mode = False
        self._candidate = None
        self._observations = 0

    def enable_shadow_mode(self) -> None:
        self.shadow_mode = True
        self._candidate = None
        self._observations = 0

    def snapshot(self) -> AlertGateSnapshot:
        return AlertGateSnapshot(candidate=self._candidate, observations=self._observations)

    def restore(self, snapshot: AlertGateSnapshot) -> None:
        if snapshot.candidate not in {None, "stopped", "fault"}:
            raise ValueError("alert gate candidate must be stopped, fault, or null")
        if (
            isinstance(snapshot.observations, bool)
            or not isinstance(snapshot.observations, int)
            or not 0 <= snapshot.observations <= self.consecutive_required
        ):
            raise ValueError("alert gate observations are outside the allowed range")
        if (snapshot.candidate is None) != (snapshot.observations == 0):
            raise ValueError("alert gate candidate and observations are inconsistent")
        self._candidate = snapshot.candidate
        self._observations = snapshot.observations
