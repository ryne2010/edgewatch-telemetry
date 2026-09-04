from __future__ import annotations

import base64
import binascii
import importlib
import json
import re
import stat
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping

from .config import DeviceIdentity, DeviceRegistry, IdentityConfigError
from .protocol import (
    EquipmentState,
    HealthFlag,
    MessageType,
    ProtocolError,
    UPLINK_SIZE,
    WAKE_SIZE,
    UplinkFrame,
    canonical_message_id,
    decode_uplink,
    decode_wake,
)

if TYPE_CHECKING:
    from .store import GatewayStore


_TOPIC = re.compile(
    r"^application/(?P<application_id>[A-Za-z0-9][A-Za-z0-9-]{0,63})/"
    r"device/(?P<dev_eui>[0-9a-fA-F]{16})/event/up$"
)


class ChirpStackError(ValueError):
    """Raised when a ChirpStack MQTT event violates the gateway boundary."""


class MqttDependencyError(RuntimeError):
    """Raised at runtime when MQTT operation is requested without paho-mqtt."""


def _safe_segment(value: object, *, where: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ChirpStackError(f"{where} is invalid")
    return value


def _secret_file(path: Path | None) -> Path | None:
    if path is None:
        return None
    if not isinstance(path, Path):
        raise ChirpStackError("MQTT password_file must be a filesystem path")
    expanded = path.expanduser()
    try:
        mode = stat.S_IMODE(expanded.stat().st_mode)
    except OSError as exc:
        raise ChirpStackError("MQTT password file cannot be read") from exc
    if not expanded.is_file() or mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ChirpStackError("MQTT password file must be a regular file with mode 0600 or stricter")
    if not expanded.read_text(encoding="utf-8").strip():
        raise ChirpStackError("MQTT password file is empty")
    return expanded


@dataclass(frozen=True)
class MqttConnectionConfig:
    host: str
    application_id: str
    port: int = 1883
    client_id: str = "edgewatch-lorawan-gateway"
    username: str | None = None
    password_file: Path | None = None
    tls: bool = False
    keepalive_s: int = 60
    qos: int = 1

    def __post_init__(self) -> None:
        host = self.host.strip() if isinstance(self.host, str) else ""
        if not host or any(char.isspace() for char in host) or "/" in host:
            raise ChirpStackError("MQTT host is invalid")
        application_id = _safe_segment(
            self.application_id,
            where="MQTT application_id",
            pattern=re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}"),
        )
        client_id = _safe_segment(
            self.client_id,
            where="MQTT client_id",
            pattern=re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"),
        )
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ChirpStackError("MQTT port must be from 1 through 65535")
        if (
            isinstance(self.keepalive_s, bool)
            or not isinstance(self.keepalive_s, int)
            or not 5 <= self.keepalive_s <= 3_600
        ):
            raise ChirpStackError("MQTT keepalive_s must be from 5 through 3600")
        if isinstance(self.qos, bool) or self.qos not in {0, 1, 2}:
            raise ChirpStackError("MQTT qos must be 0, 1, or 2")
        if not isinstance(self.tls, bool):
            raise ChirpStackError("MQTT tls must be a boolean")
        if self.username is not None and (not isinstance(self.username, str) or not self.username.strip()):
            raise ChirpStackError("MQTT username must be a non-empty string")
        password_file = _secret_file(self.password_file)
        if (self.username is None) != (password_file is None):
            raise ChirpStackError("MQTT username and password_file must be configured together")
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "application_id", application_id)
        object.__setattr__(self, "client_id", client_id)
        object.__setattr__(self, "password_file", password_file)
        if self.username is not None:
            object.__setattr__(self, "username", self.username.strip())

    @property
    def uplink_topic(self) -> str:
        return f"application/{self.application_id}/device/+/event/up"

    def password(self) -> str | None:
        if self.password_file is None:
            return None
        return self.password_file.read_text(encoding="utf-8").strip()


@dataclass(frozen=True)
class ChirpStackUplink:
    application_id: str
    dev_eui: str
    device_id: str
    message_id: str
    frame: UplinkFrame
    frame_bytes: bytes
    canonical_point: Mapping[str, Any]
    envelope_json: str
    deduplication_id: str | None = None

    @property
    def requires_immediate_alert(self) -> bool:
        """Return whether this frame must wake the gateway LTE path immediately."""

        return self.frame.equipment_state is EquipmentState.FAULT or bool(
            self.frame.flags & HealthFlag.SENTINEL_TRIGGERED
        )


