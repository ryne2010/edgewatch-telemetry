from __future__ import annotations

import logging
import math
import re
import stat
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

import yaml

from agent.telegram_transport import (
    TelegramTransport,
    TelegramTransportConfigError,
    load_telegram_transport_config,
)

from .chirpstack import ChirpStackBridge, ChirpStackError, ChirpStackUplink, MqttConnectionConfig
from .config import DeviceIdentity, DeviceRegistry, IdentityConfigError
from .maintenance import MaintenanceWakeCoordinator
from .radio import RadioIngressConfig, RadioIngressError, RadioIngressHealth, load_radio_ingress_config
from .store import GatewayStore, OutboxItem


class GatewayServiceConfigError(ValueError):
    """Raised when the private gateway service configuration is invalid."""


@dataclass(frozen=True)
class TelegramSinkConfig:
    chat_id: str
    token_file: Path
    timeout_s: float = 10.0
    disable_notification: bool = False
    protect_content: bool = True

    def __post_init__(self) -> None:
        if not self.chat_id.lstrip("-").isdigit():
            raise GatewayServiceConfigError("Telegram chat_id must be numeric")
        if not isinstance(self.token_file, Path):
            raise GatewayServiceConfigError("Telegram token_file must be a filesystem path")
        if (
            isinstance(self.timeout_s, bool)
            or not isinstance(self.timeout_s, (int, float))
            or not math.isfinite(float(self.timeout_s))
            or not 1 <= self.timeout_s <= 120
        ):
            raise GatewayServiceConfigError("Telegram timeout_s must be from 1 through 120")
        if not isinstance(self.disable_notification, bool) or not isinstance(self.protect_content, bool):
            raise GatewayServiceConfigError("Telegram boolean settings must be booleans")


@dataclass(frozen=True)
class OutboxWorkerConfig:
    poll_interval_s: float = 1.0
    lease_s: int = 60
    batch_size: int = 10
    retry_base_s: int = 30
    retry_max_s: int = 3_600

    def __post_init__(self) -> None:
        if (
            isinstance(self.poll_interval_s, bool)
            or not isinstance(self.poll_interval_s, (int, float))
            or not math.isfinite(float(self.poll_interval_s))
            or not 0.1 <= self.poll_interval_s <= 60
        ):
            raise GatewayServiceConfigError("outbox poll_interval_s must be from 0.1 through 60")
        for name, value, minimum, maximum in (
            ("lease_s", self.lease_s, 5, 3_600),
            ("batch_size", self.batch_size, 1, 100),
            ("retry_base_s", self.retry_base_s, 1, 3_600),
            ("retry_max_s", self.retry_max_s, 1, 86_400),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise GatewayServiceConfigError(f"outbox {name} must be from {minimum} through {maximum}")
        if self.retry_max_s < self.retry_base_s:
            raise GatewayServiceConfigError("outbox retry_max_s must be at least retry_base_s")


@dataclass(frozen=True)
class GatewayServiceConfig:
    registry_file: Path
    gateway_store_path: Path
    mqtt: MqttConnectionConfig
    telegram: TelegramSinkConfig
    outbox: OutboxWorkerConfig = OutboxWorkerConfig()
    radio_ingress: RadioIngressConfig | None = None


@dataclass(frozen=True)
class DeliveryOutcome:
    delivered: bool
    failure_code: str = "delivery_failed"
    retry_after_s: float | None = None
    permanent: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.delivered, bool) or not isinstance(self.permanent, bool):
            raise ValueError("delivery outcome flags must be booleans")
        if re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", self.failure_code) is None:
            raise ValueError("delivery failure_code must be a safe identifier")
        if self.retry_after_s is not None and (
            isinstance(self.retry_after_s, bool)
            or not isinstance(self.retry_after_s, (int, float))
            or not math.isfinite(float(self.retry_after_s))
            or self.retry_after_s <= 0
        ):
            raise ValueError("delivery retry_after_s must be a positive finite number")


@dataclass(frozen=True)
class OutboxRunResult:
    claimed: int = 0
    delivered: int = 0
    retried: int = 0
    lease_lost: int = 0


class CanonicalPointSink(Protocol):
    """Programmatic delivery boundary for canonical LoRaWAN telemetry points."""

    def deliver(self, device_id: str, point: Mapping[str, Any]) -> DeliveryOutcome: ...


