from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest
import yaml

from agent.lorawan.__main__ import gateway_power_callbacks
from agent.lorawan.chirpstack import MqttConnectionConfig, parse_uplink_event
from agent.lorawan.config import DeviceIdentity, DeviceRegistry
from agent.lorawan.protocol import EquipmentState, HealthFlag, MessageType, UplinkFrame, encode_uplink
from agent.lorawan.radio import RadioIngressConfig, RadioIngressError, load_radio_ingress_config
from agent.lorawan.service import (
    DeliveryOutcome,
    DurableOutboxWorker,
    GatewayService,
    GatewayServiceConfig,
    GatewayServiceConfigError,
    OutboxWorkerConfig,
    TelegramSinkConfig,
    load_gateway_service_config,
)
from agent.lorawan.store import GatewayStore
from gateway_runtime.lte_power import GatewayLtePowerController, GatewayPowerConfig


DEV_EUI = "0102030405060708"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _identity() -> DeviceIdentity:
    return DeviceIdentity(
        device_id="camera-1",
        application_id="app-1",
        dev_eui=DEV_EUI,
        join_eui="1122334455667788",
        app_key="11" * 16,
        wake_key="22" * 32,
    )


def _write_private(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


def _service_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    registry = _write_private(
        tmp_path / "registry.yaml",
        yaml.safe_dump(
            {
                "devices": {
                    "camera-1": {
                        "application_id": "app-1",
                        "dev_eui": DEV_EUI,
                        "join_eui": "1122334455667788",
                        "app_key": "11" * 16,
                        "wake_key": "22" * 32,
                    }
                }
            }
        ),
    )
    radio = _write_private(
        tmp_path / "radio.yaml",
        yaml.safe_dump(
            {
                "schema_version": 1,
                "gateway_id": "aabbccddeeff0011",
                "region": "US915",
                "concentrator": "sx1302",
                "adapter_executable": str(tmp_path / "radio-adapter"),
                "adapter_sha256": "aa" * 32,
                "adapter_config_file": str(tmp_path / "radio-adapter.yaml"),
                "status_file": str(tmp_path / "radio-status.json"),
                "instance_file": str(tmp_path / "radio-instance.json"),
                "status_max_age_s": 30,
                "startup_timeout_s": 90,
            }
        ),
    )
    token = _write_private(tmp_path / "telemetry-token", "telegram-secret")
    config = _write_private(
        tmp_path / "gateway.yaml",
        yaml.safe_dump(
            {
                "schema_version": 1,
                "registry_file": registry.name,
                "radio_ingress_file": radio.name,
                "gateway_store_path": "state/gateway.sqlite",
                "mqtt": {"host": "127.0.0.1", "application_id": "app-1", "qos": 1},
                "delivery": {
                    "type": "telegram",
                    "chat_id": "-100123",
                    "token_file": token.name,
                    "protect_content": True,
                },
                "outbox": {
                    "poll_interval_s": 0.5,
                    "lease_s": 30,
                    "batch_size": 4,
                    "retry_base_s": 5,
                    "retry_max_s": 300,
                },
            }
        ),
    )
    return config, registry, token


def _uplink(
    now: int,
    *,
    sequence: int = 1,
    equipment_state: EquipmentState = EquipmentState.FAULT,
    flags: HealthFlag = HealthFlag.CAMERA_OK,
) -> Any:
    frame = encode_uplink(
        UplinkFrame(
            message_type=MessageType.EVENT,
            sequence=sequence,
            timestamp=now,
            equipment_state=equipment_state,
            visual_confidence_pct=98,
            audio_confidence_pct=88,
            battery_mv=12_100,
            flags=flags,
            model_digest=bytes.fromhex("0011223344556677"),
        )
    )
    event = json.dumps(
        {
            "deviceInfo": {"applicationId": "app-1", "devEui": DEV_EUI},
            "fPort": 10,
            "data": base64.b64encode(frame).decode("ascii"),
        }
    )
    return parse_uplink_event(
        f"application/app-1/device/{DEV_EUI}/event/up",
        event,
        DeviceRegistry([_identity()]),
    )


def test_private_service_config_loads_registry_mqtt_store_and_telegram(tmp_path: Path) -> None:
    config_path, registry_path, token_path = _service_files(tmp_path)

    config, registry = load_gateway_service_config(config_path)

    assert config.registry_file == registry_path
    assert config.radio_ingress is not None
    assert config.radio_ingress.gateway_id == "aabbccddeeff0011"
    assert config.gateway_store_path == tmp_path / "state/gateway.sqlite"
    assert config.mqtt.uplink_topic == "application/app-1/device/+/event/up"
    assert config.telegram.token_file == token_path
    assert config.telegram.chat_id == "-100123"
    assert config.outbox == OutboxWorkerConfig(
        poll_interval_s=0.5,
        lease_s=30,
        batch_size=4,
        retry_base_s=5,
        retry_max_s=300,
    )
    assert registry.by_device_id("camera-1").dev_eui == DEV_EUI


def test_service_and_registry_files_fail_closed_on_permissions_and_unknown_keys(
    tmp_path: Path,
) -> None:
    config_path, registry_path, _token_path = _service_files(tmp_path)
    config_path.chmod(0o644)
    with pytest.raises(GatewayServiceConfigError, match="0600"):
        load_gateway_service_config(config_path)

    config_path.chmod(0o600)
    registry_path.chmod(0o644)
    with pytest.raises(GatewayServiceConfigError, match="registry_file.*0600"):
        load_gateway_service_config(config_path)

    registry_path.chmod(0o600)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw["schema_version"] = True
    config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(GatewayServiceConfigError, match="schema_version"):
        load_gateway_service_config(config_path)

    raw["schema_version"] = 1
    raw["arbitrary_downlink"] = True
    config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(GatewayServiceConfigError, match="unknown key"):
        load_gateway_service_config(config_path)


class _Sink:
    def __init__(
        self,
        outcomes: list[DeliveryOutcome] | None = None,
        *,
        on_deliver: Callable[[], None] | None = None,
    ) -> None:
        self.outcomes = list(outcomes or [DeliveryOutcome(True)])
        self.points: list[tuple[str, Mapping[str, Any]]] = []
        self.on_deliver = on_deliver

    def deliver(self, device_id: str, point: Mapping[str, Any]) -> DeliveryOutcome:
        if self.on_deliver is not None:
            self.on_deliver()
        self.points.append((device_id, point))
        return self.outcomes.pop(0)


def test_durable_outbox_worker_delivers_and_retries_without_losing_points(tmp_path: Path) -> None:
    now = int(time.time())
    store = GatewayStore(tmp_path / "gateway.sqlite")
    first = _uplink(now, sequence=1)
    second = _uplink(now, sequence=2)
    store.enqueue_uplink(first, received_at=now)
    store.enqueue_uplink(second, received_at=now)
    sink = _Sink(
        [
            DeliveryOutcome(False, failure_code="telegram_http_429", retry_after_s=17),
            DeliveryOutcome(True),
        ]
    )
    worker = DurableOutboxWorker(
        store,
        sink,
        OutboxWorkerConfig(lease_s=30, batch_size=2, retry_base_s=5, retry_max_s=300),
        worker_id="worker",
    )

    result = worker.process_once(now=now)

    assert result.claimed == 2
    assert result.delivered == 1
    assert result.retried == 1
    assert store.outbox_counts() == {"pending": 1, "sending": 0, "delivered": 1}
    assert store.claim_outbox("probe", now=now + 16) == ()
    assert len(store.claim_outbox("probe", now=now + 17)) == 1
    assert {device_id for device_id, _point in sink.points} == {"camera-1"}


def test_durable_outbox_waits_without_claiming_while_delivery_is_offline(tmp_path: Path) -> None:
    now = int(time.time())
    store = GatewayStore(tmp_path / "gateway.sqlite")
    store.enqueue_uplink(_uplink(now), received_at=now)
    sink = _Sink()
    ready = False
    worker = DurableOutboxWorker(
        store,
        sink,
        OutboxWorkerConfig(lease_s=30, batch_size=1),
        worker_id="worker",
        delivery_ready=lambda: ready,
    )

    blocked = worker.process_once(now=now)
    assert blocked.claimed == 0
    assert store.outbox_counts() == {"pending": 1, "sending": 0, "delivered": 0}
    assert sink.points == []

    ready = True
    result = worker.process_once(now=now)
    assert result.claimed == 1
    assert result.delivered == 1
    assert store.outbox_counts() == {"pending": 0, "sending": 0, "delivered": 1}


class _FakeMqttClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, int, bool]] = []

    def publish(self, topic: str, body: str, *, qos: int, retain: bool) -> int:
        self.published.append((topic, body, qos, retain))
        return 0

    def disconnect(self) -> None:
        return None


