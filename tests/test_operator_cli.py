from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "operator_cli.py"

spec = importlib.util.spec_from_file_location("operator_cli", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
operator_cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operator_cli)


def test_cli_search_builds_expected_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"entity_type": "device", "entity_id": "well-001"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "search",
            "pump",
        ]
    )

    assert rc == 0
    assert captured["base_url"] == "http://localhost:8082"
    assert captured["method"] == "GET"
    assert "/api/v1/search?" in str(captured["path"])
    assert "q=pump" in str(captured["path"])


def test_cli_health_reads_public_health(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "health",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/health"


def test_cli_contracts_telemetry_reads_public_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"version": "v1"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "contracts",
            "telemetry",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/contracts/telemetry"


def test_cli_contracts_edge_policy_reads_public_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"policy_version": "v1"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "contracts",
            "edge-policy",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/contracts/edge_policy"


def test_cli_ota_validation_collect_invokes_helper(monkeypatch, tmp_path: Path) -> None:
    output_path = tmp_path / "evidence.json"

    def _fake_run(cmd, check, capture_output, text):
        return subprocess.CompletedProcess(cmd, 0, stdout='{"output": "ok"}', stderr="")

    monkeypatch.setattr(operator_cli.subprocess, "run", _fake_run)

    rc = operator_cli.main(
        [
            "ota-validation",
            "collect",
            "--device-id",
            "well-001",
            "--output",
            str(output_path),
        ]
    )

    assert rc == 0


def test_cli_ota_validation_evaluate_invokes_helper(monkeypatch, tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text("{}", encoding="utf-8")

    def _fake_run(cmd, check, capture_output, text):
        return subprocess.CompletedProcess(cmd, 0, stdout='{"evidence_complete": true}', stderr="")

    monkeypatch.setattr(operator_cli.subprocess, "run", _fake_run)

    rc = operator_cli.main(
        [
            "ota-validation",
            "evaluate",
            "--scenario",
            "good_release",
            "--evidence-json",
            str(evidence_path),
        ]
    )

    assert rc == 0


def test_cli_ota_validation_run_chains_collect_and_evaluate(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    def _fake_collect(args):
        calls.append(("collect", args.output))

    def _fake_evaluate(args):
        calls.append(("evaluate", args.evidence_json))

    monkeypatch.setattr(operator_cli, "_cmd_ota_validation_collect", _fake_collect)
    monkeypatch.setattr(operator_cli, "_cmd_ota_validation_evaluate", _fake_evaluate)

    output_path = tmp_path / "evidence.json"
    rc = operator_cli.main(
        [
            "ota-validation",
            "run",
            "--device-id",
            "well-001",
            "--scenario",
            "good_release",
            "--output",
            str(output_path),
        ]
    )

    assert rc == 0
    assert calls == [
        ("collect", str(output_path)),
        ("evaluate", str(output_path)),
    ]


def test_cli_search_supports_entity_type_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"entity_type": "alert", "entity_id": "alert-1"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "search",
            "battery",
            "--entity-types",
            "alert,device_event",
        ]
    )

    assert rc == 0
    assert "entity_type=alert" in str(captured["path"])
    assert "entity_type=device_event" in str(captured["path"])


def test_cli_search_supports_release_manifest_entity_filter(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"entity_type": "release_manifest", "entity_id": "manifest-1"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "search",
            "v1.2.3",
            "--entity-types",
            "release_manifest",
        ]
    )

    assert rc == 0
    assert "entity_type=release_manifest" in str(captured["path"])


def test_cli_search_supports_admin_event_entity_filter(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"entity_type": "admin_event", "entity_id": "event-1"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "search",
            "device.update",
            "--entity-types",
            "admin_event",
        ]
    )

    assert rc == 0
    assert "entity_type=admin_event" in str(captured["path"])


def test_cli_search_supports_offset(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"entity_type": "device", "entity_id": "well-002"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "search",
            "pump",
            "--offset",
            "25",
        ]
    )

    assert rc == 0
    assert "offset=25" in str(captured["path"])


