from __future__ import annotations

from api.app import observability as obs


class _DummyCounter:
    def __init__(self) -> None:
        self.calls: list[tuple[int, dict[str, object] | None]] = []

    def add(self, value: int, *, attributes: dict[str, object] | None = None) -> None:
        self.calls.append((value, attributes))


class _DummyHistogram:
    def __init__(self) -> None:
        self.calls: list[tuple[float, dict[str, object] | None]] = []

    def record(self, value: float, *, attributes: dict[str, object] | None = None) -> None:
        self.calls.append((value, attributes))


def test_http_request_metric_records_route_method_status() -> None:
    counter = _DummyCounter()
    histogram = _DummyHistogram()
    runtime = obs._OtelRuntime(
        http_requests_total=counter,
        http_request_duration_ms=histogram,
    )
    prev = obs._otel_runtime
    obs._otel_runtime = runtime
    try:
        obs.record_http_request_metric(
            method="get",
            route="/api/v1/devices/{device_id}",
            status_code=200,
            duration_ms=12.5,
        )
    finally:
        obs._otel_runtime = prev

    assert counter.calls == [
        (
            1,
            {
                "http.method": "GET",
                "http.route": "/api/v1/devices/{device_id}",
                "http.status_code": 200,
            },
        )
    ]
    assert histogram.calls == [
        (
            12.5,
            {
                "http.method": "GET",
                "http.route": "/api/v1/devices/{device_id}",
                "http.status_code": 200,
            },
        )
    ]


def test_ingest_points_metric_tracks_accepted_and_rejected() -> None:
    counter = _DummyCounter()
    runtime = obs._OtelRuntime(ingest_points_total=counter)
    prev = obs._otel_runtime
    obs._otel_runtime = runtime
    try:
        obs.record_ingest_points_metric(
            accepted=42,
            rejected=3,
            source="device",
            pipeline_mode="direct",
        )
    finally:
        obs._otel_runtime = prev

    assert counter.calls == [
        (42, {"source": "device", "pipeline_mode": "direct", "outcome": "accepted"}),
        (3, {"source": "device", "pipeline_mode": "direct", "outcome": "rejected"}),
    ]


def test_alert_transition_and_monitor_metrics_record_attributes() -> None:
    alert_counter = _DummyCounter()
    monitor_histogram = _DummyHistogram()
    runtime = obs._OtelRuntime(
        alert_transitions_total=alert_counter,
        monitor_loop_duration_ms=monitor_histogram,
    )
    prev = obs._otel_runtime
    obs._otel_runtime = runtime
    try:
        obs.record_alert_transition_metric(state="open", alert_type="DEVICE_OFFLINE", severity="warning")
        obs.record_monitor_loop_metric(duration_ms=250.0, success=False)
    finally:
        obs._otel_runtime = prev

    assert alert_counter.calls == [
        (
            1,
            {
                "state": "open",
                "alert_type": "DEVICE_OFFLINE",
                "severity": "warning",
            },
        )
    ]
    assert monitor_histogram.calls == [
        (
            250.0,
            {
                "success": False,
            },
        )
    ]