def test_gateway_service_wires_mqtt_wakes_and_callback_delivery(tmp_path: Path) -> None:
    now = int(time.time())
    registry = DeviceRegistry([_identity()])
    token = _write_private(tmp_path / "token", "secret")
    config = GatewayServiceConfig(
        registry_file=tmp_path / "registry.yaml",
        gateway_store_path=tmp_path / "gateway.sqlite",
        mqtt=MqttConnectionConfig("127.0.0.1", "app-1"),
        telegram=TelegramSinkConfig("-100123", token),
        outbox=OutboxWorkerConfig(batch_size=1),
    )
    mqtt = _FakeMqttClient()
    sink = _Sink()
    service = GatewayService(config, registry, sink=sink, mqtt_client=mqtt)
    service.coordinator.request_wake(
        "cmd-1",
        "camera-1",
        expires_at=now + 600,
        readiness_timeout_s=120,
        now=now,
        nonce=7,
    )
    uplink = _uplink(now)
    body = json.dumps(
        {
            "deviceInfo": {"applicationId": "app-1", "devEui": DEV_EUI},
            "fPort": 10,
            "data": base64.b64encode(uplink.frame_bytes).decode("ascii"),
        }
    )

    assert service.bridge.handle_message(
        f"application/app-1/device/{DEV_EUI}/event/up", body, received_at=now
    )
    assert service.store.get_wake("cmd-1").state == "waiting_ready"  # type: ignore[union-attr]
    assert mqtt.published[0][0] == f"application/app-1/device/{DEV_EUI}/command/down"
    result = service.outbox_worker.process_once(now=now)
    assert result.delivered == 1
    assert sink.points[0][0] == "camera-1"
    assert sink.points[0][1]["severity"] == "critical"
    assert sink.points[0][1]["alert_type"] == "EQUIPMENT_FAULT"


