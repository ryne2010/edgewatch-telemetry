from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pytest

from agent.inference.litert import (
    InferenceUnavailableError,
    LiteRtClassifier,
    QuantizedModelError,
)
from agent.inference.policy import (
    FusionPolicy,
    InferenceOutput,
    PromotionEvidence,
    ShadowAlertGate,
    fuse_equipment_state,
)
from agent.inference.runtime import EquipmentInferenceRuntime


def test_fusion_prefers_unknown_for_ambiguous_or_conflicting_evidence() -> None:
    ambiguous = fuse_equipment_state(
        vision_scores={"running": 0.81, "stopped": 0.72, "fault": 0.01, "unknown": 0.01},
        audio_anomaly_score=0.1,
        visual_change=0.1,
        model_version="model-1",
    )
    conflicting = fuse_equipment_state(
        vision_scores={"running": 0.95, "stopped": 0.02, "fault": 0.01, "unknown": 0.02},
        audio_anomaly_score=0.95,
        visual_change=0.1,
        model_version="model-1",
    )
    uncorroborated_fault = fuse_equipment_state(
        vision_scores={"running": 0.01, "stopped": 0.02, "fault": 0.95, "unknown": 0.02},
        audio_anomaly_score=0.1,
        visual_change=0.1,
        model_version="model-1",
    )

    assert ambiguous.equipment_state == "unknown"
    assert conflicting.equipment_state == "unknown"
    assert uncorroborated_fault.equipment_state == "unknown"


def test_fusion_accepts_high_confidence_corroborated_fault() -> None:
    output = fuse_equipment_state(
        vision_scores={"running": 0.01, "stopped": 0.02, "fault": 0.95, "unknown": 0.02},
        audio_anomaly_score=0.91,
        visual_change=0.9,
        model_version="model-1",
    )

    assert output.equipment_state == "fault"
    assert output.as_scalars() == {
        "equipment_state": "fault",
        "state_confidence": 0.95,
        "audio_anomaly_score": 0.91,
        "visual_change": 0.9,
        "model_version": "model-1",
    }


def test_shadow_gate_requires_promotion_evidence_and_repeated_agreement() -> None:
    gate = ShadowAlertGate(shadow_mode=True, consecutive_required=2)
    fault = InferenceOutput("fault", 0.97, 0.95, 0.2, "model-1")

    assert gate.evaluate(fault).reason == "shadow_mode"
    assert gate.evaluate(fault).eligible is False
    with pytest.raises(ValueError, match="precision"):
        gate.enable_live_alerts(PromotionEvidence(0.949, false_alert_count=0, device_days=14))
    with pytest.raises(ValueError, match="false alerts"):
        gate.enable_live_alerts(PromotionEvidence(0.95, false_alert_count=15, device_days=14))

    gate.enable_live_alerts(PromotionEvidence(0.95, false_alert_count=14, device_days=14))
    first = gate.evaluate(fault)
    second = gate.evaluate(fault)

    assert first.reason == "awaiting_repeated_agreement"
    assert second.eligible is True


class _ScoresClassifier:
    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores

    def predict_quantized(self, values: Iterable[int]) -> dict[str, float]:
        assert tuple(values)
        return dict(self.scores)


def test_equipment_runtime_emits_scalars_but_shadow_suppresses_alert() -> None:
    runtime = EquipmentInferenceRuntime(
        model_version="model-1",
        vision_classifier=_ScoresClassifier(
            {"running": 0.01, "stopped": 0.01, "fault": 0.96, "unknown": 0.02}
        ),
        audio_classifier=_ScoresClassifier({"normal": 0.03, "anomaly": 0.97}),
        fusion_policy=FusionPolicy(),
        alert_gate=ShadowAlertGate(shadow_mode=True),
    )

    evaluation = runtime.infer(vision_input=[1], audio_input=[2], visual_change=0.9)

    assert evaluation.output.equipment_state == "fault"
    assert evaluation.alert.reason == "shadow_mode"
    assert evaluation.telemetry_scalars()["alert_eligible"] is False


class _DType:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeInterpreter:
    def __init__(
        self,
        *,
        input_dtype: str = "int8",
        output_dtype: str = "int8",
        input_zero_point: int = 0,
    ) -> None:
        self.input_dtype = input_dtype
        self.output_dtype = output_dtype
        self.input_zero_point = input_zero_point

    def allocate_tensors(self) -> None:
        return None

    def get_input_details(self) -> list[dict[str, Any]]:
        return [
            {
                "shape": [1, 2],
                "dtype": _DType(self.input_dtype),
                "quantization": (0.1, self.input_zero_point),
                "index": 0,
            }
        ]

    def get_output_details(self) -> list[dict[str, Any]]:
        return [
            {
                "shape": [1, 2],
                "dtype": _DType(self.output_dtype),
                "quantization": (0.01, -128),
                "index": 1,
            }
        ]

    def get_tensor_details(self) -> list[dict[str, Any]]:
        return [*self.get_input_details(), *self.get_output_details()]


def test_litert_adapter_pins_one_thread_and_requires_signed_int8_models(tmp_path: Path) -> None:
    model_path = tmp_path / "model.tflite"
    model_path.write_bytes(b"tflite")
    calls: list[dict[str, Any]] = []

    def factory(**kwargs: Any) -> _FakeInterpreter:
        calls.append(kwargs)
        return _FakeInterpreter()

    classifier = LiteRtClassifier.load(
        model_path,
        labels=("normal", "anomaly"),
        interpreter_factory=factory,
        numpy_module=object(),
    )
    assert classifier.labels == ("normal", "anomaly")
    assert calls == [{"model_path": str(model_path), "num_threads": 1}]

    with pytest.raises(QuantizedModelError, match="signed int8 tensors, not float32"):
        LiteRtClassifier.load(
            model_path,
            labels=("normal", "anomaly"),
            interpreter_factory=lambda **_kwargs: _FakeInterpreter(output_dtype="float32"),
            numpy_module=object(),
        )

    with pytest.raises(QuantizedModelError, match="signed int8 tensors, not uint8"):
        LiteRtClassifier.load(
            model_path,
            labels=("normal", "anomaly"),
            interpreter_factory=lambda **_kwargs: _FakeInterpreter(output_dtype="uint8"),
            numpy_module=object(),
        )

    with pytest.raises(QuantizedModelError, match="signed int8 tensors, not uint8"):
        LiteRtClassifier.load(
            model_path,
            labels=("normal", "anomaly"),
            interpreter_factory=lambda **_kwargs: _FakeInterpreter(input_dtype="uint8"),
            numpy_module=object(),
        )

    with pytest.raises(QuantizedModelError, match="zero-point"):
        LiteRtClassifier.load(
            model_path,
            labels=("normal", "anomaly"),
            interpreter_factory=lambda **_kwargs: _FakeInterpreter(input_zero_point=255),
            numpy_module=object(),
        )


def test_litert_import_fails_cleanly_off_pi(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_path = tmp_path / "model.tflite"
    model_path.write_bytes(b"tflite")

    def fail_import(name: str) -> Any:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("agent.inference.litert.importlib.import_module", fail_import)

    with pytest.raises(InferenceUnavailableError, match="ai-edge-litert==2.1.6"):
        LiteRtClassifier.load(model_path, labels=("normal", "anomaly"))
