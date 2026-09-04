from pathlib import Path

import pytest

from telegram_controller.config import ConfigError, load_config


def _config(tmp_path: Path, extra: str = "") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    token = tmp_path / "control-token"
    key = tmp_path / "controller-key"
    known = tmp_path / "known_hosts"
    token.write_text("control-secret")
    key.write_text("private-key")
    known.write_text("device ssh-ed25519 AAAA")
    token.chmod(0o600)
    key.chmod(0o600)
    path = tmp_path / "controller.yaml"
    path.write_text(f"""
telegram:
  token_file: {token}
storage:
  database_path: {tmp_path / "controller.sqlite"}
ssh:
  private_key_file: {key}
  known_hosts_file: {known}
authorization:
  allowed_chats: ["-10001"]
  users:
    "123": {{role: operator, fleets: [west]}}
    "999": {{role: admin, fleets: []}}
devices:
  pump-1:
    fleet: west
    host: 10.0.0.1
    capabilities: [status, sample_now, reboot, ota]
fleets:
  west:
    devices: [pump-1]
    topic_id: "77"
controller:
  confirmation_ttl_s: 120
{extra}
""")
    return path


def test_loads_inventory_roles_scopes_topics_and_secret_files(tmp_path: Path) -> None:
    config = load_config(_config(tmp_path))
    assert config.principals["123"].fleets == frozenset({"west"})
    assert config.fleets["west"].topic_id == "77"
    assert config.devices["pump-1"].capabilities == frozenset({"status", "sample_now", "reboot", "ota"})
    assert config.ssh.device_key_file == tmp_path / "controller-key"
    assert config.ssh.private_key_file == config.ssh.device_key_file
    assert config.ssh.username == "ryne"
    assert config.ssh.connect_timeout_s == 10
    assert config.ssh.command_timeout_s == 60
    assert config.ssh.spacebridge_identity_file is None
    assert config.ssh.spacebridge_host == "tunnel.hologram.io"
    assert config.ssh.spacebridge_user == "htunnel"
    assert config.ssh.spacebridge_port == 999
    assert config.fleet_dispatch_concurrency == 4
    assert config.accepted_poll_interval_s == 2
    assert config.ota is None


def test_local_and_maintenance_transports_are_explicit_inventory_values(tmp_path: Path) -> None:
    path = _config(tmp_path)
    text = path.read_text()
    text = text.replace(
        "host: 10.0.0.1\n    capabilities:",
        "host: localhost\n    transport: local\n    capabilities:",
    )
    path.write_text(text)
    assert load_config(path).devices["pump-1"].transport == "local"

    registry = tmp_path / "lorawan-registry.yaml"
    registry.write_text("devices: {}\n")
    registry.chmod(0o600)
    maintenance = text.replace(
        "transport: local",
        "transport: maintenance_via_lora\n    metadata: {host_key_alias: pump-1-maintenance}",
    )
    maintenance += f"""
maintenance:
  registry_file: {registry}
  gateway_store_path: {tmp_path / "lorawan.sqlite"}
  readiness_timeout_s: 300
artifact_cache:
  directory: {tmp_path / "artifacts"}
  bind_host: 10.42.0.1
  port: 8091
"""
    path.write_text(maintenance)
    loaded = load_config(path)
    assert loaded.devices["pump-1"].transport == "maintenance_via_lora"
    assert loaded.maintenance is not None
    assert loaded.maintenance.readiness_timeout_s == 300
    assert loaded.artifact_cache is not None
    assert loaded.artifact_cache.base_url == "http://10.42.0.1:8091"
    assert loaded.artifact_cache.max_total_bytes == 2 * 1024 * 1024 * 1024
    assert loaded.artifact_cache.max_objects == 16
    assert loaded.artifact_cache.minimum_free_bytes == 256 * 1024 * 1024
    assert loaded.artifact_cache.http_max_connections == 4
    assert loaded.artifact_cache.http_socket_timeout_s == 30

    valid_text = path.read_text()
    for invalid_host in ("127.0.0.1", "169.254.1.1", "::1"):
        path.write_text(valid_text.replace("bind_host: 10.42.0.1", f"bind_host: {invalid_host}"))
        with pytest.raises(ConfigError, match="non-loopback and non-link-local"):
            load_config(path)


def test_maintenance_transport_requires_gateway_configuration(tmp_path: Path) -> None:
    path = _config(tmp_path)
    path.write_text(
        path.read_text().replace(
            "host: 10.0.0.1\n    capabilities:",
            "host: 10.0.0.1\n    transport: maintenance_via_lora\n"
            "    metadata: {host_key_alias: pump-1-maintenance}\n    capabilities:",
        )
    )
    with pytest.raises(ConfigError, match="require maintenance"):
        load_config(path)