def test_alert_uplink_persists_before_trigger_and_waits_for_lte_window(tmp_path: Path) -> None:
    now = int(time.time())
    registry = DeviceRegistry([_identity()])
    token = _write_private(tmp_path / "token", "secret")
    config = GatewayServiceConfig(
        registry_file=tmp_path / "registry.yaml",
        gateway_store_path=tmp_path / "gateway.sqlite",
        mqtt=MqttConnectionConfig("127.0.0.1", "app-1"),
        telegram=TelegramSinkConfig("-100123", token),
        outbox=OutboxWorkerConfig(batch_size=1),
    )
    power_config = GatewayPowerConfig(
        mode="observe",
        trigger_path=tmp_path / "lte-trigger.json",
        state_path=tmp_path / "lte-state.json",
        hold_dir=tmp_path / "lte-holds",
    )
    power = GatewayLtePowerController(power_config, clock=lambda: float(now))
    power_observer, delivery_ready, hold_acquire, hold_release = gateway_power_callbacks(power)
    callback_state: list[tuple[dict[str, int], str]] = []
    service_ref: list[GatewayService] = []

    def observer(uplink: Any) -> None:
        service = service_ref[0]
        wake = service.store.get_wake("cmd-alert")
        callback_state.append((service.store.outbox_counts(), "" if wake is None else wake.state))
        power_observer(uplink)

    hold_seen_during_delivery: list[bool] = []
    sink = _Sink(on_deliver=lambda: hold_seen_during_delivery.append(power.has_active_holds()))
    mqtt = _FakeMqttClient()
    service = GatewayService(
        config,
        registry,
        sink=sink,
        mqtt_client=mqtt,
        uplink_observer=observer,
        delivery_ready=delivery_ready,
        delivery_hold_acquire=hold_acquire,
        delivery_hold_release=hold_release,
    )
    service_ref.append(service)
    service.coordinator.request_wake(
        "cmd-alert",
        "camera-1",
        expires_at=now + 600,
        readiness_timeout_s=120,
        now=now,
        nonce=9,
    )
    uplink = _uplink(now, flags=HealthFlag.SENTINEL_TRIGGERED)
    body = json.dumps(
        {
            "deviceInfo": {"applicationId": "app-1", "devEui": DEV_EUI},
            "fPort": 10,
            "data": base64.b64encode(uplink.frame_bytes).decode("ascii"),
        }
    )

    assert service.bridge.handle_message(
        f"application/app-1/device/{DEV_EUI}/event/up", body, received_at=now
    )
    assert callback_state == [({"pending": 1, "sending": 0, "delivered": 0}, "waiting_ready")]
    assert power_config.trigger_path.exists()
    power_config.trigger_path.unlink()
    assert not service.bridge.handle_message(
        f"application/app-1/device/{DEV_EUI}/event/up", body, received_at=now + 1
    )
    assert callback_state == [({"pending": 1, "sending": 0, "delivered": 0}, "waiting_ready")]
    assert not power_config.trigger_path.exists()
    power.request_immediate("alert")
    assert service.outbox_worker.process_once(now=now).claimed == 0
    assert sink.points == []

    restarted_power = GatewayLtePowerController(power_config, clock=lambda: float(now + 1))
    assert restarted_power.next_reason() == "alert"
    restarted_power.open_window("alert")
    assert service.outbox_worker.process_once(now=now + 1).delivered == 1
    assert len(sink.points) == 1
    assert hold_seen_during_delivery == [True]
    assert power.has_active_holds() is False


