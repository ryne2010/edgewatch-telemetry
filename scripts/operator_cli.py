from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _normalize_admin_key(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1].strip()
    return value


def _build_headers(args: argparse.Namespace, *, needs_admin: bool) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if needs_admin:
        admin_key = _normalize_admin_key(getattr(args, "admin_key", None))
        if admin_key:
            headers["X-Admin-Key"] = admin_key
    dev_email = (getattr(args, "dev_principal_email", None) or "").strip()
    dev_role = (getattr(args, "dev_principal_role", None) or "").strip()
    if dev_email:
        headers["X-EdgeWatch-Dev-Principal-Email"] = dev_email
    if dev_role:
        headers["X-EdgeWatch-Dev-Principal-Role"] = dev_role
    for raw in getattr(args, "header", []) or []:
        if "=" not in raw:
            raise SystemExit(f"invalid --header value: {raw!r} (expected Key=Value)")
        key, value = raw.split("=", 1)
        headers[key.strip()] = value
    return headers


def _request_json(
    *,
    base_url: str,
    path: str,
    method: str,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
) -> Any:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    request = urllib.request.Request(url=url, method=method)
    for key, value in headers.items():
        request.add_header(key, value)
    payload: bytes | None = None
    if body is not None:
        request.add_header("Content-Type", "application/json")
        payload = json.dumps(body).encode("utf-8")
    try:
        with urllib.request.urlopen(request, data=payload, timeout=30.0) as response:
            data = response.read().decode("utf-8")
            if not data:
                return None
            return json.loads(data)
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {message or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Request failed: {exc.reason}") from exc


def _request_sse(
    *,
    base_url: str,
    path: str,
    headers: dict[str, str],
    max_events: int,
    timeout_s: float,
) -> list[dict[str, Any]]:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    request = urllib.request.Request(url=url, method="GET")
    for key, value in headers.items():
        request.add_header(key, value)
    request.add_header("Accept", "text/event-stream")
    events: list[dict[str, Any]] = []
    current_event: str | None = None
    current_data: str | None = None
    deadline = time.monotonic() + max(0.1, timeout_s)
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            while len(events) < max_events and time.monotonic() < deadline:
                raw = response.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    if current_data:
                        try:
                            parsed = json.loads(current_data)
                        except json.JSONDecodeError:
                            parsed = {"raw": current_data}
                        events.append({"event": current_event or "message", "data": parsed})
                    current_event = None
                    current_data = None
                    continue
                if line.startswith("event:"):
                    current_event = line.removeprefix("event:").strip()
                elif line.startswith("data:"):
                    current_data = line.removeprefix("data:").strip()
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {message or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Request failed: {exc.reason}") from exc
    return events


def _request_bytes(
    *,
    base_url: str,
    path: str,
    headers: dict[str, str],
) -> bytes:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    request = urllib.request.Request(url=url, method="GET")
    for key, value in headers.items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=30.0) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {message or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Request failed: {exc.reason}") from exc


def _run_local_json_command(cmd: list[str]) -> Any:
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit((proc.stderr or proc.stdout or "").strip() or f"command failed: {cmd}")
    text = (proc.stdout or "").strip()
    if not text:
        return None
    return json.loads(text)


def _parse_json_arg(raw: str | None, *, label: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label} must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit(f"{label} must decode to a JSON object")
    return parsed


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _cmd_health(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path="/api/v1/health",
        method="GET",
        headers=_build_headers(args, needs_admin=False),
    )
    _print_json(data)


def _cmd_search(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"q": args.query, "limit": args.limit, "offset": args.offset}
    for value in [item.strip() for item in args.entity_types.split(",") if item.strip()]:
        params.setdefault("entity_type", [])
        params["entity_type"].append(value)
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/search?{urllib.parse.urlencode(params, doseq=True)}",
        method="GET",
        headers=_build_headers(args, needs_admin=False),
    )
    _print_json(data)


def _cmd_search_page(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"q": args.query, "limit": args.limit, "offset": args.offset}
    for value in [item.strip() for item in args.entity_types.split(",") if item.strip()]:
        params.setdefault("entity_type", [])
        params["entity_type"].append(value)
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/search-page?{urllib.parse.urlencode(params, doseq=True)}",
        method="GET",
        headers=_build_headers(args, needs_admin=False),
    )
    _print_json(data)


def _cmd_contracts_telemetry(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path="/api/v1/contracts/telemetry",
        method="GET",
        headers=_build_headers(args, needs_admin=False),
    )
    _print_json(data)


def _cmd_contracts_edge_policy(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path="/api/v1/contracts/edge_policy",
        method="GET",
        headers=_build_headers(args, needs_admin=False),
    )
    _print_json(data)


def _cmd_alerts(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"limit": args.limit}
    if args.device_id:
        params["device_id"] = args.device_id
    if args.open_only:
        params["open_only"] = "true"
    if args.severity:
        params["severity"] = args.severity
    if args.alert_type:
        params["alert_type"] = args.alert_type
    if args.query:
        params["q"] = args.query
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/alerts?{urllib.parse.urlencode(params)}",
        method="GET",
        headers=_build_headers(args, needs_admin=False),
    )
    _print_json(data)


def _cmd_telemetry(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"limit": args.limit}
    if args.metric:
        params["metric"] = args.metric
    if args.since:
        params["since"] = args.since
    if args.until:
        params["until"] = args.until
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/devices/{urllib.parse.quote(args.device_id)}/telemetry?{urllib.parse.urlencode(params)}",
        method="GET",
        headers=_build_headers(args, needs_admin=False),
    )
    _print_json(data)


def _cmd_timeseries(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"metric": args.metric, "bucket": args.bucket}
    if args.since:
        params["since"] = args.since
    if args.until:
        params["until"] = args.until
    if args.limit is not None:
        params["limit"] = args.limit
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/devices/{urllib.parse.quote(args.device_id)}/timeseries?{urllib.parse.urlencode(params)}",
        method="GET",
        headers=_build_headers(args, needs_admin=False),
    )
    _print_json(data)


def _cmd_fleets_list(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path="/api/v1/admin/fleets" if args.admin else "/api/v1/fleets",
        method="GET",
        headers=_build_headers(args, needs_admin=args.admin),
    )
    _print_json(data)


def _cmd_fleets_devices(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/fleets/{urllib.parse.quote(args.fleet_id)}/devices",
        method="GET",
        headers=_build_headers(args, needs_admin=False),
    )
    _print_json(data)


def _cmd_fleets_create(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path="/api/v1/admin/fleets",
        method="POST",
        headers=_build_headers(args, needs_admin=True),
        body={
            "name": args.name,
            "description": args.description,
            "default_ota_channel": args.default_ota_channel,
        },
    )
    _print_json(data)


def _cmd_fleets_add_device(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/fleets/{urllib.parse.quote(args.fleet_id)}/devices/{urllib.parse.quote(args.device_id)}",
        method="PUT",
        headers=_build_headers(args, needs_admin=True),
        body={},
    )
    _print_json(data)


def _cmd_fleets_remove_device(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/fleets/{urllib.parse.quote(args.fleet_id)}/devices/{urllib.parse.quote(args.device_id)}",
        method="DELETE",
        headers=_build_headers(args, needs_admin=True),
        body={},
    )
    _print_json(data)


