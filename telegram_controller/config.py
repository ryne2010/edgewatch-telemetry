from __future__ import annotations

import os
import ipaddress
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .models import Device, Fleet, Principal, Role


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class TelegramConfig:
    token_file: Path
    poll_timeout_s: int = 30
    request_timeout_s: int = 40

    @property
    def control_bot_token_file(self) -> Path:
        return self.token_file


@dataclass(frozen=True)
class SSHConfig:
    device_key_file: Path
    known_hosts_file: Path
    username: str = "ryne"
    connect_timeout_s: int = 10
    command_timeout_s: int = 60
    spacebridge_identity_file: Path | None = None
    spacebridge_host: str = "tunnel.hologram.io"
    spacebridge_user: str = "htunnel"
    spacebridge_port: int = 999

    @property
    def private_key_file(self) -> Path:
        return self.device_key_file


@dataclass(frozen=True)
class OTAConfig:
    catalog_file: Path
    rollout_percentages: tuple[int, ...] = (10, 50, 100)
    failure_rate_threshold: float = 0.10
    defer_rate_threshold: float = 0.25


@dataclass(frozen=True)
class MaintenanceConfig:
    registry_file: Path
    gateway_store_path: Path
    readiness_timeout_s: int = 300


@dataclass(frozen=True)
class ArtifactCacheConfig:
    directory: Path
    bind_host: str
    port: int = 8091
    max_artifact_bytes: int = 512 * 1024 * 1024
    max_total_bytes: int = 2 * 1024 * 1024 * 1024
    max_objects: int = 16
    minimum_free_bytes: int = 256 * 1024 * 1024
    download_timeout_s: int = 60
    http_max_connections: int = 4
    http_socket_timeout_s: int = 30

    @property
    def base_url(self) -> str:
        return f"http://{self.bind_host}:{self.port}"


@dataclass(frozen=True)
class ControllerConfig:
    telegram: TelegramConfig
    ssh: SSHConfig
    database_path: Path
    principals: Mapping[str, Principal]
    devices: Mapping[str, Device]
    fleets: Mapping[str, Fleet]
    allowed_chats: frozenset[str]
    ota: OTAConfig | None = None
    maintenance: MaintenanceConfig | None = None
    artifact_cache: ArtifactCacheConfig | None = None
    confirmation_ttl_s: int = 120
    command_ttl_s: int = 300
    fleet_dispatch_concurrency: int = 4
    accepted_poll_interval_s: int = 2
    shutdown_enabled: bool = False


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise ConfigError(f"{where} must be a mapping")
    return value


def _only(data: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"unknown key(s) in {where}: {', '.join(unknown)}")


def _numeric_id(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.lstrip("-").isdigit():
        raise ConfigError(f"{where} must be a numeric ID encoded as a string")
    return value


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where} must be a non-empty string")
    return value.strip()


def _secret_file(value: Any, where: str) -> Path:
    path = Path(_string(value, where)).expanduser()
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise ConfigError(f"{where} cannot be read") from exc
    if not path.is_file() or mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ConfigError(f"{where} must be a regular file with mode 0600 or stricter")
    return path


def _plain_file(value: Any, where: str) -> Path:
    path = Path(_string(value, where)).expanduser()
    if not path.is_file():
        raise ConfigError(f"{where} must reference an existing file")
    return path


