from __future__ import annotations

import importlib
import math
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


class InferenceUnavailableError(RuntimeError):
    """LiteRT is absent or cannot be loaded on this host."""


class QuantizedModelError(ValueError):
    """The model does not satisfy the fully-quantized runtime contract."""


def _dtype_name(dtype: object) -> str:
    for attribute in ("name", "__name__"):
        value = getattr(dtype, attribute, None)
        if isinstance(value, str):
            return value.lower()
    rendered = str(dtype).lower()
    if "uint8" in rendered:
        return "uint8"
    if "int8" in rendered:
        return "int8"
    return rendered


def _shape(detail: Mapping[str, Any], *, field: str) -> tuple[int, ...]:
    raw = detail.get("shape")
    if raw is None:
        raise QuantizedModelError(f"{field} shape is invalid")
    try:
        values = tuple(int(item) for item in raw)
    except (TypeError, ValueError) as exc:
        raise QuantizedModelError(f"{field} shape is invalid") from exc
    if not values or any(item <= 0 for item in values):
        raise QuantizedModelError(f"{field} shape must be static and positive")
    return values


def _quantization(detail: Mapping[str, Any], *, field: str) -> tuple[float, int]:
    raw = detail.get("quantization")
    if not isinstance(raw, (tuple, list)) or len(raw) != 2:
        raise QuantizedModelError(f"{field} quantization metadata is missing")
    scale_raw, zero_raw = raw
    if isinstance(scale_raw, bool) or not isinstance(scale_raw, (int, float)):
        raise QuantizedModelError(f"{field} quantization scale is invalid")
    scale = float(scale_raw)
    if not math.isfinite(scale) or scale <= 0:
        raise QuantizedModelError(f"{field} quantization scale must be > 0")
    if isinstance(zero_raw, bool) or not isinstance(zero_raw, int):
        raise QuantizedModelError(f"{field} quantization zero-point is invalid")
    return scale, int(zero_raw)


def _validate_tensor(detail: Mapping[str, Any], *, field: str) -> None:
    dtype = _dtype_name(detail.get("dtype"))
    if dtype != "int8":
        raise QuantizedModelError(f"{field} must use signed int8 tensors, not {dtype}")
    _shape(detail, field=field)
    _, zero_point = _quantization(detail, field=field)
    if not -128 <= zero_point <= 127:
        raise QuantizedModelError(f"{field} quantization zero-point does not fit {dtype}")
    index = detail.get("index")
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise QuantizedModelError(f"{field} tensor index is invalid")


def _product(values: Iterable[int]) -> int:
    result = 1
    for value in values:
        result *= value
    return result


def _load_runtime_dependencies() -> tuple[Callable[..., Any], Any]:
    try:
        interpreter_module = importlib.import_module("ai_edge_litert.interpreter")
        numpy_module = importlib.import_module("numpy")
    except (ImportError, OSError) as exc:
        raise InferenceUnavailableError(
            "LiteRT runtime is unavailable; install ai-edge-litert==2.1.6 in the base image"
        ) from exc
    factory = getattr(interpreter_module, "Interpreter", None)
    if not callable(factory):
        raise InferenceUnavailableError("ai-edge-litert does not expose Interpreter")
    return factory, numpy_module


