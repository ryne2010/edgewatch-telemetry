from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol

from .bundle import InstalledModelBundle
from .litert import LiteRtClassifier
from .policy import (
    AlertDecision,
    FusionPolicy,
    InferenceOutput,
    PromotionEvidence,
    ShadowAlertGate,
    fuse_equipment_state,
)


class QuantizedClassifier(Protocol):
    def predict_quantized(self, values: Iterable[int]) -> dict[str, float]:
        raise NotImplementedError


@dataclass(frozen=True)
class InferenceEvaluation:
    output: InferenceOutput
    alert: AlertDecision

    def telemetry_scalars(self) -> dict[str, str | float | bool]:
        return {
            **self.output.as_scalars(),
            "alert_eligible": self.alert.eligible,
        }


class EquipmentInferenceRuntime:
    """Local dual-model inference with deterministic conservative fusion."""

    def __init__(
        self,
        *,
        model_version: str,
        vision_classifier: QuantizedClassifier,
        audio_classifier: QuantizedClassifier,
        fusion_policy: FusionPolicy,
        alert_gate: ShadowAlertGate,
    ) -> None:
        if not model_version.strip():
            raise ValueError("model_version must be non-empty")
        self.model_version = model_version.strip()
        self.vision_classifier = vision_classifier
        self.audio_classifier = audio_classifier
        self.fusion_policy = fusion_policy
        self.alert_gate = alert_gate

    @classmethod
    def load_bundle(
        cls,
        bundle: InstalledModelBundle,
        *,
        shadow_mode: bool = True,
    ) -> EquipmentInferenceRuntime:
        thresholds = bundle.thresholds
        return cls(
            model_version=bundle.manifest.version,
            vision_classifier=LiteRtClassifier.load(
                bundle.role_path("vision_model"),
                labels=bundle.labels["vision"],
            ),
            audio_classifier=LiteRtClassifier.load(
                bundle.role_path("audio_model"),
                labels=bundle.labels["audio"],
            ),
            fusion_policy=FusionPolicy(
                minimum_state_confidence=float(thresholds["minimum_state_confidence"]),
                minimum_state_margin=float(thresholds["minimum_state_margin"]),
                fault_audio_threshold=float(thresholds["fault_audio_threshold"]),
                fault_visual_threshold=float(thresholds["fault_visual_threshold"]),
            ),
            alert_gate=ShadowAlertGate(
                shadow_mode=shadow_mode,
                minimum_alert_confidence=float(thresholds["minimum_alert_confidence"]),
                consecutive_required=int(thresholds["consecutive_required"]),
            ),
        )

    def infer(
        self,
        *,
        vision_input: Iterable[int],
        audio_input: Iterable[int],
        visual_change: float,
    ) -> InferenceEvaluation:
        vision_scores = self.vision_classifier.predict_quantized(vision_input)
        audio_scores = self.audio_classifier.predict_quantized(audio_input)
        if set(audio_scores) != {"normal", "anomaly"}:
            raise ValueError("audio classifier output must contain normal and anomaly")
        output = fuse_equipment_state(
            vision_scores=vision_scores,
            audio_anomaly_score=audio_scores["anomaly"],
            visual_change=visual_change,
            model_version=self.model_version,
            policy=self.fusion_policy,
        )
        return InferenceEvaluation(output=output, alert=self.alert_gate.evaluate(output))

    def enable_live_alerts(self, evidence: PromotionEvidence) -> None:
        self.alert_gate.enable_live_alerts(evidence)

    def enable_shadow_mode(self) -> None:
        self.alert_gate.enable_shadow_mode()


def inference_sidecar_scalars(
    evaluation: InferenceEvaluation,
) -> Mapping[str, str | float | bool]:
    """Return only scalar, non-media inference data for telemetry/sidecars."""

    return evaluation.telemetry_scalars()
