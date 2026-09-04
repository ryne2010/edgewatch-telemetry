from __future__ import annotations

import importlib
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from agent.buffer import SqliteBuffer
from agent.telegram_transport import TelegramDeliveryResult, TelegramTransportConfig


AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

agent_main = importlib.import_module("edgewatch_agent")


class _StubTelegramTransport:
    def __init__(
        self,
        result: TelegramDeliveryResult,
        *,
        on_send: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.result = result
        self.on_send = on_send
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def send(self, device_id: str, point: dict[str, Any]) -> TelegramDeliveryResult:
        self.calls.append((device_id, point))
        if self.on_send is not None:
            self.on_send(device_id, point)
        return self.result


def _delivery_result(*, delivered: bool) -> TelegramDeliveryResult:
    return TelegramDeliveryResult(
        delivered=delivered,
        retry_after_s=None,
        status_code=200 if delivered else 503,
        reason="delivered" if delivered else "telegram HTTP failure (status=503)",
        bytes_sent=128,
    )


def _queued_point(message_id: str = "msg-1") -> dict[str, Any]:
    return {
        "message_id": message_id,
        "ts": "2026-08-09T12:00:00+00:00",
        "metrics": {"device_state": "NORMAL"},
    }


def test_agent_ready_receipt_is_durable_agent_owned_startup_proof(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ready_path = tmp_path / "state" / "ready.json"
    synced_directories: list[Path] = []
    monkeypatch.setenv("EDGEWATCH_READY_PATH", str(ready_path))
    monkeypatch.setattr(agent_main, "PROCESS_SESSION_ID", "session-123")
    monkeypatch.setattr(agent_main, "utcnow_iso", lambda: "2026-08-09T12:00:00+00:00")
    monkeypatch.setattr(agent_main, "_fsync_directory", synced_directories.append)

    written = agent_main._write_agent_ready_receipt(
        device_id="device-1",
        transport="telegram",
    )

    assert written == ready_path
    assert json.loads(ready_path.read_text(encoding="utf-8")) == {
        "device_id": "device-1",
        "pid": agent_main.os.getpid(),
        "process_session_id": "session-123",
        "started_at": "2026-08-09T12:00:00+00:00",
        "transport": "telegram",
    }
    assert synced_directories == [ready_path.parent]
    assert list(ready_path.parent.glob("*.tmp")) == []


def test_agent_ready_receipt_failure_is_fatal_and_removes_uncommitted_proof(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ready_path = tmp_path / "ready.json"
    monkeypatch.setenv("EDGEWATCH_READY_PATH", str(ready_path))
    monkeypatch.setattr(
        agent_main,
        "_fsync_directory",
        lambda _path: (_ for _ in ()).throw(OSError("fsync failed")),
    )

    with pytest.raises(RuntimeError, match="failed to publish agent readiness receipt"):
        agent_main._write_agent_ready_receipt(device_id="device-1", transport="telegram")

    assert not ready_path.exists()


def test_telegram_flush_deletes_point_after_delivery_confirmation(tmp_path: Path) -> None:
    buf = SqliteBuffer(str(tmp_path / "outbox.sqlite"))
    point = _queued_point()
    assert buf.enqueue(point["message_id"], point, point["ts"])
    transport = _StubTelegramTransport(_delivery_result(delivered=True))

    drained = agent_main._flush_telegram_buffer(
        buf=buf,
        transport=transport,
        device_id="device-1",
    )

    assert drained is True
    assert buf.count() == 0


def test_telegram_flush_retains_point_when_delivery_fails(tmp_path: Path) -> None:
    buf = SqliteBuffer(str(tmp_path / "outbox.sqlite"))
    point = _queued_point()
    assert buf.enqueue(point["message_id"], point, point["ts"])
    transport = _StubTelegramTransport(_delivery_result(delivered=False))

    with pytest.raises(RuntimeError, match="telegram HTTP failure"):
        agent_main._flush_telegram_buffer(
            buf=buf,
            transport=transport,
            device_id="device-1",
        )

    assert buf.dequeue_batch(limit=1)[0].payload == point


def test_telegram_flush_deadletters_permanent_point_then_sends_next(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    buf = SqliteBuffer(str(tmp_path / "outbox.sqlite"))
    poison = _queued_point("poison")
    valid = _queued_point("valid")
    assert buf.enqueue(poison["message_id"], poison, poison["ts"])
    assert buf.enqueue(valid["message_id"], valid, "2026-08-09T12:00:01+00:00")
    deadletter_path = tmp_path / "telegram-deadletter.jsonl"
    synced_directories: list[Path] = []
    monkeypatch.setenv("EDGEWATCH_DEADLETTER_PATH", str(deadletter_path))
    monkeypatch.setattr(agent_main, "_fsync_directory", synced_directories.append)

    results = iter(
        [
            TelegramDeliveryResult(
                delivered=False,
                retry_after_s=None,
                status_code=None,
                reason="telemetry document exceeds Telegram's 50 MB limit",
                bytes_sent=0,
                permanent=True,
            ),
            _delivery_result(delivered=True),
        ]
    )

    class SequencedTransport:
        def send(self, _device_id: str, _point: dict[str, Any]) -> TelegramDeliveryResult:
            return next(results)

    drained = agent_main._flush_telegram_buffer(
        buf=buf,
        transport=SequencedTransport(),
        device_id="device-1",
    )

    assert drained is True
    assert buf.count() == 0
    record = json.loads(deadletter_path.read_text(encoding="utf-8"))
    assert record["transport"] == "telegram"
    assert record["reason"] == "telemetry document exceeds Telegram's 50 MB limit"
    assert record["payload"] == poison
    assert synced_directories == [deadletter_path.parent]


class _StubBatchTransport(_StubTelegramTransport):
    def __init__(self, result: TelegramDeliveryResult, **config_changes: Any) -> None:
        super().__init__(result)
        self.config = replace(
            TelegramTransportConfig(
                transport="telegram", chat_id="42", bot_token="token", batch_enabled=True
            ),
            **config_changes,
        )
        self.batch_calls: list[tuple[str, list[dict[str, Any]]]] = []

    def serialized_envelope_size(self, device_id: str, point: dict[str, Any]) -> int:
        return (
            len(
                json.dumps(
                    {"device_id": device_id, "point": point},
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            )
            + 1
        )

    def send_batch(self, device_id: str, points: list[dict[str, Any]]) -> TelegramDeliveryResult:
        self.batch_calls.append((device_id, points))
        return self.result


def _fresh_created_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_batch_waits_durably_until_window_threshold(tmp_path: Path) -> None:
    buf = SqliteBuffer(str(tmp_path / "outbox.sqlite"))
    point = _queued_point()
    assert buf.enqueue(point["message_id"], point, _fresh_created_at())
    transport = _StubBatchTransport(
        _delivery_result(delivered=True),
        batch_max_points=3,
        batch_max_bytes=1_000_000,
        batch_max_age_s=3600,
    )

    assert agent_main._flush_telegram_buffer(buf=buf, transport=transport, device_id="device-1")

    assert transport.batch_calls == []
    assert buf.count() == 1


def test_batch_count_threshold_deletes_only_after_confirmation(tmp_path: Path) -> None:
    buf = SqliteBuffer(str(tmp_path / "outbox.sqlite"))
    points = [_queued_point(f"m{i}") for i in range(3)]
    for point in points:
        assert buf.enqueue(point["message_id"], point, _fresh_created_at())
    transport = _StubBatchTransport(
        _delivery_result(delivered=True), batch_max_points=3, batch_max_age_s=3600
    )
    deliveries: list[tuple[list[dict[str, Any]], TelegramDeliveryResult]] = []

    assert agent_main._flush_telegram_buffer(
        buf=buf,
        transport=transport,
        device_id="device-1",
        on_delivery=lambda sent, result: deliveries.append((sent, result)),
    )

    assert transport.batch_calls == [("device-1", points)]
    assert deliveries == [(points, transport.result)]
    assert buf.count() == 0


def test_batch_age_threshold_flushes_partial_batch(tmp_path: Path) -> None:
    buf = SqliteBuffer(str(tmp_path / "outbox.sqlite"))
    point = _queued_point("aged")
    assert buf.enqueue(point["message_id"], point, "2000-01-01T00:00:00+00:00")
    transport = _StubBatchTransport(_delivery_result(delivered=True), batch_max_points=10, batch_max_age_s=60)

    assert agent_main._flush_telegram_buffer(buf=buf, transport=transport, device_id="device-1")

    assert transport.batch_calls == [("device-1", [point])]
    assert buf.count() == 0


def test_batch_byte_window_flushes_fitting_prefix_and_retains_tail(tmp_path: Path) -> None:
    buf = SqliteBuffer(str(tmp_path / "outbox.sqlite"))
    first = _queued_point("first")
    second = _queued_point("second")
    for point in (first, second):
        assert buf.enqueue(point["message_id"], point, _fresh_created_at())
    sizing_transport = _StubBatchTransport(_delivery_result(delivered=True))
    max_single_point_bytes = max(
        sizing_transport.serialized_envelope_size("device-1", first),
        sizing_transport.serialized_envelope_size("device-1", second),
    )
    transport = _StubBatchTransport(
        _delivery_result(delivered=True),
        batch_max_points=10,
        batch_max_bytes=max_single_point_bytes + 10,
        batch_max_age_s=3600,
    )

    assert agent_main._flush_telegram_buffer(buf=buf, transport=transport, device_id="device-1")

    assert transport.batch_calls == [("device-1", [first])]
    assert [message.payload for message in buf.dequeue_batch(limit=5)] == [second]


def test_batch_failure_and_retry_after_retain_every_point(tmp_path: Path) -> None:
    buf = SqliteBuffer(str(tmp_path / "outbox.sqlite"))
    points = [_queued_point("m1"), _queued_point("m2")]
    for point in points:
        assert buf.enqueue(point["message_id"], point, _fresh_created_at())
    result = TelegramDeliveryResult(
        delivered=False,
        retry_after_s=17,
        status_code=429,
        reason="telegram API rejected delivery (error_code=429)",
        bytes_sent=64,
        estimated_wire_bytes=900,
    )
    transport = _StubBatchTransport(result, batch_max_points=2)

    with pytest.raises(agent_main.RateLimited) as exc_info:
        agent_main._flush_telegram_buffer(buf=buf, transport=transport, device_id="device-1")

    assert exc_info.value.retry_after_s == 17
    assert [message.payload for message in buf.dequeue_batch(limit=5)] == points


def test_batch_isolates_and_deadletters_poison_before_advancing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    buf = SqliteBuffer(str(tmp_path / "outbox.sqlite"))
    poison = _queued_point("poison")
    valid = _queued_point("valid")
    for point in (poison, valid):
        assert buf.enqueue(point["message_id"], point, _fresh_created_at())
    deadletter_path = tmp_path / "deadletter.jsonl"
    monkeypatch.setenv("EDGEWATCH_DEADLETTER_PATH", str(deadletter_path))
    permanent = TelegramDeliveryResult(
        delivered=False,
        retry_after_s=None,
        status_code=None,
        reason="telemetry document exceeds Telegram's 50 MB limit",
        bytes_sent=0,
        permanent=True,
    )

    class PoisonBatchTransport(_StubBatchTransport):
        def __init__(self) -> None:
            super().__init__(_delivery_result(delivered=True), batch_max_points=2)
            self.batch_results = iter([permanent, _delivery_result(delivered=True)])

        def send_batch(self, device_id: str, points: list[dict[str, Any]]) -> TelegramDeliveryResult:
            self.batch_calls.append((device_id, points))
            return next(self.batch_results)

        def send(self, device_id: str, point: dict[str, Any]) -> TelegramDeliveryResult:
            self.calls.append((device_id, point))
            return permanent

    transport = PoisonBatchTransport()

    assert agent_main._flush_telegram_buffer(
        buf=buf,
        transport=transport,
        device_id="device-1",
        force_immediate=True,
    )

    assert transport.calls == [("device-1", poison)]
    assert transport.batch_calls[-1] == ("device-1", [valid])
    assert buf.count() == 0
    assert json.loads(deadletter_path.read_text(encoding="utf-8"))["payload"] == poison


def test_immediate_startup_or_alert_path_flushes_partial_batch(tmp_path: Path) -> None:
    buf = SqliteBuffer(str(tmp_path / "outbox.sqlite"))
    point = _queued_point("urgent")
    assert buf.enqueue(point["message_id"], point, _fresh_created_at())
    transport = _StubBatchTransport(
        _delivery_result(delivered=True), batch_max_points=10, batch_max_age_s=3600
    )

    assert agent_main._flush_telegram_buffer(
        buf=buf,
        transport=transport,
        device_id="device-1",
        force_immediate=True,
    )

    assert transport.batch_calls == [("device-1", [point])]
    assert buf.count() == 0


def test_telegram_flush_limits_each_batch_to_remaining_wire_budget(tmp_path: Path) -> None:
    buf = SqliteBuffer(str(tmp_path / "outbox.sqlite"))
    first = _queued_point("first")
    second = _queued_point("second")
    for point in (first, second):
        assert buf.enqueue(point["message_id"], point, _fresh_created_at())
    transport = _StubBatchTransport(
        _delivery_result(delivered=True),
        batch_max_points=10,
        batch_max_bytes=1_000_000,
        batch_max_age_s=3600,
    )
    one_request_budget = agent_main._estimate_telegram_request_wire_bytes(
        transport,
        device_id="device-1",
        points=[first],
        batch=True,
    )

    assert agent_main._flush_telegram_buffer(
        buf=buf,
        transport=transport,
        device_id="device-1",
        force_immediate=True,
        max_wire_bytes=one_request_budget,
    )

    assert transport.batch_calls == [("device-1", [first])]
    assert [message.payload for message in buf.dequeue_batch(limit=5)] == [second]


def test_capped_urgent_point_bypasses_routine_backlog_without_deleting_it(tmp_path: Path) -> None:
    buf = SqliteBuffer(str(tmp_path / "outbox.sqlite"))
    routine = _queued_point("routine-backlog")
    urgent = _queued_point("current-alert")
    urgent["metrics"] = {"device_state": "WARN", "battery_v": 10.0}
    assert buf.enqueue(routine["message_id"], routine, "2026-08-09T11:00:00+00:00")
    assert buf.enqueue(urgent["message_id"], urgent, "2026-08-09T12:00:00+00:00")
    transport = _StubTelegramTransport(_delivery_result(delivered=True))
    urgent_budget = agent_main._estimate_telegram_request_wire_bytes(
        transport,
        device_id="device-1",
        points=[urgent],
        batch=False,
    )

    outcome = agent_main._send_telegram_buffered_point(
        buf=buf,
        transport=transport,
        device_id="device-1",
        point=urgent,
        max_wire_bytes=urgent_budget,
    )

    assert outcome == agent_main.TelegramPointDelivery(attempted=True, delivered=True)
    assert transport.calls == [("device-1", urgent)]
    assert [message.payload for message in buf.dequeue_batch(limit=5)] == [routine]


def test_urgent_point_stays_durable_when_reserve_cannot_fit_request(tmp_path: Path) -> None:
    buf = SqliteBuffer(str(tmp_path / "outbox.sqlite"))
    urgent = _queued_point("current-heartbeat")
    assert buf.enqueue(urgent["message_id"], urgent, urgent["ts"])
    transport = _StubTelegramTransport(_delivery_result(delivered=True))

    outcome = agent_main._send_telegram_buffered_point(
        buf=buf,
        transport=transport,
        device_id="device-1",
        point=urgent,
        max_wire_bytes=1,
    )

    assert outcome == agent_main.TelegramPointDelivery(attempted=False, delivered=False)
    assert transport.calls == []
    assert [message.payload for message in buf.dequeue_batch(limit=5)] == [urgent]


def test_telegram_reservation_failure_prevents_network_and_retains_row(tmp_path: Path) -> None:
    buf = SqliteBuffer(str(tmp_path / "outbox.sqlite"))
    point = _queued_point("reservation-failure")
    assert buf.enqueue(point["message_id"], point, point["ts"])
    transport = _StubTelegramTransport(_delivery_result(delivered=True))

    with pytest.raises(RuntimeError, match="reservation failed"):
        agent_main._send_telegram_buffered_point(
            buf=buf,
            transport=transport,
            device_id="device-1",
            point=point,
            max_wire_bytes=100_000,
            on_reserve=lambda _points, _wire_bytes: (_ for _ in ()).throw(RuntimeError("reservation failed")),
        )

    assert transport.calls == []
    assert [message.payload for message in buf.dequeue_batch(limit=5)] == [point]


def test_targeted_delivery_retains_row_when_durable_completion_fails(tmp_path: Path) -> None:
    buf = SqliteBuffer(str(tmp_path / "outbox.sqlite"))
    point = _queued_point("completion-failure")
    assert buf.enqueue(point["message_id"], point, point["ts"])
    transport = _StubTelegramTransport(_delivery_result(delivered=True))

    with pytest.raises(RuntimeError, match="completion state failed"):
        agent_main._send_telegram_buffered_point(
            buf=buf,
            transport=transport,
            device_id="device-1",
            point=point,
            max_wire_bytes=100_000,
            on_delivery=lambda _points, _result: (_ for _ in ()).throw(
                RuntimeError("completion state failed")
            ),
        )

    assert transport.calls == [("device-1", point)]
    assert [message.payload for message in buf.dequeue_batch(limit=5)] == [point]


class _LoopComplete(Exception):
    pass


def _run_one_telegram_iteration(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    transport: _StubTelegramTransport,
    forbid_api_paths: bool,
    on_buffer_ready: Callable[[SqliteBuffer], None] | None = None,
    initial_state: Any | None = None,
    sensor_metrics: dict[str, Any] | None = None,
    iterations: int = 1,
    local_request: tuple[str, str] | None = None,
    local_requests: tuple[tuple[str, str], ...] = (),
) -> SqliteBuffer:
    buffer = SqliteBuffer(str(tmp_path / "runtime-outbox.sqlite"))
    if on_buffer_ready is not None:
        on_buffer_ready(buffer)

    class NoNetworkSession:
        def post(self, *_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("unexpected direct HTTP request from agent main loop")

    monkeypatch.setattr(agent_main, "load_dotenv", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agent_main, "build_buffer_from_env", lambda _path: buffer)
    monkeypatch.setattr(agent_main, "TelegramTransport", lambda *_args, **_kwargs: transport)
    monkeypatch.setattr(agent_main.requests, "Session", NoNetworkSession)
    if initial_state is not None:
        monkeypatch.setattr(agent_main, "AgentState", lambda: initial_state)
    if sensor_metrics is not None:
        monkeypatch.setattr(
            agent_main,
            "build_sensor_backend",
            lambda **_kwargs: SimpleNamespace(read_metrics=lambda: dict(sensor_metrics)),
        )
    completed_iterations = 0

    def stop_after_requested_iterations(_seconds: float) -> None:
        nonlocal completed_iterations
        completed_iterations += 1
        if completed_iterations >= iterations:
            raise _LoopComplete()

    monkeypatch.setattr(agent_main, "_sleep", stop_after_requested_iterations)

    monkeypatch.setenv("EDGEWATCH_TELEMETRY_TRANSPORT", "telegram")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100123")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("EDGEWATCH_DEVICE_ID", "telegram-device")
    monkeypatch.setenv("EDGEWATCH_API_URL", "https://edgewatch.invalid")
    monkeypatch.setenv("EDGEWATCH_DEVICE_TOKEN", "api-token-must-not-be-used")
    monkeypatch.setenv("BUFFER_DB_PATH", str(tmp_path / "runtime-outbox.sqlite"))
    monkeypatch.setenv("SENSOR_CONFIG_PATH", "")
    monkeypatch.setenv("SENSOR_BACKEND", "none")
    monkeypatch.setenv("CELLULAR_METRICS_ENABLED", "false")
    monkeypatch.setenv("MEDIA_ENABLED", "true")
    monkeypatch.setenv("POWER_MGMT_ENABLED", "false")
    monkeypatch.setenv("RUNTIME_POWER_MODE", "continuous")
    monkeypatch.setenv("OPERATION_MODE", "active")
    monkeypatch.setenv("EDGEWATCH_COST_CAP_STATE_PATH", str(tmp_path / "cost-caps.json"))
    monkeypatch.setenv("EDGEWATCH_POWER_STATE_PATH", str(tmp_path / "power.json"))
    monkeypatch.setenv("EDGEWATCH_COMMAND_STATE_PATH", str(tmp_path / "commands.json"))
    monkeypatch.setenv("EDGEWATCH_UPDATE_STATE_PATH", str(tmp_path / "updates.json"))
    monkeypatch.setenv("EDGEWATCH_PROCEDURE_STATE_PATH", str(tmp_path / "procedures.json"))
    monkeypatch.setenv("EDGEWATCH_LOW_POWER_STATE_PATH", str(tmp_path / "low-power.json"))
    monkeypatch.setenv(
        "EDGEWATCH_LOCAL_CONTROL_STATE_PATH",
        str(tmp_path / "local-control.json"),
    )

    requests = local_requests + ((local_request,) if local_request is not None else ())
    for command_id, request_type in requests:
        agent_main.LocalControlState.from_env("telegram-device").ensure_request(
            command_id,
            request_type,
        )

    if forbid_api_paths:

        def forbidden(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("EdgeWatch API path used in Telegram-exclusive mode")

        for name in (
            "load_cached_policy",
            "fetch_device_policy",
            "save_cached_policy",
            "_maybe_ack_pending_command",
            "_maybe_run_pending_procedure_invocation",
            "_maybe_apply_pending_update_command",
            "build_media_runtime_from_env",
            "post_points",
        ):
            monkeypatch.setattr(agent_main, name, forbidden)

    with pytest.raises(_LoopComplete):
        agent_main.main()

    return buffer


def test_telegram_main_uses_no_edgewatch_api_path_for_one_iteration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    transport = _StubTelegramTransport(_delivery_result(delivered=True))

    _run_one_telegram_iteration(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        transport=transport,
        forbid_api_paths=True,
    )

    assert len(transport.calls) == 1


def test_telegram_main_enqueues_current_point_before_transport_send(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed_queue_depths: list[int] = []
    buffer_holder: dict[str, SqliteBuffer] = {}

    def observe_send(_device_id: str, _point: dict[str, Any]) -> None:
        observed_queue_depths.append(buffer_holder["buffer"].count())

    transport = _StubTelegramTransport(
        _delivery_result(delivered=True),
        on_send=observe_send,
    )
    _run_one_telegram_iteration(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        transport=transport,
        forbid_api_paths=False,
        on_buffer_ready=lambda buffer: buffer_holder.__setitem__("buffer", buffer),
    )

    assert observed_queue_depths == [1]


def test_telegram_main_reserves_once_before_successful_network_send(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed_reserved_bytes: list[int] = []

    def observe_send(_device_id: str, _point: dict[str, Any]) -> None:
        counters = json.loads((tmp_path / "cost-caps.json").read_text(encoding="utf-8"))
        observed_reserved_bytes.append(counters["bytes_sent_today"])

    transport = _StubTelegramTransport(
        _delivery_result(delivered=True),
        on_send=observe_send,
    )

    _run_one_telegram_iteration(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        transport=transport,
        forbid_api_paths=False,
    )

    sent_point = transport.calls[0][1]
    expected_reservation = agent_main._estimate_telegram_request_wire_bytes(
        transport,
        device_id="telegram-device",
        points=[sent_point],
        batch=False,
    )
    persisted = json.loads((tmp_path / "cost-caps.json").read_text(encoding="utf-8"))
    assert observed_reserved_bytes == [expected_reservation]
    assert persisted["bytes_sent_today"] == expected_reservation


def test_telegram_main_retains_current_point_after_delivery_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    transport = _StubTelegramTransport(_delivery_result(delivered=False))

    buffer = _run_one_telegram_iteration(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        transport=transport,
        forbid_api_paths=False,
    )

    queued = buffer.dequeue_batch(limit=1)
    assert len(queued) == 1
    assert queued[0].payload == transport.calls[0][1]
    cost_counters = json.loads((tmp_path / "cost-caps.json").read_text(encoding="utf-8"))
    assert cost_counters["bytes_sent_today"] >= agent_main._TELEGRAM_WIRE_FIXED_OVERHEAD_BYTES


def test_sync_retry_backoff_reuses_one_durable_telegram_point(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    command_id = "cmd-sync-retry"
    initial_state = agent_main.AgentState(
        last_state="OK",
        last_metrics_snapshot={"stable": True},
        last_heartbeat_at=agent_main.time.time(),
    )
    monkeypatch.setattr(agent_main, "_changed_keys", lambda **_kwargs: [])
    failing_transport = _StubTelegramTransport(_delivery_result(delivered=False))

    buffer = _run_one_telegram_iteration(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        transport=failing_transport,
        forbid_api_paths=False,
        initial_state=initial_state,
        iterations=3,
        local_request=(command_id, "sync_now"),
    )

    queued = buffer.dequeue_batch(limit=10)
    assert len(failing_transport.calls) == 1
    assert len(queued) == 1
    assert queued[0].message_id == agent_main._local_command_message_id(
        device_id="telegram-device",
        command_id=command_id,
    )
    pending = agent_main.LocalControlState.from_env("telegram-device").snapshot()["requests"][command_id]
    assert pending["status"] == "pending"
    assert pending["attempts"] == 3

    recovered_transport = _StubTelegramTransport(_delivery_result(delivered=True))
    recovered_state = type(initial_state)(
        last_state="OK",
        last_metrics_snapshot={"stable": True},
        last_heartbeat_at=agent_main.time.time(),
    )
    recovered_buffer = _run_one_telegram_iteration(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        transport=recovered_transport,
        forbid_api_paths=False,
        initial_state=recovered_state,
        local_request=(command_id, "sync_now"),
    )

    assert len(recovered_transport.calls) == 1
    assert recovered_transport.calls[0][1] == queued[0].payload
    assert recovered_buffer.count() == 0
    completed = agent_main.LocalControlState.from_env("telegram-device").snapshot()["requests"][command_id]
    assert completed["status"] == "completed"
    assert completed["result"] == {"network_synced": True}


def test_startup_collision_keeps_local_sync_point_distinct(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    transport = _StubTelegramTransport(_delivery_result(delivered=True))

    _run_one_telegram_iteration(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        transport=transport,
        forbid_api_paths=False,
        local_request=("cmd-sync-startup", "sync_now"),
    )

    request = agent_main.LocalControlState.from_env("telegram-device").snapshot()["requests"][
        "cmd-sync-startup"
    ]
    assert request["status"] == "completed"
    assert len(transport.calls) == 2
    assert transport.calls[0][1] == request["point"]
    assert transport.calls[1][1]["message_id"] != request["point"]["message_id"]


def test_heartbeat_collision_keeps_local_sample_point_distinct(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    transport = _StubTelegramTransport(_delivery_result(delivered=True))
    initial_state = agent_main.AgentState(
        last_state="OK",
        last_metrics_snapshot={"stable": True},
        last_heartbeat_at=0.0,
    )
    monkeypatch.setattr(agent_main, "_changed_keys", lambda **_kwargs: [])

    _run_one_telegram_iteration(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        transport=transport,
        forbid_api_paths=False,
        initial_state=initial_state,
        local_request=("cmd-sample-heartbeat", "sample_now"),
    )

    request = agent_main.LocalControlState.from_env("telegram-device").snapshot()["requests"][
        "cmd-sample-heartbeat"
    ]
    assert request["status"] == "completed"
    assert len(transport.calls) == 2
    call_ids = {call[1]["message_id"] for call in transport.calls}
    assert request["point"]["message_id"] in call_ids
    assert len(call_ids) == 2


def test_multiple_sync_requests_confirm_only_their_own_points(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    transport = _StubTelegramTransport(_delivery_result(delivered=True))
    initial_state = agent_main.AgentState(
        last_state="OK",
        last_metrics_snapshot={"stable": True},
        last_heartbeat_at=agent_main.time.time(),
    )
    monkeypatch.setattr(agent_main, "_changed_keys", lambda **_kwargs: [])

    _run_one_telegram_iteration(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        transport=transport,
        forbid_api_paths=False,
        initial_state=initial_state,
        local_requests=(("cmd-sync-a", "sync_now"), ("cmd-sync-b", "sync_now")),
    )

    requests = agent_main.LocalControlState.from_env("telegram-device").snapshot()["requests"]
    assert [call[1] for call in transport.calls] == [
        requests["cmd-sync-a"]["point"],
        requests["cmd-sync-b"]["point"],
    ]
    assert requests["cmd-sync-a"]["status"] == "completed"
    assert requests["cmd-sync-b"]["status"] == "completed"
    assert requests["cmd-sync-a"]["point"]["message_id"] != requests["cmd-sync-b"]["point"]["message_id"]


def test_each_successful_sync_resets_prior_backoff_before_the_next_sync(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class SequencedTransport(_StubTelegramTransport):
        def __init__(self) -> None:
            super().__init__(_delivery_result(delivered=True))
            self.results = iter(
                (
                    _delivery_result(delivered=True),
                    _delivery_result(delivered=False),
                )
            )

        def send(self, device_id: str, point: dict[str, Any]) -> TelegramDeliveryResult:
            self.calls.append((device_id, point))
            return next(self.results)

    transport = SequencedTransport()
    initial_state = agent_main.AgentState(
        last_state="OK",
        last_metrics_snapshot={"stable": True},
        last_heartbeat_at=agent_main.time.time(),
        consecutive_failures=3,
        next_network_attempt_at=agent_main.time.time() - 1.0,
    )
    monkeypatch.setattr(agent_main, "_changed_keys", lambda **_kwargs: [])

    _run_one_telegram_iteration(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        transport=transport,
        forbid_api_paths=False,
        initial_state=initial_state,
        local_requests=(("cmd-sync-a", "sync_now"), ("cmd-sync-b", "sync_now")),
    )

    requests = agent_main.LocalControlState.from_env("telegram-device").snapshot()["requests"]
    assert requests["cmd-sync-a"]["status"] == "completed"
    assert requests["cmd-sync-b"]["status"] == "pending"
    assert initial_state.consecutive_failures == 1
    assert initial_state.next_network_attempt_at > agent_main.time.time()


def test_mixed_sample_and_sync_requests_keep_independent_points(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    transport = _StubTelegramTransport(_delivery_result(delivered=False))
    initial_state = agent_main.AgentState(
        last_state="OK",
        last_metrics_snapshot={"stable": True},
        last_heartbeat_at=agent_main.time.time(),
    )
    monkeypatch.setattr(agent_main, "_changed_keys", lambda **_kwargs: [])

    buffer = _run_one_telegram_iteration(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        transport=transport,
        forbid_api_paths=False,
        initial_state=initial_state,
        local_requests=(("cmd-sample", "sample_now"), ("cmd-sync", "sync_now")),
    )

    requests = agent_main.LocalControlState.from_env("telegram-device").snapshot()["requests"]
    assert requests["cmd-sample"]["status"] == "completed"
    assert requests["cmd-sync"]["status"] == "pending"
    assert requests["cmd-sample"]["point"]["message_id"] != requests["cmd-sync"]["point"]["message_id"]
    assert {row.message_id for row in buffer.dequeue_batch(limit=10)} == {
        requests["cmd-sample"]["point"]["message_id"],
        requests["cmd-sync"]["point"]["message_id"],
    }


def test_local_sync_drains_unrelated_backlog_only_after_exact_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    routine = _queued_point("older-routine")
    transport = _StubTelegramTransport(_delivery_result(delivered=True))
    initial_state = agent_main.AgentState(
        last_state="OK",
        last_metrics_snapshot={"stable": True},
        last_heartbeat_at=agent_main.time.time(),
        consecutive_failures=3,
        next_network_attempt_at=agent_main.time.time() - 1.0,
    )
    monkeypatch.setattr(agent_main, "_changed_keys", lambda **_kwargs: [])

    def seed_backlog(outbox: SqliteBuffer) -> None:
        assert outbox.enqueue(routine["message_id"], routine, _fresh_created_at())

    buffer = _run_one_telegram_iteration(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        transport=transport,
        forbid_api_paths=False,
        initial_state=initial_state,
        local_request=("cmd-sync-budget", "sync_now"),
        on_buffer_ready=seed_backlog,
    )

    request = agent_main.LocalControlState.from_env("telegram-device").snapshot()["requests"][
        "cmd-sync-budget"
    ]
    assert [call[1]["message_id"] for call in transport.calls] == [
        request["point"]["message_id"],
        routine["message_id"],
    ]
    assert request["status"] == "completed"
    assert buffer.count() == 0
    assert initial_state.consecutive_failures == 0
    assert initial_state.next_network_attempt_at == 0.0


def test_sample_is_released_when_retention_evicts_its_exact_point(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BUFFER_MAX_POINTS", "0")
    monkeypatch.setattr(agent_main, "_changed_keys", lambda **_kwargs: [])
    initial_state = agent_main.AgentState(
        last_state="OK",
        last_metrics_snapshot={"stable": True},
        last_heartbeat_at=agent_main.time.time(),
    )
    transport = _StubTelegramTransport(_delivery_result(delivered=True))

    buffer = _run_one_telegram_iteration(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        transport=transport,
        forbid_api_paths=False,
        initial_state=initial_state,
        local_request=("cmd-sample-evicted", "sample_now"),
    )

    request = agent_main.LocalControlState.from_env("telegram-device").snapshot()["requests"][
        "cmd-sample-evicted"
    ]
    assert request["status"] == "pending"
    assert request["last_error"] == "sample point was evicted by outbox retention before completion"
    assert buffer.contains(request["point"]["message_id"]) is False
    assert transport.calls == []


def test_new_sync_during_existing_backoff_gets_its_own_durable_point(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = agent_main.AgentState(
        last_state="OK",
        last_metrics_snapshot={"stable": True},
        last_heartbeat_at=agent_main.time.time(),
    )
    monkeypatch.setattr(agent_main, "_changed_keys", lambda **_kwargs: [])

    _run_one_telegram_iteration(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        transport=_StubTelegramTransport(_delivery_result(delivered=False)),
        forbid_api_paths=False,
        initial_state=state,
        local_request=("cmd-sync-first", "sync_now"),
    )
    assert state.next_network_attempt_at > agent_main.time.time()

    no_send_transport = _StubTelegramTransport(_delivery_result(delivered=True))
    buffer = _run_one_telegram_iteration(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        transport=no_send_transport,
        forbid_api_paths=False,
        initial_state=state,
        local_request=("cmd-sync-second", "sync_now"),
    )

    requests = agent_main.LocalControlState.from_env("telegram-device").snapshot()["requests"]
    first = requests["cmd-sync-first"]["point"]
    second = requests["cmd-sync-second"]["point"]
    assert no_send_transport.calls == []
    assert first["message_id"] != second["message_id"]
    assert {row.message_id for row in buffer.dequeue_batch(limit=10)} == {
        first["message_id"],
        second["message_id"],
    }


def test_telegram_main_sends_alert_from_reserve_without_draining_capped_backlog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    routine_cap = 10_000
    cost_state_path = tmp_path / "cost-caps.json"
    cost_state_path.write_text(
        json.dumps(
            {
                "utc_day": datetime.now(timezone.utc).date().isoformat(),
                "bytes_sent_today": routine_cap,
                "snapshots_today": 0,
                "media_uploads_today": 0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MAX_BYTES_PER_DAY", str(routine_cap))
    monkeypatch.setenv("EDGEWATCH_COST_CAP_URGENT_RESERVE_BYTES", "65536")
    routine = _queued_point("routine-backlog")
    initial_state = agent_main.AgentState(
        last_state="OK",
        last_alerts=set(),
        last_metrics_snapshot={"battery_v": 12.5},
        last_heartbeat_at=agent_main.time.time(),
    )
    transport = _StubTelegramTransport(_delivery_result(delivered=True))

    def seed_routine_backlog(outbox: SqliteBuffer) -> None:
        assert outbox.enqueue(
            routine["message_id"],
            routine,
            _fresh_created_at(),
        )

    buffer = _run_one_telegram_iteration(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        transport=transport,
        forbid_api_paths=False,
        on_buffer_ready=seed_routine_backlog,
        initial_state=initial_state,
        sensor_metrics={"battery_v": 10.0},
    )

    assert len(transport.calls) == 1
    sent = transport.calls[0][1]
    assert sent["metrics"]["device_state"] == "WARN"
    assert sent["metrics"]["battery_v"] == 10.0
    assert sent["message_id"] != routine["message_id"]
    assert [message.payload for message in buffer.dequeue_batch(limit=5)] == [routine]


def test_post_points_preserves_api_ingest_contract() -> None:
    class RecordingSession:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def post(self, url: str, **kwargs: Any) -> SimpleNamespace:
            self.calls.append((url, kwargs))
            return SimpleNamespace(status_code=202)

    session = RecordingSession()
    points = [_queued_point()]

    response = agent_main.post_points(
        session,
        "https://edgewatch.example/",
        "device-token",
        points,
        timeout_s=7.5,
    )

    assert response.status_code == 202
    assert session.calls == [
        (
            "https://edgewatch.example/api/v1/ingest",
            {
                "headers": {"Authorization": "Bearer device-token"},
                "json": {"points": points},
                "timeout": 7.5,
            },
        )
    ]


def test_api_backlog_flush_stops_at_payload_budget(tmp_path: Path) -> None:
    class RecordingSession:
        def __init__(self) -> None:
            self.points: list[list[dict[str, Any]]] = []

        def post(self, _url: str, **kwargs: Any) -> SimpleNamespace:
            self.points.append(kwargs["json"]["points"])
            return SimpleNamespace(status_code=202, headers={}, text="")

    first = _queued_point("api-first")
    second = _queued_point("api-second")
    buffer = SqliteBuffer(str(tmp_path / "api-outbox.sqlite"))
    assert buffer.enqueue(first["message_id"], first, first["ts"])
    assert buffer.enqueue(second["message_id"], second, "2026-08-09T12:00:01+00:00")
    session = RecordingSession()

    assert agent_main._flush_buffer(
        session=session,
        buf=buffer,
        api_url="https://edgewatch.example",
        token="token",
        max_points_per_batch=50,
        max_payload_bytes=agent_main._estimate_ingest_payload_bytes([first]),
    )

    assert session.points == [[first]]
    assert [row.payload for row in buffer.dequeue_batch(limit=10)] == [second]