def load_config(path: str | os.PathLike[str]) -> ControllerConfig:
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError("controller configuration could not be loaded") from exc
    root = _mapping(raw, "root")
    _only(
        root,
        {
            "telegram",
            "storage",
            "ssh",
            "authorization",
            "devices",
            "fleets",
            "controller",
            "ota",
            "maintenance",
            "artifact_cache",
        },
        "root",
    )

    telegram_raw = _mapping(root.get("telegram"), "telegram")
    _only(
        telegram_raw,
        {"token_file", "control_bot_token_file", "poll_timeout_s", "request_timeout_s"},
        "telegram",
    )
    token_keys = [key for key in ("token_file", "control_bot_token_file") if key in telegram_raw]
    if len(token_keys) != 1:
        raise ConfigError("telegram requires exactly one control-bot token file reference")
    telegram = TelegramConfig(
        token_file=_secret_file(telegram_raw[token_keys[0]], f"telegram.{token_keys[0]}"),
        poll_timeout_s=_positive_int(telegram_raw.get("poll_timeout_s", 30), "telegram.poll_timeout_s"),
        request_timeout_s=_positive_int(
            telegram_raw.get("request_timeout_s", 40), "telegram.request_timeout_s"
        ),
    )
    if telegram.token_file.read_text(encoding="utf-8").strip() == "":
        raise ConfigError("telegram.token_file is empty")

    storage = _mapping(root.get("storage"), "storage")
    _only(storage, {"database_path"}, "storage")
    database_path = Path(_string(storage.get("database_path"), "storage.database_path")).expanduser()

    ssh_raw = _mapping(root.get("ssh"), "ssh")
    _only(
        ssh_raw,
        {
            "device_key_file",
            "private_key_file",
            "known_hosts_file",
            "username",
            "connect_timeout_s",
            "command_timeout_s",
            "spacebridge_identity_file",
            "spacebridge_host",
            "spacebridge_user",
            "spacebridge_port",
        },
        "ssh",
    )
    key_names = [key for key in ("device_key_file", "private_key_file") if key in ssh_raw]
    if len(key_names) != 1:
        raise ConfigError("ssh requires exactly one device private-key file reference")
    spacebridge_identity_raw = ssh_raw.get("spacebridge_identity_file")
    ssh = SSHConfig(
        device_key_file=_secret_file(ssh_raw[key_names[0]], f"ssh.{key_names[0]}"),
        known_hosts_file=_plain_file(ssh_raw.get("known_hosts_file"), "ssh.known_hosts_file"),
        username=_string(ssh_raw.get("username", "ryne"), "ssh.username"),
        connect_timeout_s=_positive_int(ssh_raw.get("connect_timeout_s", 10), "ssh.connect_timeout_s"),
        command_timeout_s=_positive_int(ssh_raw.get("command_timeout_s", 60), "ssh.command_timeout_s"),
        spacebridge_identity_file=(
            None
            if spacebridge_identity_raw is None
            else _secret_file(spacebridge_identity_raw, "ssh.spacebridge_identity_file")
        ),
        spacebridge_host=_string(
            ssh_raw.get("spacebridge_host", "tunnel.hologram.io"), "ssh.spacebridge_host"
        ),
        spacebridge_user=_string(ssh_raw.get("spacebridge_user", "htunnel"), "ssh.spacebridge_user"),
        spacebridge_port=_port(ssh_raw.get("spacebridge_port", 999), "ssh.spacebridge_port"),
    )

    auth = _mapping(root.get("authorization"), "authorization")
    _only(auth, {"allowed_chats", "users"}, "authorization")
    chats_raw = auth.get("allowed_chats")
    if not isinstance(chats_raw, list) or not chats_raw:
        raise ConfigError("authorization.allowed_chats must be a non-empty list")
    allowed_chats = frozenset(_numeric_id(item, "authorization.allowed_chats[]") for item in chats_raw)
    users_raw = _mapping(auth.get("users"), "authorization.users")
    principals: dict[str, Principal] = {}
    for user_id_raw, value in users_raw.items():
        user_id = _numeric_id(user_id_raw, "authorization.users key")
        user = _mapping(value, f"authorization.users.{user_id}")
        _only(user, {"role", "fleets"}, f"authorization.users.{user_id}")
        try:
            role = Role.parse(_string(user.get("role"), f"authorization.users.{user_id}.role"))
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        fleet_scope = user.get("fleets", [])
        if not isinstance(fleet_scope, list) or not all(isinstance(v, str) and v for v in fleet_scope):
            raise ConfigError(f"authorization.users.{user_id}.fleets must be a string list")
        principals[user_id] = Principal(user_id, role, frozenset(fleet_scope))

    devices = _load_devices(root.get("devices"))
    fleets = _load_fleets(root.get("fleets"), devices)
    for principal in principals.values():
        missing = principal.fleets - fleets.keys()
        if missing:
            raise ConfigError(
                f"user {principal.user_id} references unknown fleet(s): {', '.join(sorted(missing))}"
            )

    ota = _load_ota(root.get("ota"))
    maintenance = _load_maintenance(root.get("maintenance"))
    artifact_cache = _load_artifact_cache(root.get("artifact_cache"))
    if any(device.transport == "maintenance_via_lora" for device in devices.values()):
        if maintenance is None:
            raise ConfigError("maintenance_via_lora devices require maintenance configuration")
    if (
        any(
            device.transport == "maintenance_via_lora" and "ota" in device.capabilities
            for device in devices.values()
        )
        and artifact_cache is None
    ):
        raise ConfigError("OTA-capable maintenance devices require artifact_cache configuration")

    controller = _mapping(root.get("controller", {}), "controller")
    _only(
        controller,
        {
            "confirmation_ttl_s",
            "command_ttl_s",
            "fleet_dispatch_concurrency",
            "accepted_poll_interval_s",
            "shutdown_enabled",
        },
        "controller",
    )
    shutdown_enabled = controller.get("shutdown_enabled", False)
    if not isinstance(shutdown_enabled, bool):
        raise ConfigError("controller.shutdown_enabled must be a boolean")
    return ControllerConfig(
        telegram=telegram,
        ssh=ssh,
        database_path=database_path,
        principals=principals,
        devices=devices,
        fleets=fleets,
        allowed_chats=allowed_chats,
        ota=ota,
        maintenance=maintenance,
        artifact_cache=artifact_cache,
        confirmation_ttl_s=_positive_int(
            controller.get("confirmation_ttl_s", 120), "controller.confirmation_ttl_s"
        ),
        command_ttl_s=_positive_int(controller.get("command_ttl_s", 300), "controller.command_ttl_s"),
        fleet_dispatch_concurrency=_bounded_positive_int(
            controller.get("fleet_dispatch_concurrency", 4),
            "controller.fleet_dispatch_concurrency",
            maximum=32,
        ),
        accepted_poll_interval_s=_bounded_positive_int(
            controller.get("accepted_poll_interval_s", 2),
            "controller.accepted_poll_interval_s",
            maximum=300,
        ),
        shutdown_enabled=shutdown_enabled,
    )