def _mapping(value: object, *, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ChirpStackError(f"{where} must be a JSON object")
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value is not permitted: {value}")


def _parse_json(payload: bytes | str) -> tuple[Mapping[str, Any], str]:
    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ChirpStackError("MQTT uplink must be UTF-8 JSON") from exc
    elif isinstance(payload, str):
        text = payload
    else:
        raise ChirpStackError("MQTT uplink must be bytes or text")
    try:
        parsed = json.loads(
            text,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ChirpStackError("MQTT uplink must be valid JSON") from exc
    envelope = _mapping(parsed, where="MQTT uplink")
    return envelope, json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _canonical_point(identity: DeviceIdentity, frame: UplinkFrame, frame_bytes: bytes) -> dict[str, Any]:
    flags = frame.flags
    timestamp = datetime.fromtimestamp(frame.timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    point: dict[str, Any] = {
        "message_id": canonical_message_id(identity.dev_eui, frame_bytes),
        "ts": timestamp,
        "metrics": {
            "lorawan_message_type": frame.message_type.name.lower(),
            "lorawan_sequence": frame.sequence,
            "lorawan_dev_eui": identity.dev_eui,
            "equipment_state": frame.equipment_state.name.lower(),
            "visual_confidence": frame.visual_confidence_pct / 100.0,
            "audio_anomaly_score": frame.audio_confidence_pct / 100.0,
            "battery_v": frame.battery_mv / 1000.0,
            "power_input_out_of_range": bool(flags & HealthFlag.POWER_INPUT_OUT_OF_RANGE),
            "power_unsustainable": bool(flags & HealthFlag.POWER_UNSUSTAINABLE),
            "low_battery": bool(flags & HealthFlag.LOW_BATTERY),
            "sentinel_triggered": bool(flags & HealthFlag.SENTINEL_TRIGGERED),
            "camera_ok": bool(flags & HealthFlag.CAMERA_OK),
            "audio_ok": bool(flags & HealthFlag.AUDIO_OK),
            "maintenance_ready": bool(flags & HealthFlag.MAINTENANCE_READY),
            "degraded": bool(flags & HealthFlag.DEGRADED),
        },
    }
    if flags & HealthFlag.MAINTENANCE_READY:
        point["metrics"]["maintenance_command_token"] = frame.model_digest.hex()
    else:
        point["metrics"]["model_version_digest"] = frame.model_digest.hex()
    if frame.message_type is MessageType.EVENT and frame.equipment_state is EquipmentState.FAULT:
        point.update({"severity": "critical", "alert_type": "EQUIPMENT_FAULT"})
    elif frame.message_type is MessageType.EVENT and flags & HealthFlag.SENTINEL_TRIGGERED:
        point.update({"severity": "warning", "alert_type": "EQUIPMENT_EVENT"})
    elif flags & (
        HealthFlag.POWER_INPUT_OUT_OF_RANGE | HealthFlag.POWER_UNSUSTAINABLE | HealthFlag.LOW_BATTERY
    ):
        point.update({"severity": "warning", "alert_type": "POWER_HEALTH"})
    return point


def parse_uplink_event(
    topic: str,
    payload: bytes | str,
    registry: DeviceRegistry,
) -> ChirpStackUplink:
    """Validate a ChirpStack v4 event and map it to canonical EdgeWatch telemetry."""

    match = _TOPIC.fullmatch(topic)
    if match is None:
        raise ChirpStackError("MQTT topic is not a ChirpStack v4 uplink topic")
    topic_application = match.group("application_id")
    topic_eui = match.group("dev_eui").lower()
    try:
        identity = registry.by_dev_eui(topic_eui)
    except IdentityConfigError as exc:
        raise ChirpStackError("uplink DevEUI is not in the closed inventory") from exc
    if identity.application_id != topic_application:
        raise ChirpStackError("uplink application does not match the device inventory")

    envelope, envelope_json = _parse_json(payload)
    device_info = _mapping(envelope.get("deviceInfo"), where="MQTT uplink.deviceInfo")
    if device_info.get("applicationId") != topic_application:
        raise ChirpStackError("deviceInfo.applicationId does not match the MQTT topic")
    payload_eui = device_info.get("devEui")
    if not isinstance(payload_eui, str) or payload_eui.lower() != topic_eui:
        raise ChirpStackError("deviceInfo.devEui does not match the MQTT topic")
    f_port = envelope.get("fPort")
    if isinstance(f_port, bool) or not isinstance(f_port, int) or f_port != identity.uplink_f_port:
        raise ChirpStackError("uplink fPort does not match the device inventory")
    encoded_data = envelope.get("data")
    if not isinstance(encoded_data, str):
        raise ChirpStackError("uplink data must be base64 text")
    expected_base64_size = ((UPLINK_SIZE + 2) // 3) * 4
    if len(encoded_data) != expected_base64_size:
        raise ChirpStackError("uplink data has an invalid base64 encoded size")
    try:
        frame_bytes = base64.b64decode(encoded_data, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ChirpStackError("uplink data must be canonical base64") from exc
    if len(frame_bytes) != UPLINK_SIZE:
        raise ChirpStackError(f"decoded uplink must be exactly {UPLINK_SIZE} bytes")
    if base64.b64encode(frame_bytes).decode("ascii") != encoded_data:
        raise ChirpStackError("uplink data must use canonical base64 encoding")
    try:
        frame = decode_uplink(frame_bytes)
    except ProtocolError as exc:
        raise ChirpStackError(str(exc)) from exc
    deduplication_id = envelope.get("deduplicationId")
    if deduplication_id is not None and not isinstance(deduplication_id, str):
        raise ChirpStackError("deduplicationId must be text when present")
    point = _canonical_point(identity, frame, frame_bytes)
    return ChirpStackUplink(
        application_id=topic_application,
        dev_eui=topic_eui,
        device_id=identity.device_id,
        message_id=str(point["message_id"]),
        frame=frame,
        frame_bytes=frame_bytes,
        canonical_point=point,
        envelope_json=envelope_json,
        deduplication_id=deduplication_id,
    )


class ChirpStackBridge:
    """QoS-aware ChirpStack MQTT adapter with durable alert reconciliation."""

    def __init__(
        self,
        config: MqttConnectionConfig,
        registry: DeviceRegistry,
        store: GatewayStore,
        *,
        mqtt_client: Any | None = None,
        uplink_observer: Callable[[ChirpStackUplink], None] | None = None,
        receive_window_observer: Callable[[ChirpStackUplink], None] | None = None,
        error_observer: Callable[[Exception], None] | None = None,
    ) -> None:
        if config.application_id not in registry.application_ids:
            raise ChirpStackError("MQTT application_id has no devices in the inventory")
        self.config = config
        self.registry = registry
        self.store = store
        self._client = mqtt_client
        self._uplink_observer = uplink_observer
        self._receive_window_observer = receive_window_observer
        self._error_observer = error_observer
        self._alert_worker_id = f"lorawan-alert-{uuid.uuid4()}"
        self._alert_stop = threading.Event()
        self._alert_thread: threading.Thread | None = None

    def handle_message(self, topic: str, payload: bytes | str, *, received_at: int | None = None) -> bool:
        """Persist one event and then notify the Class A coordinator.

        Returns ``True`` only when a new canonical frame was inserted. Every
        accepted MQTT delivery notifies ``receive_window_observer`` because a
        replay still represents a Class A receive window. Immediate-alert
        observations are driven from a durable intent written in the same
        transaction as the uplink. Replays therefore reconcile a crash between
        ingest commit and observer execution, while completed intents do not
        retrigger. Non-alert observations retain first-insert semantics.
        """

        uplink = parse_uplink_event(topic, payload, self.registry)
        inserted = self.store.enqueue_uplink(uplink, received_at=received_at)
        if self._receive_window_observer is not None:
            self._receive_window_observer(uplink)
        if uplink.requires_immediate_alert:
            self.reconcile_alert_triggers(now=received_at, raise_on_error=True)
        elif inserted and self._uplink_observer is not None:
            self._uplink_observer(uplink)
        return inserted

    def reconcile_alert_triggers(
        self,
        *,
        now: int | None = None,
        limit: int = 100,
        raise_on_error: bool = False,
    ) -> int:
        """Apply durable immediate-alert intents and acknowledge each success.

        The observer boundary is intentionally at-least-once until its intent
        is acknowledged. The production LTE observer is itself idempotent, so
        a process loss after requesting the LTE window but before acknowledgement
        safely converges on restart.
        """

        observer = self._uplink_observer
        if observer is None:
            return 0
        timestamp = int(time.time()) if now is None else now
        triggers = self.store.claim_alert_triggers(
            self._alert_worker_id,
            now=timestamp,
            lease_s=30,
            limit=limit,
        )
        completed = 0
        for trigger in triggers:
            try:
                uplink = parse_uplink_event(
                    f"application/{trigger.application_id}/device/{trigger.dev_eui}/event/up",
                    trigger.envelope_json,
                    self.registry,
                )
                if uplink.message_id != trigger.message_id or not uplink.requires_immediate_alert:
                    raise ChirpStackError("durable alert trigger does not match its uplink")
                observer(uplink)
                if not self.store.mark_alert_trigger_completed(
                    trigger.message_id,
                    self._alert_worker_id,
                    now=timestamp,
                ):
                    raise ChirpStackError("durable alert trigger lease was lost")
                completed += 1
            except Exception:
                self.store.retry_alert_trigger(
                    trigger.message_id,
                    self._alert_worker_id,
                    failure_code="observer_failed",
                    retry_after_s=1,
                    now=timestamp,
                )
                if raise_on_error:
                    raise
        return completed

    def publish_maintenance_wake(
        self,
        identity: DeviceIdentity,
        payload: bytes,
        *,
        now: int | None = None,
    ) -> bool:
        """Queue only a valid authenticated wake on ChirpStack's downlink topic."""

        if identity.application_id != self.config.application_id:
            raise ChirpStackError("wake target is outside this MQTT application")
        if len(payload) != WAKE_SIZE:
            raise ChirpStackError(f"wake payload must be exactly {WAKE_SIZE} bytes")
        timestamp = int(time.time()) if now is None else now
        decode_wake(payload, key=identity.wake_key_bytes, now=timestamp)
        client = self._ensure_client()
        topic = f"application/{identity.application_id}/device/{identity.dev_eui}/command/down"
        body = json.dumps(
            {
                "confirmed": True,
                "data": base64.b64encode(payload).decode("ascii"),
                "devEui": identity.dev_eui,
                "fPort": identity.wake_f_port,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        result = client.publish(topic, body, qos=self.config.qos, retain=False)
        return int(getattr(result, "rc", result if isinstance(result, int) else -1)) == 0

    def connect(self) -> None:
        client = self._ensure_client()
        client.connect(self.config.host, self.config.port, self.config.keepalive_s)

    def run_forever(self) -> None:
        self._alert_stop.clear()
        if self._uplink_observer is not None:
            try:
                self.reconcile_alert_triggers(raise_on_error=True)
            except Exception as exc:
                self._report_error(exc)
            self._alert_thread = threading.Thread(
                target=self._run_alert_reconciler,
                name="edgewatch-lorawan-alert-reconciler",
                daemon=True,
            )
            self._alert_thread.start()
        try:
            self.connect()
            self._ensure_client().loop_forever()
        finally:
            self._alert_stop.set()
            thread = self._alert_thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=5)

    def stop(self) -> None:
        self._alert_stop.set()
        if self._client is None:
            return
        self._client.disconnect()

    def _run_alert_reconciler(self) -> None:
        while not self._alert_stop.is_set():
            completed = 0
            try:
                completed = self.reconcile_alert_triggers(raise_on_error=True)
            except Exception as exc:
                self._report_error(exc)
            self._alert_stop.wait(0.01 if completed else 1.0)

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            mqtt = importlib.import_module("paho.mqtt.client")
        except ImportError as exc:
            raise MqttDependencyError(
                "paho-mqtt is required only for the live ChirpStack MQTT bridge"
            ) from exc
        callback_version = getattr(getattr(mqtt, "CallbackAPIVersion", None), "VERSION2", None)
        if callback_version is None:
            client = mqtt.Client(client_id=self.config.client_id)
        else:
            client = mqtt.Client(callback_version, client_id=self.config.client_id)
        if self.config.username is not None:
            client.username_pw_set(self.config.username, self.config.password())
        if self.config.tls:
            client.tls_set()
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        self._client = client
        return client

    def _on_connect(self, client: Any, _userdata: Any, _flags: Any, reason_code: Any, *_rest: Any) -> None:
        failure = getattr(reason_code, "is_failure", None)
        if failure is None:
            try:
                failure = int(reason_code) != 0
            except (TypeError, ValueError):
                failure = True
        if bool(failure):
            self._report_error(ChirpStackError("MQTT broker rejected the connection"))
            return
        client.subscribe(self.config.uplink_topic, qos=self.config.qos)

    def _on_message(self, _client: Any, _userdata: Any, message: Any) -> None:
        try:
            self.handle_message(str(message.topic), bytes(message.payload))
        except Exception as exc:  # callback boundary must not terminate the MQTT loop
            self._report_error(exc)

    def _report_error(self, exc: Exception) -> None:
        if self._error_observer is not None:
            self._error_observer(exc)