@dataclass
class LiteRtClassifier:
    """One-thread adapter for a single-input, single-output INT8 classifier."""

    interpreter: Any
    labels: tuple[str, ...]
    numpy: Any
    input_detail: Mapping[str, Any]
    output_detail: Mapping[str, Any]

    @property
    def input_shape(self) -> tuple[int, ...]:
        return _shape(self.input_detail, field="input")

    @property
    def input_dtype(self) -> str:
        return _dtype_name(self.input_detail.get("dtype"))

    @property
    def input_quantization(self) -> tuple[float, int]:
        return _quantization(self.input_detail, field="input")

    @classmethod
    def load(
        cls,
        model_path: str | Path,
        *,
        labels: Iterable[str],
        interpreter_factory: Callable[..., Any] | None = None,
        numpy_module: Any | None = None,
        max_model_bytes: int = 64 * 1024 * 1024,
    ) -> LiteRtClassifier:
        path = Path(model_path)
        try:
            metadata = path.stat()
        except OSError as exc:
            raise QuantizedModelError("model file is missing") from exc
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise QuantizedModelError("model path must be a regular file, not a symlink")
        if metadata.st_size <= 0 or metadata.st_size > max_model_bytes:
            raise QuantizedModelError("model file size is outside the allowed range")

        normalized_labels = tuple(label.strip() for label in labels)
        if (
            not normalized_labels
            or any(not label for label in normalized_labels)
            or len(set(normalized_labels)) != len(normalized_labels)
        ):
            raise QuantizedModelError("labels must be unique and non-empty")

        if interpreter_factory is None or numpy_module is None:
            runtime_factory, runtime_numpy = _load_runtime_dependencies()
            interpreter_factory = interpreter_factory or runtime_factory
            numpy_module = numpy_module or runtime_numpy
        try:
            interpreter = interpreter_factory(model_path=str(path), num_threads=1)
            interpreter.allocate_tensors()
            inputs = interpreter.get_input_details()
            outputs = interpreter.get_output_details()
            tensor_details = interpreter.get_tensor_details()
        except InferenceUnavailableError:
            raise
        except Exception as exc:
            raise QuantizedModelError("LiteRT could not load the model") from exc
        if not isinstance(inputs, list) or len(inputs) != 1:
            raise QuantizedModelError("model must expose exactly one input tensor")
        if not isinstance(outputs, list) or len(outputs) != 1:
            raise QuantizedModelError("model must expose exactly one output tensor")
        if not isinstance(tensor_details, list) or not tensor_details:
            raise QuantizedModelError("model tensor metadata is unavailable")
        input_detail = inputs[0]
        output_detail = outputs[0]
        if not isinstance(input_detail, Mapping) or not isinstance(output_detail, Mapping):
            raise QuantizedModelError("LiteRT tensor details are invalid")
        _validate_tensor(input_detail, field="input")
        _validate_tensor(output_detail, field="output")
        for tensor_number, tensor_detail in enumerate(tensor_details):
            if not isinstance(tensor_detail, Mapping):
                raise QuantizedModelError("model tensor metadata is invalid")
            dtype = _dtype_name(tensor_detail.get("dtype"))
            if "float" in dtype:
                raise QuantizedModelError(
                    f"model contains floating-point tensor {tensor_number}; fully quantized models are required"
                )
        output_count = _product(_shape(output_detail, field="output"))
        if output_count != len(normalized_labels):
            raise QuantizedModelError("output tensor size does not match labels")
        return cls(
            interpreter=interpreter,
            labels=normalized_labels,
            numpy=numpy_module,
            input_detail=input_detail,
            output_detail=output_detail,
        )

    def predict_quantized(self, values: Iterable[int]) -> dict[str, float]:
        flattened = tuple(values)
        expected = _product(_shape(self.input_detail, field="input"))
        if len(flattened) != expected:
            raise QuantizedModelError(
                f"known-answer input contains {len(flattened)} values; expected {expected}"
            )
        dtype_name = _dtype_name(self.input_detail.get("dtype"))
        if dtype_name != "int8":
            raise QuantizedModelError(f"input must use signed int8 tensors, not {dtype_name}")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or not -128 <= value <= 127
            for value in flattened
        ):
            raise QuantizedModelError("input values must fit signed int8")

        try:
            tensor = self.numpy.asarray(flattened, dtype=self.input_detail["dtype"]).reshape(
                _shape(self.input_detail, field="input")
            )
            self.interpreter.set_tensor(int(self.input_detail["index"]), tensor)
            self.interpreter.invoke()
            raw_output = self.interpreter.get_tensor(int(self.output_detail["index"]))
            output_values = tuple(raw_output.reshape(-1).tolist())
        except Exception as exc:
            raise QuantizedModelError("LiteRT inference failed") from exc
        if len(output_values) != len(self.labels):
            raise QuantizedModelError("LiteRT returned an unexpected output shape")
        scale, zero_point = _quantization(self.output_detail, field="output")
        scores = {
            label: max(0.0, min(1.0, (float(raw) - zero_point) * scale))
            for label, raw in zip(self.labels, output_values, strict=True)
        }
        return scores