def test_cli_search_page_uses_total_aware_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total": 0, "limit": 25, "offset": 0}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "search-page",
            "pump",
            "--entity-types",
            "device",
            "--limit",
            "10",
            "--offset",
            "20",
        ]
    )

    assert rc == 0
    assert str(captured["path"]).startswith("/api/v1/search-page?")
    assert "q=pump" in str(captured["path"])
    assert "entity_type=device" in str(captured["path"])
    assert "limit=10" in str(captured["path"])
    assert "offset=20" in str(captured["path"])


def test_cli_alerts_supports_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"id": "alert-1"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "alerts",
            "--device-id",
            "well-001",
            "--open-only",
            "--severity",
            "warning",
            "--alert-type",
            "BATTERY_LOW",
            "--query",
            "battery",
            "--limit",
            "25",
        ]
    )

    assert rc == 0
    assert "device_id=well-001" in str(captured["path"])
    assert "open_only=true" in str(captured["path"])
    assert "severity=warning" in str(captured["path"])
    assert "alert_type=BATTERY_LOW" in str(captured["path"])
    assert "q=battery" in str(captured["path"])
    assert "limit=25" in str(captured["path"])


def test_cli_telemetry_supports_metric_and_bounds(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"message_id": "m1"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "telemetry",
            "--device-id",
            "well-001",
            "--metric",
            "battery_v",
            "--since",
            "2026-04-01T00:00:00Z",
            "--until",
            "2026-04-02T00:00:00Z",
            "--limit",
            "10",
        ]
    )

    assert rc == 0
    assert str(captured["path"]).startswith("/api/v1/devices/well-001/telemetry?")
    assert "metric=battery_v" in str(captured["path"])
    assert "since=2026-04-01T00%3A00%3A00Z" in str(captured["path"])
    assert "until=2026-04-02T00%3A00%3A00Z" in str(captured["path"])
    assert "limit=10" in str(captured["path"])


def test_cli_timeseries_supports_bucket_and_limit(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"bucket_ts": "2026-04-01T00:00:00Z", "value": 1.0}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "timeseries",
            "--device-id",
            "well-001",
            "--metric",
            "battery_v",
            "--bucket",
            "hour",
            "--limit",
            "24",
        ]
    )

    assert rc == 0
    assert str(captured["path"]).startswith("/api/v1/devices/well-001/timeseries?")
    assert "metric=battery_v" in str(captured["path"])
    assert "bucket=hour" in str(captured["path"])
    assert "limit=24" in str(captured["path"])


def test_cli_create_fleet_sends_admin_headers(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"id": "fleet-1", "name": "Pilot"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "fleets",
            "create",
            "--name",
            "Pilot",
            "--description",
            "Pilot fleet",
            "--default-ota-channel",
            "pilot",
        ]
    )

    assert rc == 0
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/admin/fleets"
    assert captured["headers"] == {"Accept": "application/json", "X-Admin-Key": "test-admin"}
    assert captured["body"] == {
        "name": "Pilot",
        "description": "Pilot fleet",
        "default_ota_channel": "pilot",
    }


def test_cli_update_fleet_sends_partial_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"id": "fleet-1", "default_ota_channel": "stable"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "fleets",
            "update",
            "--fleet-id",
            "fleet-1",
            "--default-ota-channel",
            "stable",
        ]
    )

    assert rc == 0
    assert captured["method"] == "PATCH"
    assert captured["path"] == "/api/v1/admin/fleets/fleet-1"
    assert captured["body"] == {"default_ota_channel": "stable"}


def test_cli_list_fleet_devices(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"device_id": "well-001"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "fleets",
            "devices",
            "--fleet-id",
            "fleet-1",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/fleets/fleet-1/devices"


def test_cli_remove_device_from_fleet(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"fleet_id": "fleet-1", "device_id": "well-001"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "fleets",
            "remove-device",
            "--fleet-id",
            "fleet-1",
            "--device-id",
            "well-001",
        ]
    )

    assert rc == 0
    assert captured["method"] == "DELETE"
    assert captured["path"] == "/api/v1/admin/fleets/fleet-1/devices/well-001"
    assert captured["body"] == {}