def _cmd_fleets_grant(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/fleets/{urllib.parse.quote(args.fleet_id)}/access/{urllib.parse.quote(args.email)}",
        method="PUT",
        headers=_build_headers(args, needs_admin=True),
        body={"access_role": args.role},
    )
    _print_json(data)


def _cmd_fleets_access_list(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/fleets/{urllib.parse.quote(args.fleet_id)}/access",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_fleets_revoke(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/fleets/{urllib.parse.quote(args.fleet_id)}/access/{urllib.parse.quote(args.email)}",
        method="DELETE",
        headers=_build_headers(args, needs_admin=True),
        body={},
    )
    _print_json(data)


def _cmd_fleets_update(args: argparse.Namespace) -> None:
    body: dict[str, Any] = {}
    if args.description is not None:
        body["description"] = args.description
    if args.default_ota_channel is not None:
        body["default_ota_channel"] = args.default_ota_channel
    if not body:
        raise SystemExit("at least one field must be supplied for fleet update")
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/fleets/{urllib.parse.quote(args.fleet_id)}",
        method="PATCH",
        headers=_build_headers(args, needs_admin=True),
        body=body,
    )
    _print_json(data)


def _cmd_procedures_list(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path="/api/v1/admin/procedures/definitions",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_procedures_create(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path="/api/v1/admin/procedures/definitions",
        method="POST",
        headers=_build_headers(args, needs_admin=True),
        body={
            "name": args.name,
            "description": args.description,
            "timeout_s": args.timeout_s,
            "request_schema": _parse_json_arg(args.request_schema, label="request schema"),
            "response_schema": _parse_json_arg(args.response_schema, label="response schema"),
            "enabled": not args.disabled,
        },
    )
    _print_json(data)


def _cmd_procedures_update(args: argparse.Namespace) -> None:
    body: dict[str, Any] = {}
    if args.description is not None:
        body["description"] = args.description
    if args.timeout_s is not None:
        body["timeout_s"] = args.timeout_s
    if args.request_schema is not None:
        body["request_schema"] = _parse_json_arg(args.request_schema, label="request schema")
    if args.response_schema is not None:
        body["response_schema"] = _parse_json_arg(args.response_schema, label="response schema")
    if args.enabled:
        body["enabled"] = True
    if args.disabled:
        body["enabled"] = False
    if not body:
        raise SystemExit("at least one field must be supplied for procedure update")
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/procedures/definitions/{urllib.parse.quote(args.definition_id)}",
        method="PATCH",
        headers=_build_headers(args, needs_admin=True),
        body=body,
    )
    _print_json(data)


def _cmd_procedures_invoke(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/devices/{urllib.parse.quote(args.device_id)}/procedures/{urllib.parse.quote(args.name)}/invoke",
        method="POST",
        headers=_build_headers(args, needs_admin=False),
        body={
            "request_payload": _parse_json_arg(args.payload, label="procedure payload"),
            "ttl_s": args.ttl_s,
        },
    )
    _print_json(data)


def _cmd_procedures_history(args: argparse.Namespace) -> None:
    params = urllib.parse.urlencode({"limit": args.limit})
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/devices/{urllib.parse.quote(args.device_id)}/procedure-invocations?{params}",
        method="GET",
        headers=_build_headers(args, needs_admin=False),
    )
    _print_json(data)


def _cmd_device_state(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/devices/{urllib.parse.quote(args.device_id)}/state",
        method="GET",
        headers=_build_headers(args, needs_admin=False),
    )
    _print_json(data)


def _cmd_device_events(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"limit": args.limit}
    if args.device_id:
        params["device_id"] = args.device_id
    if args.event_type:
        params["event_type"] = args.event_type
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/device-events?{urllib.parse.urlencode(params)}",
        method="GET",
        headers=_build_headers(args, needs_admin=False),
    )
    _print_json(data)


def _cmd_media_list(args: argparse.Namespace) -> None:
    params = urllib.parse.urlencode({"limit": args.limit})
    headers = _build_headers(args, needs_admin=False)
    token = _normalize_admin_key(args.token)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/devices/{urllib.parse.quote(args.device_id)}/media?{params}",
        method="GET",
        headers=headers,
    )
    _print_json(data)


def _cmd_media_download(args: argparse.Namespace) -> None:
    headers = _build_headers(args, needs_admin=False)
    token = _normalize_admin_key(args.token)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = _request_bytes(
        base_url=args.base_url,
        path=f"/api/v1/media/{urllib.parse.quote(args.media_id)}/download",
        headers=headers,
    )
    with open(args.output, "wb") as fh:
        fh.write(payload)
    print(json.dumps({"output": args.output, "bytes": len(payload)}, indent=2, sort_keys=True))


def _cmd_ota_validation_collect(args: argparse.Namespace) -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "ota"
        / "collect_system_image_validation_evidence.py"
    )
    cmd = [sys.executable, str(script), "--device-id", args.device_id, "--output", args.output]
    if args.update_state_path:
        cmd.extend(["--update-state-path", args.update_state_path])
    if args.stage_dir:
        cmd.extend(["--stage-dir", args.stage_dir])
    _print_json(_run_local_json_command(cmd))


def _cmd_ota_validation_evaluate(args: argparse.Namespace) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "ota" / "evaluate_system_image_validation.py"
    cmd = [
        sys.executable,
        str(script),
        "--scenario",
        args.scenario,
        "--evidence-json",
        args.evidence_json,
    ]
    _print_json(_run_local_json_command(cmd))


def _cmd_ota_validation_run(args: argparse.Namespace) -> None:
    evidence_path = Path(args.output)
    collect_args = argparse.Namespace(
        device_id=args.device_id,
        update_state_path=args.update_state_path,
        stage_dir=args.stage_dir,
        output=str(evidence_path),
    )
    _cmd_ota_validation_collect(collect_args)
    evaluate_args = argparse.Namespace(
        scenario=args.scenario,
        evidence_json=str(evidence_path),
    )
    _cmd_ota_validation_evaluate(evaluate_args)


def _cmd_devices_list(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path="/api/v1/admin/devices" if args.admin else "/api/v1/devices",
        method="GET",
        headers=_build_headers(args, needs_admin=args.admin),
    )
    _print_json(data)


def _cmd_devices_get(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/devices/{urllib.parse.quote(args.device_id)}",
        method="GET",
        headers=_build_headers(args, needs_admin=False),
    )
    _print_json(data)


def _cmd_devices_summary(args: argparse.Namespace) -> None:
    params: list[tuple[str, str]] = []
    for metric in [value.strip() for value in args.metrics.split(",") if value.strip()]:
        params.append(("metrics", metric))
    if args.limit_metrics is not None:
        params.append(("limit_metrics", str(args.limit_metrics)))
    query = urllib.parse.urlencode(params, doseq=True)
    path = f"/api/v1/devices/summary{f'?{query}' if query else ''}"
    data = _request_json(
        base_url=args.base_url,
        path=path,
        method="GET",
        headers=_build_headers(args, needs_admin=False),
    )
    _print_json(data)


