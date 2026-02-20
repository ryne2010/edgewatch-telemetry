from __future__ import annotations

from starlette.requests import Request

from api.app.edge_policy import load_edge_policy
from api.app.models import Device
from api.app.routes.device_policy import get_device_policy
from api.app.schemas import DevicePolicyOut
from fastapi import Response
from starlette.responses import Response as StarletteResponse


def _device(*, heartbeat_interval_s: int = 300, offline_after_s: int = 900) -> Device:
    # Unmapped instance; sufficient for route function.
    return Device(
        device_id="demo-001",
        display_name="Demo",
        token_hash="x",
        token_fingerprint="y",
        heartbeat_interval_s=heartbeat_interval_s,
        offline_after_s=offline_after_s,
        last_seen_at=None,
        enabled=True,
    )


def _request(headers: dict[str, str] | None = None) -> Request:
    hdrs = []
    if headers:
        for k, v in headers.items():
            hdrs.append((k.lower().encode("utf-8"), v.encode("utf-8")))

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/device-policy",
        "headers": hdrs,
    }
    return Request(scope)


def test_load_edge_policy_v1_has_expected_fields() -> None:
    p = load_edge_policy("v1")
    assert p.version == "v1"
    assert p.reporting.heartbeat_interval_s > 0
    assert p.alert_thresholds.water_pressure_low_psi > 0


def test_device_policy_sets_etag_and_supports_304() -> None:
    device = _device()

    req1 = _request()
    resp1 = Response()
    out1 = get_device_policy(req1, resp1, device)

    assert resp1.headers.get("etag")
    assert resp1.headers.get("cache-control")
    assert isinstance(out1, DevicePolicyOut)
    assert out1.device_id == device.device_id
    assert out1.reporting.heartbeat_interval_s == device.heartbeat_interval_s

    etag = resp1.headers.get("etag") or resp1.headers.get("ETag")
    assert etag

    req2 = _request({"If-None-Match": etag})
    resp2 = Response()
    out2 = get_device_policy(req2, resp2, device)

    # When ETag matches, route returns a Starlette Response with 304.
    assert isinstance(out2, StarletteResponse)
    assert out2.status_code == 304