def test_cli_list_fleet_access(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"principal_email": "ops@example.com"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "fleets",
            "access-list",
            "--fleet-id",
            "fleet-1",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/admin/fleets/fleet-1/access"


def test_cli_revoke_fleet_access(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"principal_email": "ops@example.com"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "fleets",
            "revoke",
            "--fleet-id",
            "fleet-1",
            "--email",
            "ops@example.com",
        ]
    )

    assert rc == 0
    assert captured["method"] == "DELETE"
    assert captured["path"] == "/api/v1/admin/fleets/fleet-1/access/ops%40example.com"
    assert captured["body"] == {}


def test_cli_update_notification_destination_sends_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"id": "dest-1", "name": "Ops"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "notification-destinations",
            "update",
            "--destination-id",
            "dest-1",
            "--source-types",
            "alert,device_event",
            "--event-types",
            "BATTERY_LOW,procedure.capture_snapshot.requested",
            "--enabled",
        ]
    )

    assert rc == 0
    assert captured["method"] == "PATCH"
    assert captured["path"] == "/api/v1/admin/notification-destinations/dest-1"
    assert captured["body"] == {
        "source_types": ["alert", "device_event"],
        "event_types": ["BATTERY_LOW", "procedure.capture_snapshot.requested"],
        "enabled": True,
    }


def test_cli_delete_notification_destination(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"id": "dest-1"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "notification-destinations",
            "delete",
            "--destination-id",
            "dest-1",
        ]
    )

    assert rc == 0
    assert captured["method"] == "DELETE"
    assert captured["path"] == "/api/v1/admin/notification-destinations/dest-1"
    assert captured["body"] == {}


def test_cli_admin_events_uses_limit(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"action": "device.update"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "admin",
            "events",
            "--limit",
            "25",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/admin/events?limit=25"


def test_cli_admin_events_supports_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"action": "device.update"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "admin",
            "events",
            "--action",
            "device.update",
            "--target-type",
            "device",
            "--device-id",
            "well-001",
            "--limit",
            "25",
        ]
    )

    assert rc == 0
    assert "action=device.update" in str(captured["path"])
    assert "target_type=device" in str(captured["path"])
    assert "device_id=well-001" in str(captured["path"])


def test_cli_admin_events_page_supports_offset(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total": 0, "limit": 25, "offset": 25}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "admin",
            "events-page",
            "--limit",
            "25",
            "--offset",
            "25",
        ]
    )

    assert rc == 0
    assert "limit=25" in str(captured["path"])
    assert "offset=25" in str(captured["path"])


def test_cli_admin_ingestions_supports_device_filter(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"device_id": "well-001"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "admin",
            "ingestions",
            "--device-id",
            "well-001",
            "--limit",
            "50",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert "device_id=well-001" in str(captured["path"])
    assert "limit=50" in str(captured["path"])


def test_cli_admin_drift_events_supports_device_filter(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"device_id": "well-001"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "admin",
            "drift-events",
            "--device-id",
            "well-001",
            "--limit",
            "20",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert "device_id=well-001" in str(captured["path"])
    assert "limit=20" in str(captured["path"])


def test_cli_admin_ingestions_page_supports_offset(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total": 0, "limit": 25, "offset": 50}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "admin",
            "ingestions-page",
            "--device-id",
            "well-001",
            "--limit",
            "25",
            "--offset",
            "50",
        ]
    )

    assert rc == 0
    assert str(captured["path"]).startswith("/api/v1/admin/ingestions-page?")
    assert "device_id=well-001" in str(captured["path"])
    assert "limit=25" in str(captured["path"])
    assert "offset=50" in str(captured["path"])


def test_cli_admin_drift_events_page_supports_offset(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total": 0, "limit": 25, "offset": 50}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "admin",
            "drift-events-page",
            "--device-id",
            "well-001",
            "--limit",
            "25",
            "--offset",
            "50",
        ]
    )

    assert rc == 0
    assert str(captured["path"]).startswith("/api/v1/admin/drift-events-page?")
    assert "device_id=well-001" in str(captured["path"])
    assert "limit=25" in str(captured["path"])
    assert "offset=50" in str(captured["path"])