def test_ota_maintenance_transport_requires_private_artifact_cache(tmp_path: Path) -> None:
    registry = tmp_path / "registry.yaml"
    registry.write_text("devices: {}\n")
    registry.chmod(0o600)
    path = _config(tmp_path)
    path.write_text(
        path.read_text().replace(
            "host: 10.0.0.1\n    capabilities:",
            "host: 10.42.0.21\n    transport: maintenance_via_lora\n"
            "    metadata: {host_key_alias: camera-1}\n    capabilities:",
        )
        + f"""
maintenance:
  registry_file: {registry}
  gateway_store_path: {tmp_path / "lorawan.sqlite"}
"""
    )
    with pytest.raises(ConfigError, match="require artifact_cache"):
        load_config(path)

    path.write_text(
        path.read_text()
        + f"""
artifact_cache:
  directory: {tmp_path / "artifacts"}
  bind_host: 8.8.8.8
"""
    )
    with pytest.raises(ConfigError, match="private maintenance"):
        load_config(path)


def test_local_transport_rejects_unused_metadata(tmp_path: Path) -> None:
    path = _config(tmp_path)
    path.write_text(
        path.read_text().replace(
            "host: 10.0.0.1\n    capabilities:",
            "host: localhost\n    transport: local\n    metadata: {port: 22}\n    capabilities:",
        )
    )
    with pytest.raises(ConfigError, match="must be empty"):
        load_config(path)


def test_rejects_unknown_keys_and_integer_identity(tmp_path: Path) -> None:
    path = _config(tmp_path)
    path.write_text(path.read_text().replace('allowed_chats: ["-10001"]', "allowed_chats: [-10001]"))
    with pytest.raises(ConfigError, match="numeric ID encoded as a string"):
        load_config(path)
    path = _config(tmp_path / "unknown", "  surprise: true")
    with pytest.raises(ConfigError, match="unknown key"):
        load_config(path)


def test_rejects_permissive_secret_mode_without_leaking_secret(tmp_path: Path) -> None:
    path = _config(tmp_path)
    token = tmp_path / "control-token"
    token.chmod(0o644)
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert "control-secret" not in str(caught.value)


def test_loads_and_bounds_fleet_dispatch_concurrency(tmp_path: Path) -> None:
    configured = _config(tmp_path, "  fleet_dispatch_concurrency: 8")
    assert load_config(configured).fleet_dispatch_concurrency == 8

    invalid = _config(tmp_path / "invalid", "  fleet_dispatch_concurrency: 33")
    with pytest.raises(ConfigError, match="at most 32"):
        load_config(invalid)


def test_loads_and_bounds_accepted_poll_interval(tmp_path: Path) -> None:
    configured = _config(tmp_path, "  accepted_poll_interval_s: 5")
    assert load_config(configured).accepted_poll_interval_s == 5

    invalid = _config(tmp_path / "invalid-poll", "  accepted_poll_interval_s: 301")
    with pytest.raises(ConfigError, match="at most 300"):
        load_config(invalid)


def test_loads_strict_ota_rollout_configuration(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text("schema_version: 1\nreleases: {stable: {}}\n", encoding="utf-8")
    path = _config(
        tmp_path,
        """
ota:
  catalog_file: %s
  rollout_percentages: [5, 25, 100]
  failure_rate_threshold: 0.05
  defer_rate_threshold: 0.2
"""
        % catalog,
    )

    config = load_config(path)

    assert config.ota is not None
    assert config.ota.catalog_file == catalog
    assert config.ota.rollout_percentages == (5, 25, 100)
    assert config.ota.failure_rate_threshold == 0.05
    assert config.ota.defer_rate_threshold == 0.2


@pytest.mark.parametrize(
    "ota_body",
    [
        "rollout_percentages: [50, 10, 100]",
        "rollout_percentages: [10, 50]",
        "failure_rate_threshold: 1.1",
        "defer_rate_threshold: false",
    ],
)
def test_rejects_invalid_ota_rollout_configuration(tmp_path: Path, ota_body: str) -> None:
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text("schema_version: 1\nreleases: {stable: {}}\n", encoding="utf-8")
    indented = "\n".join(f"  {line}" for line in ota_body.splitlines())
    path = _config(tmp_path, f"\nota:\n  catalog_file: {catalog}\n{indented}\n")
    with pytest.raises(ConfigError):
        load_config(path)