def _positive_int(value: Any, where: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"{where} must be a positive integer")
    return value


def _bounded_positive_int(value: Any, where: str, *, maximum: int) -> int:
    result = _positive_int(value, where)
    if result > maximum:
        raise ConfigError(f"{where} must be at most {maximum}")
    return result


def _bounded_nonnegative_int(value: Any, where: str, *, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConfigError(f"{where} must be a non-negative integer")
    if value > maximum:
        raise ConfigError(f"{where} must be at most {maximum}")
    return value


def _port(value: Any, where: str) -> int:
    port = _positive_int(value, where)
    if port > 65535:
        raise ConfigError(f"{where} must be at most 65535")
    return port


def _rate(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{where} must be a number from 0 through 1")
    result = float(value)
    if not 0 <= result <= 1:
        raise ConfigError(f"{where} must be a number from 0 through 1")
    return result


def _load_ota(value: Any) -> OTAConfig | None:
    if value is None:
        return None
    raw = _mapping(value, "ota")
    _only(
        raw,
        {
            "catalog_file",
            "rollout_percentages",
            "failure_rate_threshold",
            "defer_rate_threshold",
        },
        "ota",
    )
    percentages_raw = raw.get("rollout_percentages", [10, 50, 100])
    if (
        not isinstance(percentages_raw, list)
        or not percentages_raw
        or any(
            isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100
            for value in percentages_raw
        )
    ):
        raise ConfigError("ota.rollout_percentages must contain integers from 1 through 100")
    percentages = tuple(percentages_raw)
    if tuple(sorted(set(percentages))) != percentages or percentages[-1] != 100:
        raise ConfigError("ota.rollout_percentages must be strictly increasing and end at 100")
    return OTAConfig(
        catalog_file=_plain_file(raw.get("catalog_file"), "ota.catalog_file"),
        rollout_percentages=percentages,
        failure_rate_threshold=_rate(raw.get("failure_rate_threshold", 0.10), "ota.failure_rate_threshold"),
        defer_rate_threshold=_rate(raw.get("defer_rate_threshold", 0.25), "ota.defer_rate_threshold"),
    )


def _load_maintenance(value: Any) -> MaintenanceConfig | None:
    if value is None:
        return None
    raw = _mapping(value, "maintenance")
    _only(raw, {"registry_file", "gateway_store_path", "readiness_timeout_s"}, "maintenance")
    return MaintenanceConfig(
        registry_file=_secret_file(raw.get("registry_file"), "maintenance.registry_file"),
        gateway_store_path=Path(
            _string(raw.get("gateway_store_path"), "maintenance.gateway_store_path")
        ).expanduser(),
        readiness_timeout_s=_bounded_positive_int(
            raw.get("readiness_timeout_s", 300),
            "maintenance.readiness_timeout_s",
            maximum=3600,
        ),
    )


def _load_artifact_cache(value: Any) -> ArtifactCacheConfig | None:
    if value is None:
        return None
    raw = _mapping(value, "artifact_cache")
    _only(
        raw,
        {
            "directory",
            "bind_host",
            "port",
            "max_artifact_bytes",
            "max_total_bytes",
            "max_objects",
            "minimum_free_bytes",
            "download_timeout_s",
            "http_max_connections",
            "http_socket_timeout_s",
        },
        "artifact_cache",
    )
    bind_host = _string(raw.get("bind_host"), "artifact_cache.bind_host")
    try:
        address = ipaddress.ip_address(bind_host)
    except ValueError as exc:
        raise ConfigError("artifact_cache.bind_host must be an IP address") from exc
    if (
        address.version != 4
        or not address.is_private
        or address.is_unspecified
        or address.is_multicast
        or address.is_loopback
        or address.is_link_local
    ):
        raise ConfigError(
            "artifact_cache.bind_host must be a private maintenance IPv4 address that is "
            "non-loopback and non-link-local"
        )
    max_artifact_bytes = _bounded_positive_int(
        raw.get("max_artifact_bytes", 512 * 1024 * 1024),
        "artifact_cache.max_artifact_bytes",
        maximum=4 * 1024 * 1024 * 1024,
    )
    max_total_bytes = _bounded_positive_int(
        raw.get("max_total_bytes", 2 * 1024 * 1024 * 1024),
        "artifact_cache.max_total_bytes",
        maximum=16 * 1024 * 1024 * 1024,
    )
    if max_total_bytes < max_artifact_bytes:
        raise ConfigError("artifact_cache.max_total_bytes must be at least max_artifact_bytes")
    return ArtifactCacheConfig(
        directory=Path(_string(raw.get("directory"), "artifact_cache.directory")).expanduser(),
        bind_host=bind_host,
        port=_port(raw.get("port", 8091), "artifact_cache.port"),
        max_artifact_bytes=max_artifact_bytes,
        max_total_bytes=max_total_bytes,
        max_objects=_bounded_positive_int(
            raw.get("max_objects", 16), "artifact_cache.max_objects", maximum=1024
        ),
        minimum_free_bytes=_bounded_nonnegative_int(
            raw.get("minimum_free_bytes", 256 * 1024 * 1024),
            "artifact_cache.minimum_free_bytes",
            maximum=16 * 1024 * 1024 * 1024,
        ),
        download_timeout_s=_bounded_positive_int(
            raw.get("download_timeout_s", 60),
            "artifact_cache.download_timeout_s",
            maximum=3600,
        ),
        http_max_connections=_bounded_positive_int(
            raw.get("http_max_connections", 4),
            "artifact_cache.http_max_connections",
            maximum=64,
        ),
        http_socket_timeout_s=_bounded_positive_int(
            raw.get("http_socket_timeout_s", 30),
            "artifact_cache.http_socket_timeout_s",
            maximum=300,
        ),
    )


def _load_devices(value: Any) -> dict[str, Device]:
    raw = _mapping(value, "devices")
    result: dict[str, Device] = {}
    for device_id, item_raw in raw.items():
        item = _mapping(item_raw, f"devices.{device_id}")
        _only(
            item,
            {"fleet", "host", "transport", "capabilities", "enabled", "metadata"},
            f"devices.{device_id}",
        )
        capabilities = item.get("capabilities", [])
        if not isinstance(capabilities, list) or not all(isinstance(v, str) and v for v in capabilities):
            raise ConfigError(f"devices.{device_id}.capabilities must be a string list")
        transport = _string(item.get("transport", "direct"), f"devices.{device_id}.transport")
        if transport not in {"direct", "spacebridge", "local", "maintenance_via_lora"}:
            raise ConfigError(
                f"devices.{device_id}.transport must be direct, spacebridge, local, or maintenance_via_lora"
            )
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"devices.{device_id}.enabled must be a boolean")
        metadata = _mapping(item.get("metadata", {}), f"devices.{device_id}.metadata")
        if transport == "local" and metadata:
            raise ConfigError(f"devices.{device_id}.metadata must be empty for local transport")
        if transport == "maintenance_via_lora":
            _only(metadata, {"host_key_alias", "port"}, f"devices.{device_id}.metadata")
            if "host_key_alias" not in metadata:
                raise ConfigError(
                    f"devices.{device_id}.metadata.host_key_alias is required for maintenance transport"
                )
            metadata["host_key_alias"] = _string(
                metadata["host_key_alias"],
                f"devices.{device_id}.metadata.host_key_alias",
            )
            if "port" in metadata:
                metadata["port"] = _port(metadata["port"], f"devices.{device_id}.metadata.port")
        result[device_id] = Device(
            device_id,
            _string(item.get("fleet"), f"devices.{device_id}.fleet"),
            _string(item.get("host"), f"devices.{device_id}.host"),
            transport,
            frozenset(capabilities),
            enabled,
            metadata,
        )
    return result


def _load_fleets(value: Any, devices: Mapping[str, Device]) -> dict[str, Fleet]:
    raw = _mapping(value, "fleets")
    result: dict[str, Fleet] = {}
    for fleet_id, item_raw in raw.items():
        item = _mapping(item_raw, f"fleets.{fleet_id}")
        _only(item, {"devices", "topic_id", "canaries"}, f"fleets.{fleet_id}")
        ids = item.get("devices", [d.device_id for d in devices.values() if d.fleet_id == fleet_id])
        canaries = item.get("canaries", [])
        if not isinstance(ids, list) or not all(isinstance(v, str) and v for v in ids):
            raise ConfigError(f"fleets.{fleet_id}.devices must be a string list")
        if not isinstance(canaries, list) or not all(isinstance(v, str) and v for v in canaries):
            raise ConfigError(f"fleets.{fleet_id}.canaries must be a string list")
        missing = (set(ids) | set(canaries)) - devices.keys()
        if missing:
            raise ConfigError(f"fleet {fleet_id} references unknown device(s): {', '.join(sorted(missing))}")
        if any(devices[device_id].fleet_id != fleet_id for device_id in (*ids, *canaries)):
            raise ConfigError(f"fleet {fleet_id} contains a device assigned to another fleet")
        if not set(canaries) <= set(ids):
            raise ConfigError(f"fleet {fleet_id} canaries must be included in its device list")
        topic_raw = item.get("topic_id")
        topic_id = None if topic_raw is None else _numeric_id(topic_raw, f"fleets.{fleet_id}.topic_id")
        result[fleet_id] = Fleet(
            fleet_id, tuple(dict.fromkeys(ids)), topic_id, tuple(dict.fromkeys(canaries))
        )
    missing_fleets = sorted({d.fleet_id for d in devices.values()} - result.keys())
    if missing_fleets:
        raise ConfigError(f"device(s) reference unknown fleet(s): {', '.join(missing_fleets)}")
    return result