def _cmd_devices_create(args: argparse.Namespace) -> None:
    body: dict[str, Any] = {
        "device_id": args.device_id,
        "token": args.token,
    }
    if args.display_name:
        body["display_name"] = args.display_name
    if args.heartbeat_interval_s is not None:
        body["heartbeat_interval_s"] = args.heartbeat_interval_s
    if args.offline_after_s is not None:
        body["offline_after_s"] = args.offline_after_s
    if args.owner_emails:
        body["owner_emails"] = [value.strip() for value in args.owner_emails.split(",") if value.strip()]
    data = _request_json(
        base_url=args.base_url,
        path="/api/v1/admin/devices",
        method="POST",
        headers=_build_headers(args, needs_admin=True),
        body=body,
    )
    _print_json(data)


def _cmd_devices_access_list(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/devices/{urllib.parse.quote(args.device_id)}/access",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_devices_access_grant(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/devices/{urllib.parse.quote(args.device_id)}/access/{urllib.parse.quote(args.email)}",
        method="PUT",
        headers=_build_headers(args, needs_admin=True),
        body={"access_role": args.role},
    )
    _print_json(data)


def _cmd_devices_access_revoke(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/devices/{urllib.parse.quote(args.device_id)}/access/{urllib.parse.quote(args.email)}",
        method="DELETE",
        headers=_build_headers(args, needs_admin=True),
        body={},
    )
    _print_json(data)


def _cmd_devices_update(args: argparse.Namespace) -> None:
    body: dict[str, Any] = {}
    if args.display_name is not None:
        body["display_name"] = args.display_name
    if args.token is not None:
        body["token"] = args.token
    if args.heartbeat_interval_s is not None:
        body["heartbeat_interval_s"] = args.heartbeat_interval_s
    if args.offline_after_s is not None:
        body["offline_after_s"] = args.offline_after_s
    if args.enabled:
        body["enabled"] = True
    if args.disabled:
        body["enabled"] = False
    if not body:
        raise SystemExit("at least one device field must be supplied")
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/devices/{urllib.parse.quote(args.device_id)}",
        method="PATCH",
        headers=_build_headers(args, needs_admin=True),
        body=body,
    )
    _print_json(data)


def _cmd_devices_controls_get(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/devices/{urllib.parse.quote(args.device_id)}/controls",
        method="GET",
        headers=_build_headers(args, needs_admin=False),
    )
    _print_json(data)


def _cmd_devices_operation_set(args: argparse.Namespace) -> None:
    body: dict[str, Any] = {"operation_mode": args.operation_mode}
    if args.sleep_poll_interval_s is not None:
        body["sleep_poll_interval_s"] = args.sleep_poll_interval_s
    if args.runtime_power_mode is not None:
        body["runtime_power_mode"] = args.runtime_power_mode
    if args.deep_sleep_backend is not None:
        body["deep_sleep_backend"] = args.deep_sleep_backend
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/devices/{urllib.parse.quote(args.device_id)}/controls/operation",
        method="PATCH",
        headers=_build_headers(args, needs_admin=False),
        body=body,
    )
    _print_json(data)


def _cmd_devices_alerts_set(args: argparse.Namespace) -> None:
    body: dict[str, Any] = {}
    if args.clear:
        body["alerts_muted_until"] = None
        body["alerts_muted_reason"] = None
    else:
        body["alerts_muted_until"] = args.alerts_muted_until
        if args.alerts_muted_reason is not None:
            body["alerts_muted_reason"] = args.alerts_muted_reason
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/devices/{urllib.parse.quote(args.device_id)}/controls/alerts",
        method="PATCH",
        headers=_build_headers(args, needs_admin=False),
        body=body,
    )
    _print_json(data)


def _cmd_devices_shutdown(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/devices/{urllib.parse.quote(args.device_id)}/controls/shutdown",
        method="POST",
        headers=_build_headers(args, needs_admin=True),
        body={
            "reason": args.reason,
            "shutdown_grace_s": args.shutdown_grace_s,
        },
    )
    _print_json(data)


def _cmd_devices_update_ota(args: argparse.Namespace) -> None:
    body: dict[str, Any] = {}
    if args.ota_channel is not None:
        body["ota_channel"] = args.ota_channel
    if args.updates_enabled:
        body["ota_updates_enabled"] = True
    if args.updates_disabled:
        body["ota_updates_enabled"] = False
    if args.busy_reason is not None:
        body["ota_busy_reason"] = args.busy_reason
    if args.clear_busy_reason:
        body["ota_busy_reason"] = None
    if args.development:
        body["ota_is_development"] = True
    if args.not_development:
        body["ota_is_development"] = False
    if args.locked_manifest_id is not None:
        body["ota_locked_manifest_id"] = args.locked_manifest_id
    if args.clear_locked_manifest_id:
        body["ota_locked_manifest_id"] = None
    if not body:
        raise SystemExit("at least one OTA governance field must be supplied")
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/devices/{urllib.parse.quote(args.device_id)}",
        method="PATCH",
        headers=_build_headers(args, needs_admin=True),
        body=body,
    )
    _print_json(data)


def _cmd_live_stream(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {}
    if args.device_id:
        params["device_id"] = args.device_id
    if args.event_name:
        params["event_name"] = args.event_name
    if args.since_seconds > 0:
        params["since_seconds"] = args.since_seconds
    for value in [item.strip() for item in args.source_kinds.split(",") if item.strip()]:
        params.setdefault("source_kind", [])
        params["source_kind"].append(value)
    query = urllib.parse.urlencode(params, doseq=True)
    data = _request_sse(
        base_url=args.base_url,
        path=f"/api/v1/event-stream{f'?{query}' if query else ''}",
        headers=_build_headers(args, needs_admin=False),
        max_events=args.max_events,
        timeout_s=args.timeout_s,
    )
    _print_json(data)


def _cmd_operator_events(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"limit": args.limit, "offset": args.offset}
    if args.device_id:
        params["device_id"] = args.device_id
    if args.event_name:
        params["event_name"] = args.event_name
    for value in [item.strip() for item in args.source_kinds.split(",") if item.strip()]:
        params.setdefault("source_kind", [])
        params["source_kind"].append(value)
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/operator-events?{urllib.parse.urlencode(params, doseq=True)}",
        method="GET",
        headers=_build_headers(args, needs_admin=False),
    )
    _print_json(data)


def _cmd_notification_destinations_list(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path="/api/v1/admin/notification-destinations",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_notification_destinations_create(args: argparse.Namespace) -> None:
    source_types = [value.strip() for value in args.source_types.split(",") if value.strip()]
    event_types = [value.strip() for value in args.event_types.split(",") if value.strip()]
    if not source_types:
        raise SystemExit("at least one source type is required")
    data = _request_json(
        base_url=args.base_url,
        path="/api/v1/admin/notification-destinations",
        method="POST",
        headers=_build_headers(args, needs_admin=True),
        body={
            "name": args.name,
            "channel": "webhook",
            "kind": args.kind,
            "webhook_url": args.webhook_url,
            "source_types": source_types,
            "event_types": event_types,
            "enabled": not args.disabled,
        },
    )
    _print_json(data)


def _cmd_notification_destinations_update(args: argparse.Namespace) -> None:
    body: dict[str, Any] = {}
    if args.name is not None:
        body["name"] = args.name
    if args.kind is not None:
        body["kind"] = args.kind
    if args.webhook_url is not None:
        body["webhook_url"] = args.webhook_url
    if args.source_types is not None:
        body["source_types"] = [value.strip() for value in args.source_types.split(",") if value.strip()]
    if args.event_types is not None:
        body["event_types"] = [value.strip() for value in args.event_types.split(",") if value.strip()]
    if args.enabled:
        body["enabled"] = True
    if args.disabled:
        body["enabled"] = False
    if not body:
        raise SystemExit("at least one field must be supplied for update")
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/notification-destinations/{urllib.parse.quote(args.destination_id)}",
        method="PATCH",
        headers=_build_headers(args, needs_admin=True),
        body=body,
    )
    _print_json(data)