def test_cli_admin_notifications_supports_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"device_id": "well-001"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "admin",
            "notifications",
            "--device-id",
            "well-001",
            "--source-kind",
            "alert",
            "--channel",
            "webhook",
            "--decision",
            "delivered",
            "--delivered",
            "true",
            "--limit",
            "50",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert "device_id=well-001" in str(captured["path"])
    assert "source_kind=alert" in str(captured["path"])
    assert "channel=webhook" in str(captured["path"])
    assert "decision=delivered" in str(captured["path"])
    assert "delivered=true" in str(captured["path"])
    assert "limit=50" in str(captured["path"])


def test_cli_admin_notifications_page_supports_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total": 0, "limit": 25, "offset": 50}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "admin",
            "notifications-page",
            "--device-id",
            "well-001",
            "--source-kind",
            "alert",
            "--channel",
            "webhook",
            "--decision",
            "blocked",
            "--delivered",
            "false",
            "--limit",
            "25",
            "--offset",
            "50",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert str(captured["path"]).startswith("/api/v1/admin/notifications-page?")
    assert "device_id=well-001" in str(captured["path"])
    assert "source_kind=alert" in str(captured["path"])
    assert "channel=webhook" in str(captured["path"])
    assert "decision=blocked" in str(captured["path"])
    assert "delivered=false" in str(captured["path"])
    assert "limit=25" in str(captured["path"])
    assert "offset=50" in str(captured["path"])


def test_cli_admin_exports_page_supports_offset(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total": 0, "limit": 25, "offset": 50}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "admin",
            "exports-page",
            "--status",
            "completed",
            "--limit",
            "25",
            "--offset",
            "50",
        ]
    )

    assert rc == 0
    assert str(captured["path"]).startswith("/api/v1/admin/exports-page?")
    assert "status=completed" in str(captured["path"])
    assert "limit=25" in str(captured["path"])
    assert "offset=50" in str(captured["path"])


def test_cli_admin_exports_supports_status_filter(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"status": "completed"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "admin",
            "exports",
            "--status",
            "completed",
            "--limit",
            "10",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert "status=completed" in str(captured["path"])
    assert "limit=10" in str(captured["path"])


def test_cli_admin_edge_policy_source(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"yaml_text": "version: v1"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "admin",
            "edge-policy-source",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/admin/contracts/edge-policy/source"


def test_cli_admin_edge_policy_update(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"policy_version": "v1"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "admin",
            "edge-policy-update",
            "--yaml-text",
            "version: v1",
        ]
    )

    assert rc == 0
    assert captured["method"] == "PATCH"
    assert captured["path"] == "/api/v1/admin/contracts/edge-policy"
    assert captured["body"] == {"yaml_text": "version: v1"}


def test_cli_update_device_ota_governance(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"device_id": "well-001", "ota_channel": "pilot"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "devices",
            "update-ota",
            "--device-id",
            "well-001",
            "--ota-channel",
            "pilot",
            "--updates-disabled",
            "--busy-reason",
            "maintenance",
            "--development",
            "--clear-locked-manifest-id",
        ]
    )

    assert rc == 0
    assert captured["method"] == "PATCH"
    assert captured["path"] == "/api/v1/admin/devices/well-001"
    assert captured["body"] == {
        "ota_channel": "pilot",
        "ota_updates_enabled": False,
        "ota_busy_reason": "maintenance",
        "ota_is_development": True,
        "ota_locked_manifest_id": None,
    }


def test_cli_update_procedure_definition(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"id": "proc-1", "enabled": False}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "procedures",
            "update",
            "--definition-id",
            "proc-1",
            "--description",
            "Updated procedure",
            "--timeout-s",
            "120",
            "--disabled",
        ]
    )

    assert rc == 0
    assert captured["method"] == "PATCH"
    assert captured["path"] == "/api/v1/admin/procedures/definitions/proc-1"
    assert captured["body"] == {
        "description": "Updated procedure",
        "timeout_s": 120,
        "enabled": False,
    }