def test_disabled_lte_scheduler_preserves_always_online_delivery(tmp_path: Path) -> None:
    now = int(time.time())
    power_config = GatewayPowerConfig(
        mode="disabled",
        trigger_path=tmp_path / "lte-trigger.json",
        state_path=tmp_path / "lte-state.json",
        hold_dir=tmp_path / "lte-holds",
    )
    observer, delivery_ready, hold_acquire, hold_release = gateway_power_callbacks(
        GatewayLtePowerController(power_config)
    )

    observer(_uplink(now, equipment_state=EquipmentState.FAULT))
    hold_acquire()
    hold_release()

    assert delivery_ready() is True
    assert not power_config.trigger_path.exists()


def test_production_service_refuses_to_run_without_fresh_radio_ingress(tmp_path: Path) -> None:
    registry = DeviceRegistry([_identity()])
    token = _write_private(tmp_path / "token", "secret")
    adapter = tmp_path / "adapter"
    adapter.write_bytes(b"test adapter")
    adapter.chmod(0o700)
    adapter_config = _write_private(tmp_path / "adapter.yaml", "test: true\n")
    radio = RadioIngressConfig(
        gateway_id="aabbccddeeff0011",
        adapter_executable=adapter,
        adapter_sha256=hashlib.sha256(adapter.read_bytes()).hexdigest(),
        adapter_config_file=adapter_config,
        status_file=tmp_path / "missing-status.json",
        instance_file=tmp_path / "missing-instance.json",
    )
    config = GatewayServiceConfig(
        registry_file=tmp_path / "registry.yaml",
        gateway_store_path=tmp_path / "gateway.sqlite",
        mqtt=MqttConnectionConfig("127.0.0.1", "app-1"),
        telegram=TelegramSinkConfig("-100123", token),
        radio_ingress=radio,
    )
    service = GatewayService(
        config,
        registry,
        sink=_Sink(),
        mqtt_client=_FakeMqttClient(),
    )

    with pytest.raises(RadioIngressError, match="instance file"):
        service.run_forever()


def test_gateway_deploy_examples_match_the_production_runner_contract(tmp_path: Path) -> None:
    deploy = REPOSITORY_ROOT / "deploy" / "rpi" / "gateway"
    registry_raw = yaml.safe_load((deploy / "lorawan-registry.example.yaml").read_text(encoding="utf-8"))
    gateway_raw = yaml.safe_load((deploy / "lorawan-gateway.example.yaml").read_text(encoding="utf-8"))
    unit = (deploy / "edgewatch-lorawan-gateway.service").read_text(encoding="utf-8")
    radio_unit = (deploy / "edgewatch-lorawan-radio-ingress.service").read_text(encoding="utf-8")
    radio_config_path = _write_private(
        tmp_path / "radio.yaml",
        (deploy / "lorawan-radio-ingress.example.yaml").read_text(encoding="utf-8"),
    )

    registry = DeviceRegistry.from_mapping(registry_raw)
    radio = load_radio_ingress_config(radio_config_path)
    assert len(registry.devices) == 2
    assert registry.application_ids == frozenset({gateway_raw["mqtt"]["application_id"]})
    assert gateway_raw["schema_version"] == 1
    assert gateway_raw["radio_ingress_file"].endswith("lorawan-radio-ingress.yaml")
    assert gateway_raw["delivery"]["type"] == "telegram"
    assert radio.region == "US915"
    assert radio.concentrator == "sx1302"
    assert "EnvironmentFile=-/etc/edgewatch-controller/gateway-power.env" in unit
    assert "BindsTo=edgewatch-lorawan-radio-ingress.service" in unit
    assert "-m agent.lorawan --config /etc/edgewatch-controller/lorawan-gateway.yaml" in unit
    assert "-m agent.lorawan.radio_cli run" in radio_unit
    assert "-m agent.lorawan.radio_cli check" in radio_unit
