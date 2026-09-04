"""Secret-safe Telegram delivery for EdgeWatch telemetry points."""

from __future__ import annotations

import json
import gzip
import math
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests


_TELEGRAM_API_BASE_URL = "https://api.telegram.org"
_TELEGRAM_DOCUMENT_MAX_BYTES = 50_000_000
_ALLOWED_TRANSPORTS = frozenset({"api", "telegram"})
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_SAFE_FILENAME_PART = re.compile(r"[^A-Za-z0-9._-]+")


class TelegramTransportConfigError(ValueError):
    """Raised when transport configuration is missing or invalid."""


@dataclass(frozen=True)
class TelegramTransportConfig:
    transport: str = "api"
    chat_id: str | None = None
    bot_token: str | None = None
    timeout_s: float = 10.0
    disable_notification: bool = False
    protect_content: bool = True
    batch_enabled: bool = False
    batch_max_points: int = 100
    batch_max_bytes: int = 1_000_000
    batch_max_age_s: float = 3600.0


@dataclass(frozen=True)
class TelegramDeliveryResult:
    """Delivery outcome; callers retain the point whenever ``delivered`` is false."""

    delivered: bool
    retry_after_s: float | None
    status_code: int | None
    reason: str
    bytes_sent: int
    permanent: bool = False
    estimated_wire_bytes: int = 0

    @property
    def document_bytes(self) -> int:
        """Bytes in the uploaded document (legacy ``bytes_sent`` semantics)."""

        return self.bytes_sent