def _mapping(value: object, *, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise GatewayServiceConfigError(f"{where} must be a mapping")
    return value


def _closed(value: object, *, where: str, allowed: set[str]) -> Mapping[str, Any]:
    result = _mapping(value, where=where)
    unknown = sorted(set(result) - allowed)
    if unknown:
        raise GatewayServiceConfigError(f"unknown key(s) in {where}: {', '.join(unknown)}")
    return result


def _string(value: object, *, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GatewayServiceConfigError(f"{where} must be a non-empty string")
    return value.strip()


def _boolean(value: object, *, where: str) -> bool:
    if not isinstance(value, bool):
        raise GatewayServiceConfigError(f"{where} must be a boolean")
    return value


def _integer(value: object, *, where: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise GatewayServiceConfigError(f"{where} must be from {minimum} through {maximum}")
    return value


def _number(value: object, *, where: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GatewayServiceConfigError(f"{where} must be a number")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise GatewayServiceConfigError(f"{where} must be from {minimum:g} through {maximum:g}")
    return result


def _resolve_path(value: object, *, where: str, base: Path) -> Path:
    raw = Path(_string(value, where=where)).expanduser()
    return raw if raw.is_absolute() else (base / raw).resolve()


def _private_file(path: Path, *, where: str) -> Path:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise GatewayServiceConfigError(f"{where} cannot be read") from exc
    if not path.is_file() or mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise GatewayServiceConfigError(f"{where} must be a regular file with mode 0600 or stricter")
    return path


def _load_private_yaml(path: Path, *, where: str) -> Mapping[str, Any]:
    _private_file(path, where=where)
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise GatewayServiceConfigError(f"{where} must contain valid UTF-8 YAML") from exc
    return _mapping(value, where=where)


def load_gateway_service_config(path: str | Path) -> tuple[GatewayServiceConfig, DeviceRegistry]:
    """Load a closed gateway configuration and a separate private OTAA registry."""

    config_path = Path(path).expanduser().resolve()
    root = _closed(
        _load_private_yaml(config_path, where="gateway config"),
        where="gateway config",
        allowed={
            "schema_version",
            "registry_file",
            "radio_ingress_file",
            "gateway_store_path",
            "mqtt",
            "delivery",
            "outbox",
        },
    )
    schema_version = root.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != 1:
        raise GatewayServiceConfigError("gateway config schema_version must be 1")
    base = config_path.parent
    registry_file = _private_file(
        _resolve_path(root.get("registry_file"), where="registry_file", base=base),
        where="registry_file",
    )
    try:
        registry = DeviceRegistry.from_mapping(_load_private_yaml(registry_file, where="registry_file"))
    except IdentityConfigError as exc:
        raise GatewayServiceConfigError("registry_file is invalid") from exc
    radio_ingress_file = _private_file(
        _resolve_path(root.get("radio_ingress_file"), where="radio_ingress_file", base=base),
        where="radio_ingress_file",
    )
    try:
        radio_ingress = load_radio_ingress_config(radio_ingress_file)
    except RadioIngressError as exc:
        raise GatewayServiceConfigError("radio_ingress_file is invalid") from exc

    mqtt_raw = _closed(
        root.get("mqtt"),
        where="mqtt",
        allowed={
            "host",
            "application_id",
            "port",
            "client_id",
            "username",
            "password_file",
            "tls",
            "keepalive_s",
            "qos",
        },
    )
    password_raw = mqtt_raw.get("password_file")
    password_file = (
        None
        if password_raw is None
        else _private_file(
            _resolve_path(password_raw, where="mqtt.password_file", base=base),
            where="mqtt.password_file",
        )
    )
    try:
        mqtt = MqttConnectionConfig(
            host=_string(mqtt_raw.get("host"), where="mqtt.host"),
            application_id=_string(mqtt_raw.get("application_id"), where="mqtt.application_id"),
            port=_integer(mqtt_raw.get("port", 1883), where="mqtt.port", minimum=1, maximum=65_535),
            client_id=_string(
                mqtt_raw.get("client_id", "edgewatch-lorawan-gateway"),
                where="mqtt.client_id",
            ),
            username=(
                None
                if mqtt_raw.get("username") is None
                else _string(mqtt_raw.get("username"), where="mqtt.username")
            ),
            password_file=password_file,
            tls=_boolean(mqtt_raw.get("tls", False), where="mqtt.tls"),
            keepalive_s=_integer(
                mqtt_raw.get("keepalive_s", 60),
                where="mqtt.keepalive_s",
                minimum=5,
                maximum=3_600,
            ),
            qos=_integer(mqtt_raw.get("qos", 1), where="mqtt.qos", minimum=0, maximum=2),
        )
    except (ChirpStackError, ValueError) as exc:
        raise GatewayServiceConfigError(str(exc)) from exc
    if registry.application_ids != frozenset({mqtt.application_id}):
        raise GatewayServiceConfigError("registry devices must all belong to the configured MQTT application")

    delivery = _closed(
        root.get("delivery"),
        where="delivery",
        allowed={
            "type",
            "chat_id",
            "token_file",
            "timeout_s",
            "disable_notification",
            "protect_content",
        },
    )
    if delivery.get("type") != "telegram":
        raise GatewayServiceConfigError("delivery.type must be telegram for the production runner")
    chat_id = _string(delivery.get("chat_id"), where="delivery.chat_id")
    if not chat_id.lstrip("-").isdigit():
        raise GatewayServiceConfigError("delivery.chat_id must be a numeric ID encoded as a string")
    token_file = _private_file(
        _resolve_path(delivery.get("token_file"), where="delivery.token_file", base=base),
        where="delivery.token_file",
    )
    telegram = TelegramSinkConfig(
        chat_id=chat_id,
        token_file=token_file,
        timeout_s=_number(
            delivery.get("timeout_s", 10.0),
            where="delivery.timeout_s",
            minimum=1.0,
            maximum=120.0,
        ),
        disable_notification=_boolean(
            delivery.get("disable_notification", False),
            where="delivery.disable_notification",
        ),
        protect_content=_boolean(delivery.get("protect_content", True), where="delivery.protect_content"),
    )

    outbox_raw = _closed(
        root.get("outbox", {}),
        where="outbox",
        allowed={"poll_interval_s", "lease_s", "batch_size", "retry_base_s", "retry_max_s"},
    )
    outbox = OutboxWorkerConfig(
        poll_interval_s=_number(
            outbox_raw.get("poll_interval_s", 1.0),
            where="outbox.poll_interval_s",
            minimum=0.1,
            maximum=60.0,
        ),
        lease_s=_integer(outbox_raw.get("lease_s", 60), where="outbox.lease_s", minimum=5, maximum=3_600),
        batch_size=_integer(
            outbox_raw.get("batch_size", 10),
            where="outbox.batch_size",
            minimum=1,
            maximum=100,
        ),
        retry_base_s=_integer(
            outbox_raw.get("retry_base_s", 30),
            where="outbox.retry_base_s",
            minimum=1,
            maximum=3_600,
        ),
        retry_max_s=_integer(
            outbox_raw.get("retry_max_s", 3_600),
            where="outbox.retry_max_s",
            minimum=1,
            maximum=86_400,
        ),
    )
    if outbox.retry_max_s < outbox.retry_base_s:
        raise GatewayServiceConfigError("outbox.retry_max_s must be at least retry_base_s")
    gateway_store_path = _resolve_path(root.get("gateway_store_path"), where="gateway_store_path", base=base)
    return (
        GatewayServiceConfig(
            registry_file=registry_file,
            gateway_store_path=gateway_store_path,
            mqtt=mqtt,
            telegram=telegram,
            outbox=outbox,
            radio_ingress=radio_ingress,
        ),
        registry,
    )


class TelegramPointSink:
    def __init__(self, config: TelegramSinkConfig):
        try:
            telegram_config = load_telegram_transport_config(
                {
                    "EDGEWATCH_TELEMETRY_TRANSPORT": "telegram",
                    "TELEGRAM_CHAT_ID": config.chat_id,
                    "TELEGRAM_BOT_TOKEN_FILE": str(config.token_file),
                    "TELEGRAM_TIMEOUT_S": str(config.timeout_s),
                    "TELEGRAM_DISABLE_NOTIFICATION": str(config.disable_notification).lower(),
                    "TELEGRAM_PROTECT_CONTENT": str(config.protect_content).lower(),
                }
            )
        except TelegramTransportConfigError as exc:
            raise GatewayServiceConfigError("Telegram telemetry delivery configuration is invalid") from exc
        self._transport = TelegramTransport(telegram_config)

    def deliver(self, device_id: str, point: Mapping[str, Any]) -> DeliveryOutcome:
        result = self._transport.send(device_id, point)
        if result.delivered:
            return DeliveryOutcome(True, failure_code="delivered")
        if result.permanent:
            return DeliveryOutcome(
                False,
                failure_code="telegram_permanent_payload_failure",
                retry_after_s=None,
                permanent=True,
            )
        status = result.status_code
        code = "telegram_retryable" if status is None else f"telegram_http_{status}"
        return DeliveryOutcome(False, failure_code=code, retry_after_s=result.retry_after_s)


class DurableOutboxWorker:
    def __init__(
        self,
        store: GatewayStore,
        sink: CanonicalPointSink,
        config: OutboxWorkerConfig,
        *,
        worker_id: str | None = None,
        delivery_ready: Callable[[], bool] | None = None,
        delivery_hold_acquire: Callable[[], None] | None = None,
        delivery_hold_release: Callable[[], None] | None = None,
    ) -> None:
        if (delivery_hold_acquire is None) != (delivery_hold_release is None):
            raise GatewayServiceConfigError(
                "outbox delivery hold acquire and release callbacks must be configured together"
            )
        self.store = store
        self.sink = sink
        self.config = config
        self.worker_id = worker_id or f"lorawan-outbox-{uuid.uuid4()}"
        self._delivery_ready = delivery_ready or (lambda: True)
        self._delivery_hold_acquire = delivery_hold_acquire
        self._delivery_hold_release = delivery_hold_release
        if re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", self.worker_id) is None:
            raise GatewayServiceConfigError("outbox worker_id must be a safe identifier")

    def process_once(self, *, now: int | None = None) -> OutboxRunResult:
        if not self._is_delivery_ready():
            return OutboxRunResult()
        timestamp = int(time.time()) if now is None else now
        items = self.store.claim_outbox(
            self.worker_id,
            now=timestamp,
            lease_s=self.config.lease_s,
            limit=self.config.batch_size,
        )
        delivered = 0
        retried = 0
        lease_lost = 0
        for item in items:
            outcome = self._deliver(item)
            if outcome.delivered:
                if self.store.mark_outbox_delivered(item.message_id, self.worker_id, now=timestamp):
                    delivered += 1
                else:
                    lease_lost += 1
                continue
            retry_s = self._retry_delay(item, outcome)
            if self.store.retry_outbox(
                item.message_id,
                self.worker_id,
                failure_code=outcome.failure_code,
                retry_after_s=retry_s,
                now=timestamp,
            ):
                retried += 1
            else:
                lease_lost += 1
        return OutboxRunResult(len(items), delivered, retried, lease_lost)

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            result = OutboxRunResult()
            try:
                result = self.process_once()
                if result.claimed:
                    logging.info(
                        "LoRaWAN outbox processed claimed=%s delivered=%s retried=%s lease_lost=%s",
                        result.claimed,
                        result.delivered,
                        result.retried,
                        result.lease_lost,
                    )
            except Exception:
                logging.exception("LoRaWAN outbox worker failed; durable leases will recover")
            stop.wait(0.01 if result.claimed else self.config.poll_interval_s)

    def _deliver(self, item: OutboxItem) -> DeliveryOutcome:
        acquired = False
        try:
            if self._delivery_hold_acquire is not None:
                self._delivery_hold_acquire()
                acquired = True
            if not self._is_delivery_ready():
                return DeliveryOutcome(
                    False,
                    failure_code="delivery_not_ready",
                    retry_after_s=self.config.poll_interval_s,
                )
            outcome = self.sink.deliver(item.device_id, item.payload)
        except Exception:
            return DeliveryOutcome(False, failure_code="delivery_callback_failed")
        finally:
            if acquired and self._delivery_hold_release is not None:
                try:
                    self._delivery_hold_release()
                except Exception:
                    logging.exception("LoRaWAN delivery hold release failed; its bounded TTL will expire")
        if not isinstance(outcome, DeliveryOutcome):
            return DeliveryOutcome(False, failure_code="delivery_callback_invalid")
        return outcome

    def _is_delivery_ready(self) -> bool:
        ready = self._delivery_ready()
        if not isinstance(ready, bool):
            raise RuntimeError("outbox delivery_ready callback must return a boolean")
        return ready

    def _retry_delay(self, item: OutboxItem, outcome: DeliveryOutcome) -> int:
        if outcome.permanent:
            return self.config.retry_max_s
        if outcome.retry_after_s is not None and math.isfinite(outcome.retry_after_s):
            return max(1, min(self.config.retry_max_s, math.ceil(outcome.retry_after_s)))
        exponent = min(max(0, item.attempts - 1), 16)
        return min(self.config.retry_max_s, self.config.retry_base_s * (2**exponent))


class GatewayService:
    """Live MQTT ingest plus independent durable canonical-point delivery worker."""

    def __init__(
        self,
        config: GatewayServiceConfig,
        registry: DeviceRegistry,
        *,
        sink: CanonicalPointSink | None = None,
        mqtt_client: Any | None = None,
        uplink_observer: Callable[[ChirpStackUplink], None] | None = None,
        delivery_ready: Callable[[], bool] | None = None,
        delivery_hold_acquire: Callable[[], None] | None = None,
        delivery_hold_release: Callable[[], None] | None = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.store = GatewayStore(config.gateway_store_path)
        self._stop = threading.Event()
        self._uplink_observer = uplink_observer
        self.radio_health = None if config.radio_ingress is None else RadioIngressHealth(config.radio_ingress)
        self.coordinator = MaintenanceWakeCoordinator(
            registry,
            self.store,
            self._publish_wake,
            worker_id=f"lorawan-wake-{uuid.uuid4()}",
        )
        self.bridge = ChirpStackBridge(
            config.mqtt,
            registry,
            self.store,
            mqtt_client=mqtt_client,
            uplink_observer=self._observe_new_uplink,
            receive_window_observer=self._handle_receive_window,
            error_observer=lambda exc: logging.warning("LoRaWAN MQTT event rejected: %s", exc),
        )
        self.outbox_worker = DurableOutboxWorker(
            self.store,
            sink or TelegramPointSink(config.telegram),
            config.outbox,
            delivery_ready=delivery_ready,
            delivery_hold_acquire=delivery_hold_acquire,
            delivery_hold_release=delivery_hold_release,
        )
        self._outbox_thread: threading.Thread | None = None
        self._radio_health_thread: threading.Thread | None = None

    def _publish_wake(self, identity: DeviceIdentity, payload: bytes, now: int) -> bool:
        return self.bridge.publish_maintenance_wake(identity, payload, now=now)

    def _handle_receive_window(self, uplink: ChirpStackUplink) -> None:
        self.coordinator.handle_uplink(uplink)

    def _observe_new_uplink(self, uplink: ChirpStackUplink) -> None:
        if self._uplink_observer is not None:
            self._uplink_observer(uplink)

    def run_forever(self) -> None:
        if self.radio_health is not None:
            self.radio_health.config.validate_installation()
            self.radio_health.assert_ready()
            self._radio_health_thread = threading.Thread(
                target=self._monitor_radio_health,
                name="edgewatch-lorawan-radio-health",
                daemon=True,
            )
            self._radio_health_thread.start()
        self._outbox_thread = threading.Thread(
            target=self.outbox_worker.run,
            args=(self._stop,),
            name="edgewatch-lorawan-outbox",
            daemon=True,
        )
        self._outbox_thread.start()
        try:
            self.bridge.run_forever()
        finally:
            self.stop()

    def _monitor_radio_health(self) -> None:
        health = self.radio_health
        if health is None:
            return
        interval_s = max(1.0, min(5.0, health.config.status_max_age_s / 2))
        while not self._stop.wait(interval_s):
            try:
                health.assert_ready()
            except RadioIngressError as exc:
                logging.critical("LoRaWAN radio ingress lost readiness: %s", exc)
                self.stop()
                return

    def stop(self) -> None:
        self._stop.set()
        self.bridge.stop()
        thread = self._outbox_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        radio_thread = self._radio_health_thread
        if radio_thread is not None and radio_thread is not threading.current_thread():
            radio_thread.join(timeout=5)