def test_cli_create_device_sends_registration_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"device_id": "well-123"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "devices",
            "create",
            "--device-id",
            "well-123",
            "--token",
            "secret-token",
            "--display-name",
            "Well 123",
            "--heartbeat-interval-s",
            "300",
            "--offline-after-s",
            "900",
            "--owner-emails",
            "owner@example.com,ops@example.com",
        ]
    )

    assert rc == 0
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/admin/devices"
    assert captured["body"] == {
        "device_id": "well-123",
        "token": "secret-token",
        "display_name": "Well 123",
        "heartbeat_interval_s": 300,
        "offline_after_s": 900,
        "owner_emails": ["owner@example.com", "ops@example.com"],
    }


def test_cli_list_devices_admin(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"device_id": "well-123"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "devices",
            "list",
            "--admin",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/admin/devices"


def test_cli_get_device(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"device_id": "well-123"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "devices",
            "get",
            "--device-id",
            "well-123",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/devices/well-123"


def test_cli_devices_summary_supports_metrics(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"device_id": "well-123"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "devices",
            "summary",
            "--metrics",
            "battery_v,signal_rssi_dbm",
            "--limit-metrics",
            "10",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert "metrics=battery_v" in str(captured["path"])
    assert "metrics=signal_rssi_dbm" in str(captured["path"])
    assert "limit_metrics=10" in str(captured["path"])


def test_cli_list_device_access(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"principal_email": "ops@example.com"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "devices",
            "access-list",
            "--device-id",
            "well-123",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/admin/devices/well-123/access"


def test_cli_grant_device_access(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"principal_email": "ops@example.com"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "devices",
            "access-grant",
            "--device-id",
            "well-123",
            "--email",
            "ops@example.com",
            "--role",
            "operator",
        ]
    )

    assert rc == 0
    assert captured["method"] == "PUT"
    assert captured["path"] == "/api/v1/admin/devices/well-123/access/ops%40example.com"
    assert captured["body"] == {"access_role": "operator"}


def test_cli_revoke_device_access(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"principal_email": "ops@example.com"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "devices",
            "access-revoke",
            "--device-id",
            "well-123",
            "--email",
            "ops@example.com",
        ]
    )

    assert rc == 0
    assert captured["method"] == "DELETE"
    assert captured["path"] == "/api/v1/admin/devices/well-123/access/ops%40example.com"
    assert captured["body"] == {}


def test_cli_update_device_sends_partial_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"device_id": "well-123"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "devices",
            "update",
            "--device-id",
            "well-123",
            "--display-name",
            "Well 123 Updated",
            "--disabled",
        ]
    )

    assert rc == 0
    assert captured["method"] == "PATCH"
    assert captured["path"] == "/api/v1/admin/devices/well-123"
    assert captured["body"] == {
        "display_name": "Well 123 Updated",
        "enabled": False,
    }


def test_cli_get_device_controls(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"device_id": "well-123", "operation_mode": "active"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "devices",
            "controls-get",
            "--device-id",
            "well-123",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/devices/well-123/controls"


def test_cli_set_device_operation(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"device_id": "well-123", "operation_mode": "sleep"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "devices",
            "operation-set",
            "--device-id",
            "well-123",
            "--operation-mode",
            "sleep",
            "--sleep-poll-interval-s",
            "3600",
            "--runtime-power-mode",
            "eco",
        ]
    )

    assert rc == 0
    assert captured["method"] == "PATCH"
    assert captured["path"] == "/api/v1/devices/well-123/controls/operation"
    assert captured["body"] == {
        "operation_mode": "sleep",
        "sleep_poll_interval_s": 3600,
        "runtime_power_mode": "eco",
    }


def test_cli_set_device_alert_mute(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"device_id": "well-123", "alerts_muted_until": "2026-04-20T00:00:00Z"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "devices",
            "alerts-set",
            "--device-id",
            "well-123",
            "--alerts-muted-until",
            "2026-04-20T00:00:00Z",
            "--alerts-muted-reason",
            "maintenance",
        ]
    )

    assert rc == 0
    assert captured["method"] == "PATCH"
    assert captured["path"] == "/api/v1/devices/well-123/controls/alerts"
    assert captured["body"] == {
        "alerts_muted_until": "2026-04-20T00:00:00Z",
        "alerts_muted_reason": "maintenance",
    }


