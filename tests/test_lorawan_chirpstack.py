from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from agent.lorawan.chirpstack import (
    ChirpStackBridge,
    ChirpStackError,
    MqttConnectionConfig,
    MqttDependencyError,
    parse_uplink_event,
)
from agent.lorawan.config import DeviceIdentity, DeviceRegistry, IdentityConfigError
from agent.lorawan.protocol import (
    EquipmentState,
    HealthFlag,
    MessageType,
    UplinkFrame,
    encode_uplink,
    encode_wake,
)
from agent.lorawan.store import GatewayStore


NOW = 1_780_000_000
DEV_EUI = "0102030405060708"


def _identity(**overrides: Any) -> DeviceIdentity:
    values: dict[str, Any] = {
        "device_id": "camera-1",
        "application_id": "app-1",
        "dev_eui": DEV_EUI,
        "join_eui": "1122334455667788",
        "app_key": "11" * 16,
        "wake_key": "22" * 32,
    }
    values.update(overrides)
    return DeviceIdentity(**values)


def _registry() -> DeviceRegistry:
    return DeviceRegistry([_identity()])


def _frame(
    *,
    sequence: int = 7,
    flags: HealthFlag = HealthFlag.CAMERA_OK,
    message_type: MessageType = MessageType.HEALTH,
    equipment_state: EquipmentState = EquipmentState.RUNNING,
) -> bytes:
    return encode_uplink(
        UplinkFrame(
            message_type=message_type,
            sequence=sequence,
            timestamp=NOW,
            equipment_state=equipment_state,
            visual_confidence_pct=95,
            audio_confidence_pct=80,
            battery_mv=12_400,
            flags=flags,
            model_digest=bytes.fromhex("abcdef0123456789"),
        )
    )


def _event(frame: bytes | None = None, **overrides: Any) -> bytes:
    body: dict[str, Any] = {
        "deduplicationId": "network-dedupe-1",
        "deviceInfo": {"applicationId": "app-1", "devEui": DEV_EUI},
        "fPort": 10,
        "fCnt": 88,
        "data": base64.b64encode(frame or _frame()).decode("ascii"),
    }
    body.update(overrides)
    return json.dumps(body).encode()


def test_registry_models_unique_closed_otaa_identities_without_secret_repr() -> None:
    identity = _identity()
    registry = DeviceRegistry([identity])

    assert registry.by_dev_eui(DEV_EUI.upper()).device_id == "camera-1"
    assert registry.by_device_id("camera-1").dev_eui == DEV_EUI
    assert "11" * 16 not in repr(identity)
    assert "22" * 32 not in repr(identity)

    with pytest.raises(IdentityConfigError, match="AppKey"):
        DeviceRegistry([identity, _identity(device_id="camera-2", dev_eui="0102030405060709")])
    with pytest.raises(IdentityConfigError, match="unknown key"):
        DeviceRegistry.from_mapping(
            {
                "devices": {
                    "camera-1": {
                        "application_id": "app-1",
                        "dev_eui": DEV_EUI,
                        "join_eui": "11" * 8,
                        "app_key": "22" * 16,
                        "wake_key": "33" * 32,
                        "ota_url": "https://not-allowed.example",
                    }
                }
            }
        )


def test_chirpstack_event_maps_to_canonical_edgewatch_point() -> None:
    uplink = parse_uplink_event(
        f"application/app-1/device/{DEV_EUI}/event/up",
        _event(),
        _registry(),
    )

    assert uplink.device_id == "camera-1"
    assert uplink.message_id == uplink.canonical_point["message_id"]
    assert len(uplink.message_id) <= 64
    assert uplink.canonical_point["ts"] == "2026-05-28T20:26:40Z"
    assert "severity" not in uplink.canonical_point
    assert "alert_type" not in uplink.canonical_point
    assert uplink.canonical_point["metrics"] == {
        "lorawan_message_type": "health",
        "lorawan_sequence": 7,
        "lorawan_dev_eui": DEV_EUI,
        "equipment_state": "running",
        "visual_confidence": 0.95,
        "audio_anomaly_score": 0.8,
        "battery_v": 12.4,
        "power_input_out_of_range": False,
        "power_unsustainable": False,
        "low_battery": False,
        "sentinel_triggered": False,
        "camera_ok": True,
        "audio_ok": False,
        "maintenance_ready": False,
        "degraded": False,
        "model_version_digest": "abcdef0123456789",
    }


