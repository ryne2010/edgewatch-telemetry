"""LoRaWAN satellite protocol and gateway integration primitives.

The package deliberately exposes only the small telemetry uplink and authenticated
maintenance-wake surface. Media, shell access, and OTA artifacts are not LoRaWAN
protocol operations.
"""

from .chirpstack import (
    ChirpStackBridge,
    ChirpStackError,
    ChirpStackUplink,
    MqttConnectionConfig,
    MqttDependencyError,
    parse_uplink_event,
)
from .config import DeviceIdentity, DeviceRegistry, IdentityConfigError
from .maintenance import MaintenanceWakeCoordinator, WakeHandlingResult, WakeRequestError
from .protocol import (
    EquipmentState,
    HealthFlag,
    MessageType,
    ProtocolError,
    UplinkFrame,
    WakeFrame,
    canonical_message_id,
    decode_uplink,
    decode_wake,
    encode_uplink,
    encode_wake,
    model_digest_prefix,
)
from .store import AlertTrigger, GatewayStore, OutboxItem, StoreConflictError, WakeRecord
from .radio import (
    RadioIngressConfig,
    RadioIngressError,
    RadioIngressHealth,
    load_radio_ingress_config,
)
from .service import (
    CanonicalPointSink,
    DeliveryOutcome,
    DurableOutboxWorker,
    GatewayService,
    GatewayServiceConfig,
    GatewayServiceConfigError,
    OutboxRunResult,
    OutboxWorkerConfig,
    TelegramPointSink,
    TelegramSinkConfig,
    load_gateway_service_config,
)

__all__ = [
    "AlertTrigger",
    "ChirpStackBridge",
    "ChirpStackError",
    "ChirpStackUplink",
    "CanonicalPointSink",
    "DeviceIdentity",
    "DeviceRegistry",
    "DeliveryOutcome",
    "DurableOutboxWorker",
    "EquipmentState",
    "GatewayStore",
    "GatewayService",
    "GatewayServiceConfig",
    "GatewayServiceConfigError",
    "HealthFlag",
    "IdentityConfigError",
    "MaintenanceWakeCoordinator",
    "MessageType",
    "MqttConnectionConfig",
    "MqttDependencyError",
    "OutboxItem",
    "OutboxRunResult",
    "OutboxWorkerConfig",
    "ProtocolError",
    "RadioIngressConfig",
    "RadioIngressError",
    "RadioIngressHealth",
    "StoreConflictError",
    "TelegramPointSink",
    "TelegramSinkConfig",
    "UplinkFrame",
    "WakeFrame",
    "WakeHandlingResult",
    "WakeRecord",
    "WakeRequestError",
    "canonical_message_id",
    "decode_uplink",
    "decode_wake",
    "encode_uplink",
    "encode_wake",
    "model_digest_prefix",
    "parse_uplink_event",
    "load_gateway_service_config",
    "load_radio_ingress_config",
]