def test_cli_list_media_uses_bearer_token(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"id": "media-1"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "media",
            "list",
            "--device-id",
            "well-123",
            "--token",
            "device-token",
            "--limit",
            "50",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/devices/well-123/media?limit=50"
    assert captured["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer device-token",
    }


def test_cli_download_media_writes_file(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    output_path = tmp_path / "media.bin"

    def _fake_request_bytes(**kwargs):
        captured.update(kwargs)
        return b"payload"

    monkeypatch.setattr(operator_cli, "_request_bytes", _fake_request_bytes)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "media",
            "download",
            "--media-id",
            "media-1",
            "--token",
            "device-token",
            "--output",
            str(output_path),
        ]
    )

    assert rc == 0
    assert captured["path"] == "/api/v1/media/media-1/download"
    assert captured["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer device-token",
    }
    assert output_path.read_bytes() == b"payload"


def test_cli_shutdown_device_sends_reason_and_grace(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"device_id": "well-123", "pending_command_count": 1}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "devices",
            "shutdown",
            "--device-id",
            "well-123",
            "--reason",
            "seasonal intermission",
            "--shutdown-grace-s",
            "45",
        ]
    )

    assert rc == 0
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/admin/devices/well-123/controls/shutdown"
    assert captured["body"] == {
        "reason": "seasonal intermission",
        "shutdown_grace_s": 45,
    }


def test_cli_create_release_manifest_sends_artifact_fields(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"id": "man-1", "git_tag": "v1.2.3"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "releases",
            "manifests-create",
            "--git-tag",
            "v1.2.3",
            "--commit-sha",
            "a" * 40,
            "--artifact-uri",
            "https://example.com/release.tar",
            "--artifact-size",
            "1024",
            "--artifact-sha256",
            "b" * 64,
            "--signature",
            "sig",
            "--signature-key-id",
            "ops-key-1",
        ]
    )

    assert rc == 0
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/admin/releases/manifests"
    assert captured["body"] == {
        "git_tag": "v1.2.3",
        "commit_sha": "a" * 40,
        "update_type": "application_bundle",
        "artifact_uri": "https://example.com/release.tar",
        "artifact_size": 1024,
        "artifact_sha256": "b" * 64,
        "artifact_signature": "",
        "artifact_signature_scheme": "none",
        "compatibility": {},
        "signature": "sig",
        "signature_key_id": "ops-key-1",
        "constraints": {},
        "status": "active",
    }


def test_cli_update_release_manifest_status(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"id": "man-1", "status": "retired"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "releases",
            "manifests-update-status",
            "--manifest-id",
            "man-1",
            "--status",
            "retired",
        ]
    )

    assert rc == 0
    assert captured["method"] == "PATCH"
    assert captured["path"] == "/api/v1/admin/releases/manifests/man-1"
    assert captured["body"] == {"status": "retired"}


def test_cli_list_deployments_supports_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return [{"id": "dep-1", "status": "active"}]

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "releases",
            "deployments-list",
            "--status",
            "active",
            "--manifest-id",
            "man-1",
            "--selector-channel",
            "stable",
            "--limit",
            "25",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert "/api/v1/admin/deployments?" in str(captured["path"])
    assert "status=active" in str(captured["path"])
    assert "manifest_id=man-1" in str(captured["path"])
    assert "selector_channel=stable" in str(captured["path"])
    assert "limit=25" in str(captured["path"])


def test_cli_list_deployment_targets_supports_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total": 0, "limit": 50, "offset": 10}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "releases",
            "deployment-targets-list",
            "--deployment-id",
            "dep-1",
            "--status",
            "failed",
            "--query",
            "verify",
            "--limit",
            "50",
            "--offset",
            "10",
        ]
    )

    assert rc == 0
    assert captured["method"] == "GET"
    assert str(captured["path"]).startswith("/api/v1/admin/deployments/dep-1/targets?")
    assert "status=failed" in str(captured["path"])
    assert "q=verify" in str(captured["path"])
    assert "limit=50" in str(captured["path"])
    assert "offset=10" in str(captured["path"])