def _cmd_notification_destinations_delete(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/notification-destinations/{urllib.parse.quote(args.destination_id)}",
        method="DELETE",
        headers=_build_headers(args, needs_admin=True),
        body={},
    )
    _print_json(data)


def _cmd_admin_events(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"limit": args.limit}
    if args.action:
        params["action"] = args.action
    if args.target_type:
        params["target_type"] = args.target_type
    if args.device_id:
        params["device_id"] = args.device_id
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/events?{urllib.parse.urlencode(params)}",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_admin_events_page(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"limit": args.limit, "offset": args.offset}
    if args.action:
        params["action"] = args.action
    if args.target_type:
        params["target_type"] = args.target_type
    if args.device_id:
        params["device_id"] = args.device_id
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/events-page?{urllib.parse.urlencode(params)}",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_admin_ingestions(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"limit": args.limit}
    if args.device_id:
        params["device_id"] = args.device_id
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/ingestions?{urllib.parse.urlencode(params)}",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_admin_ingestions_page(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"limit": args.limit, "offset": args.offset}
    if args.device_id:
        params["device_id"] = args.device_id
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/ingestions-page?{urllib.parse.urlencode(params)}",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_admin_drift_events(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"limit": args.limit}
    if args.device_id:
        params["device_id"] = args.device_id
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/drift-events?{urllib.parse.urlencode(params)}",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_admin_drift_events_page(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"limit": args.limit, "offset": args.offset}
    if args.device_id:
        params["device_id"] = args.device_id
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/drift-events-page?{urllib.parse.urlencode(params)}",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_admin_notifications(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"limit": args.limit}
    if args.device_id:
        params["device_id"] = args.device_id
    if args.source_kind:
        params["source_kind"] = args.source_kind
    if args.channel:
        params["channel"] = args.channel
    if args.decision:
        params["decision"] = args.decision
    if args.delivered != "any":
        params["delivered"] = str(args.delivered == "true").lower()
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/notifications?{urllib.parse.urlencode(params)}",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_admin_notifications_page(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"limit": args.limit, "offset": args.offset}
    if args.device_id:
        params["device_id"] = args.device_id
    if args.source_kind:
        params["source_kind"] = args.source_kind
    if args.channel:
        params["channel"] = args.channel
    if args.decision:
        params["decision"] = args.decision
    if args.delivered != "any":
        params["delivered"] = str(args.delivered == "true").lower()
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/notifications-page?{urllib.parse.urlencode(params)}",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_admin_exports(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"limit": args.limit}
    if args.status:
        params["status"] = args.status
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/exports?{urllib.parse.urlencode(params)}",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_admin_exports_page(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {"limit": args.limit, "offset": args.offset}
    if args.status:
        params["status"] = args.status
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/exports-page?{urllib.parse.urlencode(params)}",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_admin_edge_policy_source(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path="/api/v1/admin/contracts/edge-policy/source",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_admin_edge_policy_update(args: argparse.Namespace) -> None:
    body = {"yaml_text": args.yaml_text}
    data = _request_json(
        base_url=args.base_url,
        path="/api/v1/admin/contracts/edge-policy",
        method="PATCH",
        headers=_build_headers(args, needs_admin=True),
        body=body,
    )
    _print_json(data)


def _cmd_release_manifests_list(args: argparse.Namespace) -> None:
    params_raw: dict[str, Any] = {"limit": args.limit}
    if args.status:
        params_raw["status"] = args.status
    params = urllib.parse.urlencode(params_raw)
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/releases/manifests?{params}",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_release_manifests_create(args: argparse.Namespace) -> None:
    body = {
        "git_tag": args.git_tag,
        "commit_sha": args.commit_sha,
        "update_type": args.update_type,
        "artifact_uri": args.artifact_uri,
        "artifact_size": args.artifact_size,
        "artifact_sha256": args.artifact_sha256,
        "artifact_signature": args.artifact_signature,
        "artifact_signature_scheme": args.artifact_signature_scheme,
        "compatibility": _parse_json_arg(args.compatibility, label="compatibility"),
        "signature": args.signature,
        "signature_key_id": args.signature_key_id,
        "constraints": _parse_json_arg(args.constraints, label="constraints"),
        "status": args.status,
    }
    data = _request_json(
        base_url=args.base_url,
        path="/api/v1/admin/releases/manifests",
        method="POST",
        headers=_build_headers(args, needs_admin=True),
        body=body,
    )
    _print_json(data)


def _cmd_release_manifests_update_status(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/releases/manifests/{urllib.parse.quote(args.manifest_id)}",
        method="PATCH",
        headers=_build_headers(args, needs_admin=True),
        body={"status": args.status},
    )
    _print_json(data)


def _cmd_deployments_list(args: argparse.Namespace) -> None:
    params_raw: dict[str, Any] = {"limit": args.limit}
    if args.status:
        params_raw["status"] = args.status
    if args.manifest_id:
        params_raw["manifest_id"] = args.manifest_id
    if args.selector_channel:
        params_raw["selector_channel"] = args.selector_channel
    params = urllib.parse.urlencode(params_raw)
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/deployments?{params}",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_deployment_targets_list(args: argparse.Namespace) -> None:
    params_raw: dict[str, Any] = {"limit": args.limit, "offset": args.offset}
    if args.status:
        params_raw["status"] = args.status
    if args.query:
        params_raw["q"] = args.query
    params = urllib.parse.urlencode(params_raw)
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/deployments/{urllib.parse.quote(args.deployment_id)}/targets?{params}",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_deployments_get(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/deployments/{urllib.parse.quote(args.deployment_id)}",
        method="GET",
        headers=_build_headers(args, needs_admin=True),
    )
    _print_json(data)


def _cmd_deployments_create(args: argparse.Namespace) -> None:
    selector: dict[str, Any] = {"mode": args.selector_mode}
    if args.selector_mode == "cohort":
        selector["cohort"] = args.cohort
    elif args.selector_mode == "channel":
        selector["channel"] = args.channel
    elif args.selector_mode == "labels":
        selector["labels"] = _parse_json_arg(args.labels, label="labels")
    elif args.selector_mode == "explicit_ids":
        selector["device_ids"] = [value.strip() for value in args.device_ids.split(",") if value.strip()]
    body = {
        "manifest_id": args.manifest_id,
        "target_selector": selector,
        "rollout_stages_pct": [int(v) for v in args.rollout_stages.split(",") if v.strip()],
        "failure_rate_threshold": args.failure_rate_threshold,
        "no_quorum_timeout_s": args.no_quorum_timeout_s,
        "stage_timeout_s": args.stage_timeout_s,
        "defer_rate_threshold": args.defer_rate_threshold,
        "health_timeout_s": args.health_timeout_s,
        "command_ttl_s": args.command_ttl_s,
        "power_guard_required": not args.no_power_guard,
        "rollback_to_tag": args.rollback_to_tag,
    }
    data = _request_json(
        base_url=args.base_url,
        path="/api/v1/admin/deployments",
        method="POST",
        headers=_build_headers(args, needs_admin=True),
        body=body,
    )
    _print_json(data)