@pytest.mark.parametrize(
    ("topic", "payload", "match"),
    [
        (f"application/other/device/{DEV_EUI}/event/up", _event(), "application"),
        (f"application/app-1/device/{DEV_EUI}/event/up", _event(fPort=12), "fPort"),
        (
            f"application/app-1/device/{DEV_EUI}/event/up",
            _event(deviceInfo={"applicationId": "app-1", "devEui": "ff" * 8}),
            "devEui",
        ),
        (f"application/app-1/device/{DEV_EUI}/event/up", _event(data="%%%"), "base64"),
        (f"application/app-1/device/{DEV_EUI}/event/up/extra", _event(), "topic"),
    ],
)
def test_chirpstack_boundary_fails_closed(topic: str, payload: bytes, match: str) -> None:
    with pytest.raises(ChirpStackError, match=match):
        parse_uplink_event(topic, payload, _registry())


class _PublishResult:
    rc = 0


class _FakeMqttClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, int, bool]] = []
        self.subscribed: list[tuple[str, int]] = []
        self.connected: list[tuple[str, int, int]] = []
        self.disconnected = False

    def publish(self, topic: str, body: str, *, qos: int, retain: bool) -> _PublishResult:
        self.published.append((topic, body, qos, retain))
        return _PublishResult()

    def subscribe(self, topic: str, *, qos: int) -> None:
        self.subscribed.append((topic, qos))

    def connect(self, host: str, port: int, keepalive_s: int) -> None:
        self.connected.append((host, port, keepalive_s))

    def loop_forever(self) -> None:
        return

    def disconnect(self) -> None:
        self.disconnected = True


def test_bridge_persists_before_observer_and_dedupes_replay(tmp_path: Path) -> None:
    store = GatewayStore(tmp_path / "gateway.sqlite")
    observed: list[dict[str, int]] = []
    receive_windows: list[dict[str, int]] = []
    bridge = ChirpStackBridge(
        MqttConnectionConfig("127.0.0.1", "app-1"),
        _registry(),
        store,
        mqtt_client=_FakeMqttClient(),
        uplink_observer=lambda _uplink: observed.append(store.outbox_counts()),
        receive_window_observer=lambda _uplink: receive_windows.append(store.outbox_counts()),
    )
    topic = f"application/app-1/device/{DEV_EUI}/event/up"

    assert bridge.handle_message(topic, _event(), received_at=NOW)
    assert not bridge.handle_message(topic, _event(), received_at=NOW + 1)
    assert observed == [{"pending": 1, "sending": 0, "delivered": 0}]
    assert receive_windows == [
        {"pending": 1, "sending": 0, "delivered": 0},
        {"pending": 1, "sending": 0, "delivered": 0},
    ]


def test_alert_trigger_reconciles_crash_after_commit_on_redelivery(tmp_path: Path) -> None:
    path = tmp_path / "gateway.sqlite"
    topic = f"application/app-1/device/{DEV_EUI}/event/up"
    payload = _event(_frame(message_type=MessageType.EVENT, equipment_state=EquipmentState.FAULT))
    uplink = parse_uplink_event(topic, payload, _registry())
    crashed_store = GatewayStore(path)

    # This committed ingest models process loss immediately before observer execution.
    assert crashed_store.enqueue_uplink(uplink, received_at=NOW)
    assert crashed_store.alert_trigger_counts() == {
        "pending": 1,
        "processing": 0,
        "completed": 0,
    }

    observed: list[str] = []
    recovered_store = GatewayStore(path)
    bridge = ChirpStackBridge(
        MqttConnectionConfig("127.0.0.1", "app-1"),
        _registry(),
        recovered_store,
        mqtt_client=_FakeMqttClient(),
        uplink_observer=lambda item: observed.append(item.message_id),
    )

    assert not bridge.handle_message(topic, payload, received_at=NOW + 1)
    assert observed == [uplink.message_id]
    assert recovered_store.alert_trigger_counts() == {
        "pending": 0,
        "processing": 0,
        "completed": 1,
    }

    assert not bridge.handle_message(topic, payload, received_at=NOW + 2)
    assert observed == [uplink.message_id]