def test_cli_live_stream_uses_server_side_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_sse(**kwargs):
        captured.update(kwargs)
        return [{"event": "alert", "data": {"event_type": "BATTERY_LOW"}}]

    monkeypatch.setattr(operator_cli, "_request_sse", _fake_request_sse)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "live-stream",
            "--device-id",
            "well-001",
            "--source-kinds",
            "alert,notification_event,device_event,deployment_event,release_manifest_event,admin_event",
            "--event-name",
            "BATTERY_LOW",
            "--since-seconds",
            "600",
            "--max-events",
            "3",
            "--timeout-s",
            "2.5",
        ]
    )

    assert rc == 0
    assert str(captured["path"]).startswith("/api/v1/event-stream?")
    assert "device_id=well-001" in str(captured["path"])
    assert "source_kind=alert" in str(captured["path"])
    assert "source_kind=notification_event" in str(captured["path"])
    assert "source_kind=device_event" in str(captured["path"])
    assert "source_kind=deployment_event" in str(captured["path"])
    assert "source_kind=release_manifest_event" in str(captured["path"])
    assert "source_kind=admin_event" in str(captured["path"])
    assert "event_name=BATTERY_LOW" in str(captured["path"])
    assert "since_seconds=600" in str(captured["path"])
    assert captured["max_events"] == 3
    assert captured["timeout_s"] == 2.5


def test_cli_operator_events_uses_paged_history_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total": 0, "limit": 25, "offset": 0}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "operator-events",
            "--device-id",
            "well-001",
            "--source-kinds",
            "alert,notification_event,device_event,deployment_event,release_manifest_event,admin_event",
            "--event-name",
            "BATTERY_LOW",
            "--limit",
            "25",
            "--offset",
            "50",
        ]
    )

    assert rc == 0
    assert str(captured["path"]).startswith("/api/v1/operator-events?")
    assert "device_id=well-001" in str(captured["path"])
    assert "source_kind=alert" in str(captured["path"])
    assert "source_kind=notification_event" in str(captured["path"])
    assert "source_kind=device_event" in str(captured["path"])
    assert "source_kind=deployment_event" in str(captured["path"])
    assert "source_kind=release_manifest_event" in str(captured["path"])
    assert "source_kind=admin_event" in str(captured["path"])
    assert "event_name=BATTERY_LOW" in str(captured["path"])
    assert "limit=25" in str(captured["path"])
    assert "offset=50" in str(captured["path"])


def test_cli_pause_deployment(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"id": "dep-1", "status": "paused"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "releases",
            "deployment-pause",
            "--deployment-id",
            "dep-1",
        ]
    )

    assert rc == 0
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/admin/deployments/dep-1/pause"
    assert captured["body"] == {}


def test_cli_abort_deployment_with_reason(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"id": "dep-1", "status": "aborted"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "releases",
            "deployment-abort",
            "--deployment-id",
            "dep-1",
            "--reason",
            "operator halt",
        ]
    )

    assert rc == 0
    assert captured["method"] == "POST"
    assert "reason=operator+halt" in str(captured["path"])
    assert str(captured["path"]).startswith("/api/v1/admin/deployments/dep-1/abort?")
    assert captured["body"] == {}


def test_cli_create_deployment_supports_channel_selector(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_request_json(**kwargs):
        captured.update(kwargs)
        return {"id": "dep-1", "status": "active"}

    monkeypatch.setattr(operator_cli, "_request_json", _fake_request_json)

    rc = operator_cli.main(
        [
            "--base-url",
            "http://localhost:8082",
            "--admin-key",
            "test-admin",
            "releases",
            "deployment-create",
            "--manifest-id",
            "man-1",
            "--selector-mode",
            "channel",
            "--channel",
            "pilot",
            "--rollout-stages",
            "10,50,100",
        ]
    )

    assert rc == 0
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/admin/deployments"
    assert captured["body"] == {
        "manifest_id": "man-1",
        "target_selector": {"mode": "channel", "channel": "pilot"},
        "rollout_stages_pct": [10, 50, 100],
        "failure_rate_threshold": 0.2,
        "no_quorum_timeout_s": 1800,
        "stage_timeout_s": 1800,
        "defer_rate_threshold": 0.5,
        "health_timeout_s": 300,
        "command_ttl_s": 15552000,
        "power_guard_required": True,
        "rollback_to_tag": None,
    }