def _cmd_deployments_pause(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/deployments/{urllib.parse.quote(args.deployment_id)}/pause",
        method="POST",
        headers=_build_headers(args, needs_admin=True),
        body={},
    )
    _print_json(data)


def _cmd_deployments_resume(args: argparse.Namespace) -> None:
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/deployments/{urllib.parse.quote(args.deployment_id)}/resume",
        method="POST",
        headers=_build_headers(args, needs_admin=True),
        body={},
    )
    _print_json(data)


def _cmd_deployments_abort(args: argparse.Namespace) -> None:
    suffix = ""
    if args.reason:
        suffix = "?" + urllib.parse.urlencode({"reason": args.reason})
    data = _request_json(
        base_url=args.base_url,
        path=f"/api/v1/admin/deployments/{urllib.parse.quote(args.deployment_id)}/abort{suffix}",
        method="POST",
        headers=_build_headers(args, needs_admin=True),
        body={},
    )
    _print_json(data)


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default="http://localhost:8082", help="API base URL")
    parser.add_argument("--admin-key", default="", help="Admin key for admin routes")
    parser.add_argument(
        "--dev-principal-email", default="", help="Dev principal email header for local authz testing"
    )
    parser.add_argument(
        "--dev-principal-role", default="", help="Dev principal role header for local authz testing"
    )
    parser.add_argument(
        "--header", action="append", default=[], help="Extra header as Key=Value (repeatable)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EdgeWatch operator CLI")
    _add_common_args(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    health = sub.add_parser("health", help="Read API health")
    health.set_defaults(func=_cmd_health)

    contracts = sub.add_parser("contracts", help="Read public contracts")
    contracts_sub = contracts.add_subparsers(dest="contracts_command", required=True)

    contracts_telemetry = contracts_sub.add_parser("telemetry", help="Read telemetry contract")
    contracts_telemetry.set_defaults(func=_cmd_contracts_telemetry)

    contracts_edge_policy = contracts_sub.add_parser("edge-policy", help="Read edge policy contract")
    contracts_edge_policy.set_defaults(func=_cmd_contracts_edge_policy)

    search = sub.add_parser("search", help="Run unified operator search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=25)
    search.add_argument("--offset", type=int, default=0)
    search.add_argument("--entity-types", default="")
    search.set_defaults(func=_cmd_search)

    search_page = sub.add_parser("search-page", help="Run paged operator search with totals")
    search_page.add_argument("query")
    search_page.add_argument("--limit", type=int, default=25)
    search_page.add_argument("--offset", type=int, default=0)
    search_page.add_argument("--entity-types", default="")
    search_page.set_defaults(func=_cmd_search_page)

    alerts = sub.add_parser("alerts", help="List alerts")
    alerts.add_argument("--device-id", default="")
    alerts.add_argument("--open-only", action="store_true")
    alerts.add_argument("--severity", default="")
    alerts.add_argument("--alert-type", default="")
    alerts.add_argument("--query", default="")
    alerts.add_argument("--limit", type=int, default=50)
    alerts.set_defaults(func=_cmd_alerts)

    telemetry = sub.add_parser("telemetry", help="List raw device telemetry points")
    telemetry.add_argument("--device-id", required=True)
    telemetry.add_argument("--metric", default="")
    telemetry.add_argument("--since", default="")
    telemetry.add_argument("--until", default="")
    telemetry.add_argument("--limit", type=int, default=200)
    telemetry.set_defaults(func=_cmd_telemetry)

    timeseries = sub.add_parser("timeseries", help="List bucketed device timeseries")
    timeseries.add_argument("--device-id", required=True)
    timeseries.add_argument("--metric", required=True)
    timeseries.add_argument("--bucket", choices=["minute", "hour"], default="minute")
    timeseries.add_argument("--since", default="")
    timeseries.add_argument("--until", default="")
    timeseries.add_argument("--limit", type=int)
    timeseries.set_defaults(func=_cmd_timeseries)

    fleets = sub.add_parser("fleets", help="Fleet operations")
    fleets_sub = fleets.add_subparsers(dest="fleets_command", required=True)

    fleets_list = fleets_sub.add_parser("list", help="List fleets")
    fleets_list.add_argument("--admin", action="store_true", help="Use admin fleet list endpoint")
    fleets_list.set_defaults(func=_cmd_fleets_list)

    fleets_devices = fleets_sub.add_parser("devices", help="List devices in an accessible fleet")
    fleets_devices.add_argument("--fleet-id", required=True)
    fleets_devices.set_defaults(func=_cmd_fleets_devices)

    fleets_create = fleets_sub.add_parser("create", help="Create fleet")
    fleets_create.add_argument("--name", required=True)
    fleets_create.add_argument("--description", default="")
    fleets_create.add_argument("--default-ota-channel", default="stable")
    fleets_create.set_defaults(func=_cmd_fleets_create)

    fleets_add_device = fleets_sub.add_parser("add-device", help="Add device to fleet")
    fleets_add_device.add_argument("--fleet-id", required=True)
    fleets_add_device.add_argument("--device-id", required=True)
    fleets_add_device.set_defaults(func=_cmd_fleets_add_device)

    fleets_remove_device = fleets_sub.add_parser("remove-device", help="Remove device from fleet")
    fleets_remove_device.add_argument("--fleet-id", required=True)
    fleets_remove_device.add_argument("--device-id", required=True)
    fleets_remove_device.set_defaults(func=_cmd_fleets_remove_device)

    fleets_grant = fleets_sub.add_parser("grant", help="Grant fleet access")
    fleets_grant.add_argument("--fleet-id", required=True)
    fleets_grant.add_argument("--email", required=True)
    fleets_grant.add_argument("--role", choices=["viewer", "operator", "owner"], required=True)
    fleets_grant.set_defaults(func=_cmd_fleets_grant)

    fleets_access_list = fleets_sub.add_parser("access-list", help="List fleet access grants")
    fleets_access_list.add_argument("--fleet-id", required=True)
    fleets_access_list.set_defaults(func=_cmd_fleets_access_list)

    fleets_revoke = fleets_sub.add_parser("revoke", help="Revoke fleet access grant")
    fleets_revoke.add_argument("--fleet-id", required=True)
    fleets_revoke.add_argument("--email", required=True)
    fleets_revoke.set_defaults(func=_cmd_fleets_revoke)

    fleets_update = fleets_sub.add_parser("update", help="Update fleet metadata or default OTA channel")
    fleets_update.add_argument("--fleet-id", required=True)
    fleets_update.add_argument("--description")
    fleets_update.add_argument("--default-ota-channel")
    fleets_update.set_defaults(func=_cmd_fleets_update)

    procedures = sub.add_parser("procedures", help="Procedure definition and invocation operations")
    procedures_sub = procedures.add_subparsers(dest="procedures_command", required=True)

    procedures_list = procedures_sub.add_parser("list", help="List procedure definitions")
    procedures_list.set_defaults(func=_cmd_procedures_list)

    procedures_create = procedures_sub.add_parser("create", help="Create a procedure definition")
    procedures_create.add_argument("--name", required=True)
    procedures_create.add_argument("--description", default="")
    procedures_create.add_argument("--timeout-s", type=int, default=300)
    procedures_create.add_argument("--request-schema", default="{}")
    procedures_create.add_argument("--response-schema", default="{}")
    procedures_create.add_argument("--disabled", action="store_true")
    procedures_create.set_defaults(func=_cmd_procedures_create)

    procedures_update = procedures_sub.add_parser("update", help="Update a procedure definition")
    procedures_update.add_argument("--definition-id", required=True)
    procedures_update.add_argument("--description")
    procedures_update.add_argument("--timeout-s", type=int)
    procedures_update.add_argument("--request-schema")
    procedures_update.add_argument("--response-schema")
    procedures_update.add_argument("--enabled", action="store_true")
    procedures_update.add_argument("--disabled", action="store_true")
    procedures_update.set_defaults(func=_cmd_procedures_update)

    procedures_invoke = procedures_sub.add_parser("invoke", help="Invoke a device procedure")
    procedures_invoke.add_argument("--device-id", required=True)
    procedures_invoke.add_argument("--name", required=True)
    procedures_invoke.add_argument("--payload", default="{}")
    procedures_invoke.add_argument("--ttl-s", type=int, default=300)
    procedures_invoke.set_defaults(func=_cmd_procedures_invoke)

    procedures_history = procedures_sub.add_parser("history", help="List device procedure history")
    procedures_history.add_argument("--device-id", required=True)
    procedures_history.add_argument("--limit", type=int, default=50)
    procedures_history.set_defaults(func=_cmd_procedures_history)

    device_state = sub.add_parser("device-state", help="Read latest reported device state")
    device_state.add_argument("--device-id", required=True)
    device_state.set_defaults(func=_cmd_device_state)

    device_events = sub.add_parser("device-events", help="List device events")
    device_events.add_argument("--device-id", default="")
    device_events.add_argument("--event-type", default="")
    device_events.add_argument("--limit", type=int, default=100)
    device_events.set_defaults(func=_cmd_device_events)

    media = sub.add_parser("media", help="Device media operations")
    media_sub = media.add_subparsers(dest="media_command", required=True)

    media_list = media_sub.add_parser("list", help="List media for a device")
    media_list.add_argument("--device-id", required=True)
    media_list.add_argument("--token", required=True)
    media_list.add_argument("--limit", type=int, default=100)
    media_list.set_defaults(func=_cmd_media_list)

    media_download = media_sub.add_parser("download", help="Download media payload to a file")
    media_download.add_argument("--media-id", required=True)
    media_download.add_argument("--token", required=True)
    media_download.add_argument("--output", required=True)
    media_download.set_defaults(func=_cmd_media_download)

    ota_validation = sub.add_parser("ota-validation", help="System-image validation helper commands")
    ota_validation_sub = ota_validation.add_subparsers(dest="ota_validation_command", required=True)

    ota_collect = ota_validation_sub.add_parser("collect", help="Collect system-image validation evidence")
    ota_collect.add_argument("--device-id", required=True)
    ota_collect.add_argument("--update-state-path", default="")
    ota_collect.add_argument("--stage-dir", default="")
    ota_collect.add_argument("--output", required=True)
    ota_collect.set_defaults(func=_cmd_ota_validation_collect)

    ota_evaluate = ota_validation_sub.add_parser("evaluate", help="Evaluate collected system-image evidence")
    ota_evaluate.add_argument("--scenario", required=True, choices=["good_release", "rollback_drill"])
    ota_evaluate.add_argument("--evidence-json", required=True)
    ota_evaluate.set_defaults(func=_cmd_ota_validation_evaluate)

    ota_run = ota_validation_sub.add_parser(
        "run", help="Collect and immediately evaluate system-image validation evidence"
    )
    ota_run.add_argument("--device-id", required=True)
    ota_run.add_argument("--scenario", required=True, choices=["good_release", "rollback_drill"])
    ota_run.add_argument("--update-state-path", default="")
    ota_run.add_argument("--stage-dir", default="")
    ota_run.add_argument("--output", required=True)
    ota_run.set_defaults(func=_cmd_ota_validation_run)

    devices = sub.add_parser("devices", help="Device admin operations")
    devices_sub = devices.add_subparsers(dest="devices_command", required=True)

    devices_list = devices_sub.add_parser("list", help="List devices")
    devices_list.add_argument("--admin", action="store_true", help="Use admin device list endpoint")
    devices_list.set_defaults(func=_cmd_devices_list)

    devices_get = devices_sub.add_parser("get", help="Get one device detail")
    devices_get.add_argument("--device-id", required=True)
    devices_get.set_defaults(func=_cmd_devices_get)

    devices_summary = devices_sub.add_parser("summary", help="List fleet-friendly device summaries")
    devices_summary.add_argument("--metrics", default="")
    devices_summary.add_argument("--limit-metrics", type=int)
    devices_summary.set_defaults(func=_cmd_devices_summary)

    devices_create = devices_sub.add_parser("create", help="Create/register a device")
    devices_create.add_argument("--device-id", required=True)
    devices_create.add_argument("--token", required=True)
    devices_create.add_argument("--display-name", default="")
    devices_create.add_argument("--heartbeat-interval-s", type=int)
    devices_create.add_argument("--offline-after-s", type=int)
    devices_create.add_argument("--owner-emails", default="")
    devices_create.set_defaults(func=_cmd_devices_create)

    devices_access_list = devices_sub.add_parser("access-list", help="List device access grants")
    devices_access_list.add_argument("--device-id", required=True)
    devices_access_list.set_defaults(func=_cmd_devices_access_list)

    devices_access_grant = devices_sub.add_parser("access-grant", help="Grant device access")
    devices_access_grant.add_argument("--device-id", required=True)
    devices_access_grant.add_argument("--email", required=True)
    devices_access_grant.add_argument("--role", choices=["viewer", "operator", "owner"], required=True)
    devices_access_grant.set_defaults(func=_cmd_devices_access_grant)

    devices_access_revoke = devices_sub.add_parser("access-revoke", help="Revoke device access")
    devices_access_revoke.add_argument("--device-id", required=True)
    devices_access_revoke.add_argument("--email", required=True)
    devices_access_revoke.set_defaults(func=_cmd_devices_access_revoke)

    devices_update = devices_sub.add_parser("update", help="Update device metadata/config")
    devices_update.add_argument("--device-id", required=True)
    devices_update.add_argument("--display-name")
    devices_update.add_argument("--token")
    devices_update.add_argument("--heartbeat-interval-s", type=int)
    devices_update.add_argument("--offline-after-s", type=int)
    devices_update.add_argument("--enabled", action="store_true")
    devices_update.add_argument("--disabled", action="store_true")
    devices_update.set_defaults(func=_cmd_devices_update)

    devices_controls_get = devices_sub.add_parser("controls-get", help="Read current device control state")
    devices_controls_get.add_argument("--device-id", required=True)
    devices_controls_get.set_defaults(func=_cmd_devices_controls_get)

    devices_operation_set = devices_sub.add_parser("operation-set", help="Set operation/runtime power mode")
    devices_operation_set.add_argument("--device-id", required=True)
    devices_operation_set.add_argument(
        "--operation-mode", choices=["active", "sleep", "disabled"], required=True
    )
    devices_operation_set.add_argument("--sleep-poll-interval-s", type=int)
    devices_operation_set.add_argument("--runtime-power-mode", choices=["continuous", "eco", "deep_sleep"])
    devices_operation_set.add_argument(
        "--deep-sleep-backend", choices=["auto", "pi5_rtc", "external_supervisor", "none"]
    )
    devices_operation_set.set_defaults(func=_cmd_devices_operation_set)

    devices_alerts_set = devices_sub.add_parser("alerts-set", help="Set or clear device alert mute window")
    devices_alerts_set.add_argument("--device-id", required=True)
    devices_alerts_set.add_argument("--alerts-muted-until")
    devices_alerts_set.add_argument("--alerts-muted-reason")
    devices_alerts_set.add_argument("--clear", action="store_true")
    devices_alerts_set.set_defaults(func=_cmd_devices_alerts_set)

    devices_update_ota = devices_sub.add_parser("update-ota", help="Update per-device OTA governance")
    devices_update_ota.add_argument("--device-id", required=True)
    devices_update_ota.add_argument("--ota-channel")
    devices_update_ota.add_argument("--updates-enabled", action="store_true")
    devices_update_ota.add_argument("--updates-disabled", action="store_true")
    devices_update_ota.add_argument("--busy-reason")
    devices_update_ota.add_argument("--clear-busy-reason", action="store_true")
    devices_update_ota.add_argument("--development", action="store_true")
    devices_update_ota.add_argument("--not-development", action="store_true")
    devices_update_ota.add_argument("--locked-manifest-id")
    devices_update_ota.add_argument("--clear-locked-manifest-id", action="store_true")
    devices_update_ota.set_defaults(func=_cmd_devices_update_ota)

    devices_shutdown = devices_sub.add_parser("shutdown", help="Queue admin disable + shutdown intent")
    devices_shutdown.add_argument("--device-id", required=True)
    devices_shutdown.add_argument("--reason", required=True)
    devices_shutdown.add_argument("--shutdown-grace-s", type=int, default=30)
    devices_shutdown.set_defaults(func=_cmd_devices_shutdown)

    live_stream = sub.add_parser("live-stream", help="Read filtered live SSE events")
    live_stream.add_argument("--device-id", default="")
    live_stream.add_argument(
        "--source-kinds",
        default="alert,notification_event,device_event,procedure_invocation,deployment_event,release_manifest_event,admin_event",
    )
    live_stream.add_argument("--event-name", default="")
    live_stream.add_argument("--since-seconds", type=int, default=300)
    live_stream.add_argument("--max-events", type=int, default=10)
    live_stream.add_argument("--timeout-s", type=float, default=5.0)
    live_stream.set_defaults(func=_cmd_live_stream)

    operator_events = sub.add_parser("operator-events", help="List paged unified operator events")
    operator_events.add_argument("--device-id", default="")
    operator_events.add_argument(
        "--source-kinds",
        default="alert,notification_event,device_event,procedure_invocation,deployment_event,release_manifest_event,admin_event",
    )
    operator_events.add_argument("--event-name", default="")
    operator_events.add_argument("--limit", type=int, default=25)
    operator_events.add_argument("--offset", type=int, default=0)
    operator_events.set_defaults(func=_cmd_operator_events)

    destinations = sub.add_parser("notification-destinations", help="Notification destination operations")
    dest_sub = destinations.add_subparsers(dest="destinations_command", required=True)

    destinations_list = dest_sub.add_parser("list", help="List notification destinations")
    destinations_list.set_defaults(func=_cmd_notification_destinations_list)

    destinations_create = dest_sub.add_parser("create", help="Create a notification destination")
    destinations_create.add_argument("--name", required=True)
    destinations_create.add_argument(
        "--kind", choices=["generic", "slack", "discord", "telegram"], default="generic"
    )
    destinations_create.add_argument("--webhook-url", required=True)
    destinations_create.add_argument("--source-types", default="alert")
    destinations_create.add_argument("--event-types", default="")
    destinations_create.add_argument("--disabled", action="store_true")
    destinations_create.set_defaults(func=_cmd_notification_destinations_create)

    destinations_update = dest_sub.add_parser("update", help="Update a notification destination")
    destinations_update.add_argument("--destination-id", required=True)
    destinations_update.add_argument("--name")
    destinations_update.add_argument("--kind", choices=["generic", "slack", "discord", "telegram"])
    destinations_update.add_argument("--webhook-url")
    destinations_update.add_argument("--source-types")
    destinations_update.add_argument("--event-types")
    destinations_update.add_argument("--enabled", action="store_true")
    destinations_update.add_argument("--disabled", action="store_true")
    destinations_update.set_defaults(func=_cmd_notification_destinations_update)

    destinations_delete = dest_sub.add_parser("delete", help="Delete a notification destination")
    destinations_delete.add_argument("--destination-id", required=True)
    destinations_delete.set_defaults(func=_cmd_notification_destinations_delete)

    admin = sub.add_parser("admin", help="Admin audit/history operations")
    admin_sub = admin.add_subparsers(dest="admin_command", required=True)

    admin_events = admin_sub.add_parser("events", help="List admin audit events")
    admin_events.add_argument("--action", default="")
    admin_events.add_argument("--target-type", default="")
    admin_events.add_argument("--device-id", default="")
    admin_events.add_argument("--limit", type=int, default=100)
    admin_events.set_defaults(func=_cmd_admin_events)

    admin_events_page = admin_sub.add_parser("events-page", help="List paged admin audit events")
    admin_events_page.add_argument("--action", default="")
    admin_events_page.add_argument("--target-type", default="")
    admin_events_page.add_argument("--device-id", default="")
    admin_events_page.add_argument("--limit", type=int, default=100)
    admin_events_page.add_argument("--offset", type=int, default=0)
    admin_events_page.set_defaults(func=_cmd_admin_events_page)

    admin_ingestions = admin_sub.add_parser("ingestions", help="List ingestion lineage batches")
    admin_ingestions.add_argument("--device-id", default="")
    admin_ingestions.add_argument("--limit", type=int, default=100)
    admin_ingestions.set_defaults(func=_cmd_admin_ingestions)

    admin_ingestions_page = admin_sub.add_parser(
        "ingestions-page", help="List paged ingestion lineage batches"
    )
    admin_ingestions_page.add_argument("--device-id", default="")
    admin_ingestions_page.add_argument("--limit", type=int, default=100)
    admin_ingestions_page.add_argument("--offset", type=int, default=0)
    admin_ingestions_page.set_defaults(func=_cmd_admin_ingestions_page)

    admin_drift = admin_sub.add_parser("drift-events", help="List drift audit events")
    admin_drift.add_argument("--device-id", default="")
    admin_drift.add_argument("--limit", type=int, default=100)
    admin_drift.set_defaults(func=_cmd_admin_drift_events)

    admin_drift_page = admin_sub.add_parser("drift-events-page", help="List paged drift audit events")
    admin_drift_page.add_argument("--device-id", default="")
    admin_drift_page.add_argument("--limit", type=int, default=100)
    admin_drift_page.add_argument("--offset", type=int, default=0)
    admin_drift_page.set_defaults(func=_cmd_admin_drift_events_page)

    admin_notifications = admin_sub.add_parser(
        "notifications", help="List notification delivery audit events"
    )
    admin_notifications.add_argument("--device-id", default="")
    admin_notifications.add_argument("--source-kind", default="")
    admin_notifications.add_argument("--channel", default="")
    admin_notifications.add_argument("--decision", default="")
    admin_notifications.add_argument("--delivered", choices=["any", "true", "false"], default="any")
    admin_notifications.add_argument("--limit", type=int, default=100)
    admin_notifications.set_defaults(func=_cmd_admin_notifications)

    admin_notifications_page = admin_sub.add_parser(
        "notifications-page", help="List paged notification delivery audit events"
    )
    admin_notifications_page.add_argument("--device-id", default="")
    admin_notifications_page.add_argument("--source-kind", default="")
    admin_notifications_page.add_argument("--channel", default="")
    admin_notifications_page.add_argument("--decision", default="")
    admin_notifications_page.add_argument("--delivered", choices=["any", "true", "false"], default="any")
    admin_notifications_page.add_argument("--limit", type=int, default=100)
    admin_notifications_page.add_argument("--offset", type=int, default=0)
    admin_notifications_page.set_defaults(func=_cmd_admin_notifications_page)

    admin_exports = admin_sub.add_parser("exports", help="List analytics export batches")
    admin_exports.add_argument("--status", default="")
    admin_exports.add_argument("--limit", type=int, default=100)
    admin_exports.set_defaults(func=_cmd_admin_exports)

    admin_exports_page = admin_sub.add_parser("exports-page", help="List paged analytics export batches")
    admin_exports_page.add_argument("--status", default="")
    admin_exports_page.add_argument("--limit", type=int, default=100)
    admin_exports_page.add_argument("--offset", type=int, default=0)
    admin_exports_page.set_defaults(func=_cmd_admin_exports_page)

    admin_edge_policy_source = admin_sub.add_parser(
        "edge-policy-source", help="Read active edge policy YAML source"
    )
    admin_edge_policy_source.set_defaults(func=_cmd_admin_edge_policy_source)

    admin_edge_policy_update = admin_sub.add_parser(
        "edge-policy-update", help="Replace active edge policy YAML source"
    )
    admin_edge_policy_update.add_argument("--yaml-text", required=True)
    admin_edge_policy_update.set_defaults(func=_cmd_admin_edge_policy_update)

    releases = sub.add_parser("releases", help="Release/deployment inspection")
    releases_sub = releases.add_subparsers(dest="releases_command", required=True)

    manifests_list = releases_sub.add_parser("manifests-list", help="List release manifests")
    manifests_list.add_argument("--limit", type=int, default=100)
    manifests_list.add_argument("--status", default="")
    manifests_list.set_defaults(func=_cmd_release_manifests_list)

    manifests_create = releases_sub.add_parser("manifests-create", help="Create release manifest")
    manifests_create.add_argument("--git-tag", required=True)
    manifests_create.add_argument("--commit-sha", required=True)
    manifests_create.add_argument(
        "--update-type",
        choices=["application_bundle", "asset_bundle", "system_image"],
        default="application_bundle",
    )
    manifests_create.add_argument("--artifact-uri", required=True)
    manifests_create.add_argument("--artifact-size", type=int, required=True)
    manifests_create.add_argument("--artifact-sha256", required=True)
    manifests_create.add_argument("--artifact-signature", default="")
    manifests_create.add_argument(
        "--artifact-signature-scheme", choices=["none", "openssl_rsa_sha256"], default="none"
    )
    manifests_create.add_argument("--compatibility", default="{}")
    manifests_create.add_argument("--signature", required=True)
    manifests_create.add_argument("--signature-key-id", required=True)
    manifests_create.add_argument("--constraints", default="{}")
    manifests_create.add_argument("--status", default="active")
    manifests_create.set_defaults(func=_cmd_release_manifests_create)

    manifests_update_status = releases_sub.add_parser(
        "manifests-update-status", help="Update release manifest status"
    )
    manifests_update_status.add_argument("--manifest-id", required=True)
    manifests_update_status.add_argument("--status", required=True)
    manifests_update_status.set_defaults(func=_cmd_release_manifests_update_status)

    deployment_list = releases_sub.add_parser("deployments-list", help="List deployments")
    deployment_list.add_argument("--limit", type=int, default=100)
    deployment_list.add_argument("--status", default="")
    deployment_list.add_argument("--manifest-id", default="")
    deployment_list.add_argument("--selector-channel", default="")
    deployment_list.set_defaults(func=_cmd_deployments_list)

    deployment_get = releases_sub.add_parser("deployment-get", help="Get deployment detail")
    deployment_get.add_argument("--deployment-id", required=True)
    deployment_get.set_defaults(func=_cmd_deployments_get)

    deployment_targets = releases_sub.add_parser(
        "deployment-targets-list", help="List paged deployment targets"
    )
    deployment_targets.add_argument("--deployment-id", required=True)
    deployment_targets.add_argument("--status", default="")
    deployment_targets.add_argument("--query", default="")
    deployment_targets.add_argument("--limit", type=int, default=100)
    deployment_targets.add_argument("--offset", type=int, default=0)
    deployment_targets.set_defaults(func=_cmd_deployment_targets_list)

    deployment_pause = releases_sub.add_parser("deployment-pause", help="Pause deployment")
    deployment_pause.add_argument("--deployment-id", required=True)
    deployment_pause.set_defaults(func=_cmd_deployments_pause)

    deployment_resume = releases_sub.add_parser("deployment-resume", help="Resume deployment")
    deployment_resume.add_argument("--deployment-id", required=True)
    deployment_resume.set_defaults(func=_cmd_deployments_resume)

    deployment_abort = releases_sub.add_parser("deployment-abort", help="Abort deployment")
    deployment_abort.add_argument("--deployment-id", required=True)
    deployment_abort.add_argument("--reason", default="")
    deployment_abort.set_defaults(func=_cmd_deployments_abort)

    deployment_create = releases_sub.add_parser("deployment-create", help="Create deployment")
    deployment_create.add_argument("--manifest-id", required=True)
    deployment_create.add_argument(
        "--selector-mode", choices=["all", "cohort", "channel", "labels", "explicit_ids"], default="all"
    )
    deployment_create.add_argument("--cohort", default="")
    deployment_create.add_argument("--channel", default="")
    deployment_create.add_argument("--labels", default="{}")
    deployment_create.add_argument("--device-ids", default="")
    deployment_create.add_argument("--rollout-stages", default="1,10,50,100")
    deployment_create.add_argument("--failure-rate-threshold", type=float, default=0.2)
    deployment_create.add_argument("--no-quorum-timeout-s", type=int, default=1800)
    deployment_create.add_argument("--stage-timeout-s", type=int, default=1800)
    deployment_create.add_argument("--defer-rate-threshold", type=float, default=0.5)
    deployment_create.add_argument("--health-timeout-s", type=int, default=300)
    deployment_create.add_argument("--command-ttl-s", type=int, default=180 * 24 * 3600)
    deployment_create.add_argument("--no-power-guard", action="store_true")
    deployment_create.add_argument("--rollback-to-tag", default=None)
    deployment_create.set_defaults(func=_cmd_deployments_create)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