class _Response(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def headers(self) -> Mapping[str, Any]: ...

    def json(self) -> Any: ...


def load_telegram_transport_config(
    env: Mapping[str, str] | None = None,
) -> TelegramTransportConfig:
    """Parse API/Telegram transport settings without exposing credential values."""

    values = os.environ if env is None else env
    transport = values.get("EDGEWATCH_TELEMETRY_TRANSPORT", "api").strip().lower()
    if transport not in _ALLOWED_TRANSPORTS:
        raise TelegramTransportConfigError("EDGEWATCH_TELEMETRY_TRANSPORT must be one of: api, telegram")

    # Keep transport-specific settings isolated: stale or partially prepared
    # Telegram variables must not break the default API mode.
    if transport == "api":
        return TelegramTransportConfig(transport=transport)

    timeout_s = _parse_positive_float(values, "TELEGRAM_TIMEOUT_S", default=10.0)
    disable_notification = _parse_bool(values, "TELEGRAM_DISABLE_NOTIFICATION", default=False)
    protect_content = _parse_bool(values, "TELEGRAM_PROTECT_CONTENT", default=True)
    batch_enabled = _parse_bool(values, "TELEGRAM_BATCH_ENABLED", default=False)
    batch_max_points = _parse_positive_int(values, "TELEGRAM_BATCH_MAX_POINTS", default=100)
    batch_max_bytes = _parse_positive_int(values, "TELEGRAM_BATCH_MAX_BYTES", default=1_000_000)
    batch_max_age_s = _parse_positive_float(values, "TELEGRAM_BATCH_MAX_AGE_S", default=3600.0)

    chat_id = values.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        raise TelegramTransportConfigError(
            "TELEGRAM_CHAT_ID is required when EDGEWATCH_TELEMETRY_TRANSPORT=telegram"
        )

    bot_token = values.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        bot_token = _read_bot_token_file(values.get("TELEGRAM_BOT_TOKEN_FILE"))
    if not bot_token:
        raise TelegramTransportConfigError(
            "TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN_FILE is required "
            "when EDGEWATCH_TELEMETRY_TRANSPORT=telegram"
        )

    return TelegramTransportConfig(
        transport=transport,
        chat_id=chat_id,
        bot_token=bot_token,
        timeout_s=timeout_s,
        disable_notification=disable_notification,
        protect_content=protect_content,
        batch_enabled=batch_enabled,
        batch_max_points=batch_max_points,
        batch_max_bytes=batch_max_bytes,
        batch_max_age_s=batch_max_age_s,
    )


class TelegramTransport:
    """Send one complete telemetry envelope through Telegram Bot API."""

    def __init__(
        self,
        config: TelegramTransportConfig,
        *,
        session: Any | None = None,
        base_url: str = _TELEGRAM_API_BASE_URL,
    ) -> None:
        if config.transport != "telegram" or not config.chat_id or not config.bot_token:
            raise TelegramTransportConfigError(
                "TelegramTransport requires a complete telegram transport configuration"
            )
        self._config = config
        self._session = session or requests.Session()
        self._base_url = base_url.rstrip("/")

    def send(self, device_id: str, point: Mapping[str, Any]) -> TelegramDeliveryResult:
        """Send a full-fidelity point; any unsuccessful result means retain and retry."""

        try:
            document = _serialize_envelope(device_id, point)
        except (TypeError, ValueError):
            return TelegramDeliveryResult(
                delivered=False,
                retry_after_s=None,
                status_code=None,
                reason="telemetry envelope is not JSON serializable",
                bytes_sent=0,
                permanent=True,
            )

        if len(document) > _TELEGRAM_DOCUMENT_MAX_BYTES:
            return TelegramDeliveryResult(
                delivered=False,
                retry_after_s=None,
                status_code=None,
                reason="telemetry document exceeds Telegram's 50 MB limit",
                bytes_sent=0,
                permanent=True,
            )

        return self._send_document(
            device_id=device_id,
            document=document,
            filename=_document_filename(point),
            content_type="application/json; charset=utf-8",
            caption=_build_caption(device_id, point),
        )

    def send_batch(self, device_id: str, points: Sequence[Mapping[str, Any]]) -> TelegramDeliveryResult:
        """Send ordered, full-fidelity envelopes as deterministic gzip JSONL."""

        if not points:
            return TelegramDeliveryResult(
                delivered=False,
                retry_after_s=None,
                status_code=None,
                reason="telegram batch must contain at least one point",
                bytes_sent=0,
                permanent=True,
            )
        try:
            jsonl = b"\n".join(_serialize_envelope(device_id, point) for point in points) + b"\n"
            document = gzip.compress(jsonl, compresslevel=9, mtime=0)
        except (TypeError, ValueError):
            return TelegramDeliveryResult(
                delivered=False,
                retry_after_s=None,
                status_code=None,
                reason="telemetry batch is not JSON serializable",
                bytes_sent=0,
                permanent=True,
            )
        if len(document) > _TELEGRAM_DOCUMENT_MAX_BYTES:
            return TelegramDeliveryResult(
                delivered=False,
                retry_after_s=None,
                status_code=None,
                reason="telemetry batch exceeds Telegram's 50 MB limit",
                bytes_sent=0,
                permanent=True,
            )
        first_id = _caption_value(points[0].get("message_id"))
        last_id = _caption_value(points[-1].get("message_id"))
        caption = (
            f"{_batch_caption_title(points)}\n"
            f"device_id: {_caption_value(device_id)}\n"
            f"points: {len(points)}\nfirst_message_id: {first_id}\nlast_message_id: {last_id}"
        )[:1024]
        return self._send_document(
            device_id=device_id,
            document=document,
            filename=f"edgewatch-{_safe_filename_part(device_id)}-telemetry.jsonl.gz",
            content_type="application/gzip",
            caption=caption,
        )

    def serialized_envelope_size(self, device_id: str, point: Mapping[str, Any]) -> int:
        """Return canonical uncompressed JSONL bytes used for batch selection."""

        return len(_serialize_envelope(device_id, point)) + 1

    @property
    def config(self) -> TelegramTransportConfig:
        return self._config

    def _send_document(
        self,
        *,
        device_id: str,
        document: bytes,
        filename: str,
        content_type: str,
        caption: str,
    ) -> TelegramDeliveryResult:
        data = {
            "chat_id": self._config.chat_id,
            "caption": caption,
            "disable_notification": _telegram_bool(self._config.disable_notification),
            "protect_content": _telegram_bool(self._config.protect_content),
        }
        files = {
            "document": (
                filename,
                document,
                content_type,
            )
        }
        url = f"{self._base_url}/bot{self._config.bot_token}/sendDocument"
        estimated_wire_bytes = _estimate_wire_bytes(data, filename, content_type, document)

        try:
            response = self._session.post(
                url,
                data=data,
                files=files,
                timeout=self._config.timeout_s,
            )
        except requests.RequestException:
            return TelegramDeliveryResult(
                delivered=False,
                retry_after_s=None,
                status_code=None,
                reason="telegram network request failed",
                bytes_sent=len(document),
                estimated_wire_bytes=estimated_wire_bytes,
            )

        return _response_result(
            response,
            bytes_sent=len(document),
            estimated_wire_bytes=estimated_wire_bytes,
        )


def _serialize_envelope(device_id: str, point: Mapping[str, Any]) -> bytes:
    return json.dumps(
        {"device_id": device_id, "point": point},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _build_caption(device_id: str, point: Mapping[str, Any]) -> str:
    metrics = point.get("metrics")
    metrics = metrics if isinstance(metrics, Mapping) else {}
    fields = [
        ("device_id", device_id),
        ("ts", point.get("ts")),
        ("message_id", point.get("message_id")),
        ("device_state", point.get("device_state", metrics.get("device_state"))),
        (
            "buffer_queue_depth",
            point.get("buffer_queue_depth", metrics.get("buffer_queue_depth")),
        ),
        (
            "cellular_registration",
            point.get("cellular_registration_state", metrics.get("cellular_registration_state")),
        ),
    ]
    lines = [_caption_title(point, metrics)]
    for name, value in fields:
        if value is not None:
            lines.append(f"{name}: {_caption_value(value)}")
    return "\n".join(lines)[:1024]


def _caption_title(point: Mapping[str, Any], metrics: Mapping[str, Any]) -> str:
    state = _caption_alert_state(point, metrics)
    if state is None:
        return "EdgeWatch telemetry"
    severity, subsystem = state
    icons = [severity]
    if subsystem is not None:
        icons.append(subsystem)
    return f"{' '.join(icons)} EdgeWatch telemetry"


def _batch_caption_title(points: Sequence[Mapping[str, Any]]) -> str:
    ranked: list[tuple[int, str, str | None]] = []
    rank = {"🚨": 4, "⚠️": 3, "✅": 2, "ℹ️": 1}
    for point in points:
        metrics_raw = point.get("metrics")
        metrics = metrics_raw if isinstance(metrics_raw, Mapping) else {}
        state = _caption_alert_state(point, metrics)
        if state is not None:
            ranked.append((rank[state[0]], state[0], state[1]))
    if not ranked:
        return "EdgeWatch telemetry batch"
    _, severity, subsystem = max(ranked, key=lambda item: item[0])
    icons = [severity]
    if subsystem is not None:
        icons.append(subsystem)
    return f"{' '.join(icons)} EdgeWatch telemetry batch"


def _caption_alert_state(
    point: Mapping[str, Any], metrics: Mapping[str, Any]
) -> tuple[str, str | None] | None:
    severity_raw = point.get(
        "severity",
        point.get("alert_severity", metrics.get("severity", metrics.get("alert_severity"))),
    )
    severity = str(severity_raw).strip().lower() if severity_raw is not None else ""
    lifecycle_raw = point.get("alert_state", metrics.get("alert_state"))
    lifecycle = str(lifecycle_raw).strip().lower() if lifecycle_raw is not None else ""
    device_state_raw = point.get("device_state", metrics.get("device_state"))
    device_state = str(device_state_raw).strip().lower() if device_state_raw is not None else ""

    if lifecycle in {"recovered", "resolved"} or severity in {"recovered", "resolved", "success"}:
        severity_icon = "✅"
    elif severity in {"critical", "emergency"} or device_state in {"critical", "fault"}:
        severity_icon = "🚨"
    elif severity in {"warning", "warn"} or device_state in {"warn", "warning"}:
        severity_icon = "⚠️"
    elif severity in {"info", "informational"}:
        severity_icon = "ℹ️"
    elif point.get("alert_type") is not None or metrics.get("alert_type") is not None:
        severity_icon = "⚠️"
    elif (
        metrics.get("power_input_out_of_range") is True
        or metrics.get("power_unsustainable") is True
        or metrics.get("link_ok") is False
    ):
        severity_icon = "⚠️"
    else:
        return None
    return severity_icon, _caption_subsystem(point, metrics, device_state)


def _caption_subsystem(point: Mapping[str, Any], metrics: Mapping[str, Any], device_state: str) -> str | None:
    alert_raw = point.get("alert_type", metrics.get("alert_type", ""))
    alert_type = str(alert_raw).upper()
    keys = {str(key).lower() for key in metrics}
    if (
        "POWER" in alert_type
        or "BATTERY" in alert_type
        or metrics.get("power_input_out_of_range") is True
        or metrics.get("power_unsustainable") is True
        or (device_state in {"warn", "warning", "critical", "fault"} and "battery_v" in keys)
    ):
        return "🔋"
    if (
        any(value in alert_type for value in ("NETWORK", "SIGNAL", "CELLULAR", "LINK"))
        or metrics.get("link_ok") is False
        or any(key.startswith(("cellular_", "signal_")) for key in keys)
    ):
        return "📶"
    if "OTA" in alert_type or any(key.startswith(("ota_", "update_")) for key in keys):
        return "🔄"
    if "LORA" in alert_type or "GATEWAY" in alert_type or any("lora" in key for key in keys):
        return "🛰️"
    if (
        any(value in alert_type for value in ("VISION", "CAMERA", "EQUIPMENT"))
        or "equipment_state" in keys
        or any(key.startswith(("visual_", "vision_", "camera_")) for key in keys)
    ):
        return "🎥"
    if any(value in alert_type for value in ("AUDIO", "MICROPHONE", "SOUND")) or any(
        key.startswith(("audio_", "microphone_", "sound_")) for key in keys
    ):
        return "🎙️"
    if "SLEEP" in alert_type or any(key in keys for key in ("power_sleep_backend", "wake_reason")):
        return "💤"
    return None


def _caption_value(value: Any) -> str:
    return " ".join(str(value).split())[:160]


def _document_filename(point: Mapping[str, Any]) -> str:
    raw_message_id = str(point.get("message_id") or "telemetry")
    safe_message_id = _SAFE_FILENAME_PART.sub("_", raw_message_id).strip("._-")[:80]
    return f"edgewatch-{safe_message_id or 'telemetry'}.json"


def _response_result(
    response: _Response, *, bytes_sent: int, estimated_wire_bytes: int = 0
) -> TelegramDeliveryResult:
    payload: Mapping[str, Any] = {}
    try:
        candidate = response.json()
        if isinstance(candidate, Mapping):
            payload = candidate
    except (TypeError, ValueError):
        pass

    retry_after_s = _retry_after_from_payload(payload)
    if retry_after_s is None:
        retry_after_s = _parse_retry_after(response.headers.get("Retry-After"))

    if 200 <= response.status_code < 300 and payload.get("ok") is True:
        return TelegramDeliveryResult(
            delivered=True,
            retry_after_s=None,
            status_code=response.status_code,
            reason="delivered",
            bytes_sent=bytes_sent,
            estimated_wire_bytes=estimated_wire_bytes,
        )

    error_code = payload.get("error_code")
    if isinstance(error_code, int) and not isinstance(error_code, bool):
        reason = f"telegram API rejected delivery (error_code={error_code})"
    elif not 200 <= response.status_code < 300:
        reason = f"telegram HTTP failure (status={response.status_code})"
    else:
        reason = "telegram API returned an invalid response"
    return TelegramDeliveryResult(
        delivered=False,
        retry_after_s=retry_after_s,
        status_code=response.status_code,
        reason=reason,
        bytes_sent=bytes_sent,
        estimated_wire_bytes=estimated_wire_bytes,
    )


def _retry_after_from_payload(payload: Mapping[str, Any]) -> float | None:
    parameters = payload.get("parameters")
    if not isinstance(parameters, Mapping):
        return None
    return _parse_retry_after(parameters.get("retry_after"))


def _parse_retry_after(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def _parse_bool(values: Mapping[str, str], name: str, *, default: bool) -> bool:
    raw = values.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise TelegramTransportConfigError(f"{name} must be one of: 0, 1, false, no, off, on, true, yes")


def _parse_positive_float(values: Mapping[str, str], name: str, *, default: float) -> float:
    raw = values.get(name)
    if raw is None:
        return default
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise TelegramTransportConfigError(f"{name} must be a positive number") from exc
    if not math.isfinite(value) or value <= 0:
        raise TelegramTransportConfigError(f"{name} must be a positive number")
    return value


def _parse_positive_int(values: Mapping[str, str], name: str, *, default: int) -> int:
    raw = values.get(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise TelegramTransportConfigError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise TelegramTransportConfigError(f"{name} must be a positive integer")
    return value


def _safe_filename_part(value: str) -> str:
    sanitized = _SAFE_FILENAME_PART.sub("_", value).strip("._-")[:80]
    return sanitized or "device"


def _estimate_wire_bytes(data: Mapping[str, str], filename: str, content_type: str, document: bytes) -> int:
    """Estimate HTTP request bytes, including multipart and conservative TLS framing.

    ``requests`` generates the multipart boundary internally, so exact interface
    counters remain the authority. This estimate deliberately excludes response
    bytes and lower-layer cellular framing.
    """

    boundary_bytes = 32
    multipart_bytes = 0
    for name, value in data.items():
        multipart_bytes += boundary_bytes + len(name.encode()) + len(value.encode()) + 64
    multipart_bytes += (
        boundary_bytes + len(filename.encode()) + len(content_type.encode()) + len(document) + 128
    )
    http_headers = 700
    tls_record_overhead = 64
    return multipart_bytes + http_headers + tls_record_overhead


def _read_bot_token_file(raw_path: str | None) -> str:
    if raw_path is None or not raw_path.strip():
        return ""
    try:
        path = Path(raw_path.strip())
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise TelegramTransportConfigError("TELEGRAM_BOT_TOKEN_FILE permissions must be 0600 or stricter")
        token = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise TelegramTransportConfigError(
            "TELEGRAM_BOT_TOKEN_FILE must name a readable UTF-8 token file"
        ) from exc
    if not token:
        raise TelegramTransportConfigError("TELEGRAM_BOT_TOKEN_FILE must not be empty")
    return token


def _telegram_bool(value: bool) -> str:
    return "true" if value else "false"