def test_alert_trigger_reconciles_after_restart_without_redelivery(tmp_path: Path) -> None:
    path = tmp_path / "gateway.sqlite"
    topic = f"application/app-1/device/{DEV_EUI}/event/up"
    payload = _event(_frame(flags=HealthFlag.SENTINEL_TRIGGERED))
    uplink = parse_uplink_event(topic, payload, _registry())
    assert GatewayStore(path).enqueue_uplink(uplink, received_at=NOW)

    observed: list[str] = []
    recovered_store = GatewayStore(path)
    client = _FakeMqttClient()
    bridge = ChirpStackBridge(
        MqttConnectionConfig("127.0.0.1", "app-1"),
        _registry(),
        recovered_store,
        mqtt_client=client,
        uplink_observer=lambda item: observed.append(item.message_id),
    )

    bridge.run_forever()

    assert client.connected == [("127.0.0.1", 1883, 60)]
    assert bridge.reconcile_alert_triggers(now=NOW + 2) == 0
    assert observed == [uplink.message_id]
    assert recovered_store.alert_trigger_counts()["completed"] == 1


def test_bridge_publishes_only_valid_authenticated_wake(tmp_path: Path) -> None:
    client = _FakeMqttClient()
    identity = _identity()
    bridge = ChirpStackBridge(
        MqttConnectionConfig("127.0.0.1", "app-1"),
        _registry(),
        GatewayStore(tmp_path / "gateway.sqlite"),
        mqtt_client=client,
    )
    payload = encode_wake(
        command_id="cmd-1",
        expires_at=NOW + 600,
        nonce=2,
        readiness_timeout_s=300,
        key=identity.wake_key_bytes,
    )

    assert bridge.publish_maintenance_wake(identity, payload, now=NOW)
    topic, body, qos, retain = client.published[0]
    assert topic == f"application/app-1/device/{DEV_EUI}/command/down"
    assert json.loads(body) == {
        "confirmed": True,
        "data": base64.b64encode(payload).decode("ascii"),
        "devEui": DEV_EUI,
        "fPort": 11,
    }
    assert (qos, retain) == (1, False)

    tampered = bytearray(payload)
    tampered[-1] ^= 1
    with pytest.raises(Exception, match="authentication"):
        bridge.publish_maintenance_wake(identity, bytes(tampered), now=NOW)


def test_live_bridge_fails_cleanly_when_optional_paho_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _missing(_name: str) -> Any:
        raise ImportError("not installed")

    monkeypatch.setattr("agent.lorawan.chirpstack.importlib.import_module", _missing)
    bridge = ChirpStackBridge(
        MqttConnectionConfig("127.0.0.1", "app-1"),
        _registry(),
        GatewayStore(tmp_path / "gateway.sqlite"),
    )
    with pytest.raises(MqttDependencyError, match="paho-mqtt"):
        bridge.connect()


def test_mqtt_password_must_be_private_and_paired_with_username(tmp_path: Path) -> None:
    password = tmp_path / "mqtt-password"
    password.write_text("secret", encoding="utf-8")
    password.chmod(0o644)
    with pytest.raises(ChirpStackError, match="0600"):
        MqttConnectionConfig("127.0.0.1", "app-1", username="gateway", password_file=password)
    password.chmod(0o600)
    config = MqttConnectionConfig("127.0.0.1", "app-1", username="gateway", password_file=password)
    assert config.password() == "secret"
    with pytest.raises(ChirpStackError, match="together"):
        MqttConnectionConfig("127.0.0.1", "app-1", username="gateway")
