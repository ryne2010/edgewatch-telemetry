from __future__ import annotations

import json
import gzip
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import requests

import agent.telegram_transport as telegram_transport_module
from agent.telegram_transport import (
    TelegramTransport,
    TelegramTransportConfig,
    TelegramTransportConfigError,
    load_telegram_transport_config,
)


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = {"ok": True} if payload is None else payload
        self.headers = headers or {}

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse | Exception | None = None) -> None:
        self.response = response or FakeResponse()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _telegram_config(**changes: Any) -> TelegramTransportConfig:
    base = TelegramTransportConfig(
        transport="telegram",
        chat_id="-100123",
        bot_token="123456:super-secret-token",
    )
    return replace(base, **changes)


def _sent_document(session: FakeSession) -> bytes:
    _, kwargs = session.calls[0]
    return kwargs["files"]["document"][1]


def test_config_defaults_to_api_without_telegram_credentials() -> None:
    config = load_telegram_transport_config({})

    assert config == TelegramTransportConfig()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("EDGEWATCH_TELEMETRY_TRANSPORT", "email"),
    ],
)
def test_config_rejects_invalid_strict_values(name: str, value: str) -> None:
    env = {name: value}

    with pytest.raises(TelegramTransportConfigError) as exc_info:
        load_telegram_transport_config(env)

    assert name in str(exc_info.value)


def test_api_mode_ignores_irrelevant_telegram_settings() -> None:
    config = load_telegram_transport_config(
        {
            "EDGEWATCH_TELEMETRY_TRANSPORT": "api",
            "TELEGRAM_TIMEOUT_S": "not-a-number",
            "TELEGRAM_DISABLE_NOTIFICATION": "sometimes",
            "TELEGRAM_PROTECT_CONTENT": "2",
        }
    )

    assert config == TelegramTransportConfig()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TELEGRAM_TIMEOUT_S", "0"),
        ("TELEGRAM_TIMEOUT_S", "nan"),
        ("TELEGRAM_DISABLE_NOTIFICATION", "sometimes"),
        ("TELEGRAM_PROTECT_CONTENT", "2"),
    ],
)
def test_telegram_mode_rejects_invalid_strict_values(name: str, value: str) -> None:
    env = {
        "EDGEWATCH_TELEMETRY_TRANSPORT": "telegram",
        "TELEGRAM_CHAT_ID": "42",
        "TELEGRAM_BOT_TOKEN": "123:secret",
        name: value,
    }

    with pytest.raises(TelegramTransportConfigError) as exc_info:
        load_telegram_transport_config(env)

    assert name in str(exc_info.value)


def test_telegram_config_requires_chat_and_token_without_exposing_secrets() -> None:
    with pytest.raises(TelegramTransportConfigError, match="TELEGRAM_CHAT_ID"):
        load_telegram_transport_config({"EDGEWATCH_TELEMETRY_TRANSPORT": "telegram"})

    with pytest.raises(TelegramTransportConfigError) as exc_info:
        load_telegram_transport_config(
            {
                "EDGEWATCH_TELEMETRY_TRANSPORT": "telegram",
                "TELEGRAM_CHAT_ID": "chat-secret-value",
            }
        )

    assert "chat-secret-value" not in str(exc_info.value)


def test_config_reads_token_file_and_parses_options(tmp_path: Path) -> None:
    token_path = tmp_path / "telegram-token"
    token_path.write_text("file-secret-token\n", encoding="utf-8")
    token_path.chmod(0o600)

    config = load_telegram_transport_config(
        {
            "EDGEWATCH_TELEMETRY_TRANSPORT": " TELEGRAM ",
            "TELEGRAM_CHAT_ID": " 42 ",
            "TELEGRAM_BOT_TOKEN_FILE": str(token_path),
            "TELEGRAM_TIMEOUT_S": "2.5",
            "TELEGRAM_DISABLE_NOTIFICATION": "YES",
            "TELEGRAM_PROTECT_CONTENT": "0",
        }
    )

    assert config == TelegramTransportConfig(
        transport="telegram",
        chat_id="42",
        bot_token="file-secret-token",
        timeout_s=2.5,
        disable_notification=True,
        protect_content=False,
    )


def test_config_enables_fleet_batch_profile_explicitly() -> None:
    config = load_telegram_transport_config(
        {
            "EDGEWATCH_TELEMETRY_TRANSPORT": "telegram",
            "TELEGRAM_CHAT_ID": "42",
            "TELEGRAM_BOT_TOKEN": "123:secret",
            "TELEGRAM_BATCH_ENABLED": "true",
            "TELEGRAM_BATCH_MAX_POINTS": "25",
            "TELEGRAM_BATCH_MAX_BYTES": "65536",
            "TELEGRAM_BATCH_MAX_AGE_S": "900",
        }
    )

    assert config.batch_enabled is True
    assert config.batch_max_points == 25
    assert config.batch_max_bytes == 65536
    assert config.batch_max_age_s == 900


def test_config_rejects_group_or_world_accessible_token_file(tmp_path: Path) -> None:
    token_path = tmp_path / "telegram-token"
    token_path.write_text("file-secret-token\n", encoding="utf-8")
    token_path.chmod(0o644)

    with pytest.raises(TelegramTransportConfigError, match="0600 or stricter"):
        load_telegram_transport_config(
            {
                "EDGEWATCH_TELEMETRY_TRANSPORT": "telegram",
                "TELEGRAM_CHAT_ID": "42",
                "TELEGRAM_BOT_TOKEN_FILE": str(token_path),
            }
        )


def test_unreadable_token_file_error_is_secret_safe(tmp_path: Path) -> None:
    secret_path = tmp_path / "secret-token-do-not-print"

    with pytest.raises(TelegramTransportConfigError) as exc_info:
        load_telegram_transport_config(
            {
                "EDGEWATCH_TELEMETRY_TRANSPORT": "telegram",
                "TELEGRAM_CHAT_ID": "42",
                "TELEGRAM_BOT_TOKEN_FILE": str(secret_path),
            }
        )

    assert str(secret_path) not in str(exc_info.value)


def test_sends_one_full_fidelity_unicode_document_with_operational_caption() -> None:
    session = FakeSession()
    point = {
        "message_id": "msg/日本語 1",
        "ts": "2026-08-09T12:34:56Z",
        "metrics": {
            "label": "café 🚀",
            "device_state": "active",
            "buffer_queue_depth": 7,
            "cellular_registration_state": "registered_roaming",
            "nested": {"samples": [1, 2.5, True, None]},
        },
    }
    transport = TelegramTransport(_telegram_config(), session=session, base_url="https://test.invalid")

    result = transport.send("edge-ñ", point)

    assert result.delivered is True
    assert result.bytes_sent == len(_sent_document(session))
    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url == "https://test.invalid/bot123456:super-secret-token/sendDocument"
    filename, document, content_type = kwargs["files"]["document"]
    assert filename == "edgewatch-msg_1.json"
    assert content_type == "application/json; charset=utf-8"
    assert json.loads(document) == {"device_id": "edge-ñ", "point": point}
    assert b"caf\xc3\xa9" in document
    assert kwargs["data"]["disable_notification"] == "false"
    assert kwargs["data"]["protect_content"] == "true"
    assert "buffer_queue_depth: 7" in kwargs["data"]["caption"]
    assert "cellular_registration: registered_roaming" in kwargs["data"]["caption"]
    assert kwargs["timeout"] == 10.0


def test_alert_caption_uses_restrained_severity_and_power_icons_without_changing_json() -> None:
    session = FakeSession()
    point = {
        "message_id": "power-alert-1",
        "ts": "2026-08-09T12:34:56Z",
        "metrics": {
            "device_state": "WARN",
            "battery_v": 10.1,
            "power_unsustainable": True,
        },
    }

    result = TelegramTransport(_telegram_config(), session=session).send("gateway-001", point)

    assert result.delivered is True
    _, kwargs = session.calls[0]
    assert kwargs["data"]["caption"].startswith("⚠️ 🔋 EdgeWatch telemetry\n")
    assert json.loads(_sent_document(session)) == {"device_id": "gateway-001", "point": point}


def test_recovery_and_camera_alert_captions_never_add_more_than_two_icons() -> None:
    recovery_session = FakeSession()
    fault_session = FakeSession()
    recovery = {
        "message_id": "recovered",
        "alert_state": "resolved",
        "alert_type": "SIGNAL_LOW",
        "metrics": {"device_state": "OK"},
    }
    fault = {
        "message_id": "fault",
        "severity": "critical",
        "alert_type": "EQUIPMENT_FAULT",
        "metrics": {"equipment_state": "fault", "visual_confidence": 0.97},
    }

    TelegramTransport(_telegram_config(), session=recovery_session).send("sat-1", recovery)
    TelegramTransport(_telegram_config(), session=fault_session).send("sat-1", fault)

    recovery_caption = recovery_session.calls[0][1]["data"]["caption"]
    fault_caption = fault_session.calls[0][1]["data"]["caption"]
    assert recovery_caption.startswith("✅ 📶 EdgeWatch telemetry")
    assert fault_caption.startswith("🚨 🎥 EdgeWatch telemetry")
    known_icons = ("🚨", "⚠️", "ℹ️", "✅", "🔋", "📶", "🎥", "🎙️", "🛰️", "🔄", "💤")
    assert sum(fault_caption.count(icon) for icon in known_icons) == 2


def test_shadow_inference_state_does_not_create_an_alert_caption() -> None:
    session = FakeSession()
    point = {
        "message_id": "shadow-stopped",
        "metrics": {"equipment_state": "stopped", "visual_confidence": 0.99},
    }

    TelegramTransport(_telegram_config(), session=session).send("sat-1", point)

    caption = session.calls[0][1]["data"]["caption"]
    assert caption.startswith("EdgeWatch telemetry\n")


def test_oversized_point_still_uses_exactly_one_complete_document() -> None:
    session = FakeSession()
    point = {"message_id": "large-1", "ts": "2026-08-09T00:00:00Z", "metrics": {"blob": "界" * 5000}}

    result = TelegramTransport(_telegram_config(), session=session).send("device-1", point)

    assert result.delivered is True
    assert len(session.calls) == 1
    document = _sent_document(session)
    assert len(document) > 4096
    assert json.loads(document) == {"device_id": "device-1", "point": point}


def test_batch_is_deterministic_canonical_gzip_jsonl_with_accounting() -> None:
    points = [
        {"message_id": "m1", "ts": "2026-08-09T00:00:00Z", "metrics": {"z": 1, "a": "é"}},
        {"message_id": "m2", "ts": "2026-08-09T00:01:00Z", "metrics": {"ok": True}},
    ]
    first_session = FakeSession()
    second_session = FakeSession()

    first = TelegramTransport(_telegram_config(), session=first_session).send_batch("device-1", points)
    second = TelegramTransport(_telegram_config(), session=second_session).send_batch("device-1", points)

    first_document = _sent_document(first_session)
    assert first.delivered is True
    assert first.document_bytes == len(first_document)
    assert first.estimated_wire_bytes > first.document_bytes
    assert first_document == _sent_document(second_session)
    assert first_document == gzip.compress(gzip.decompress(first_document), compresslevel=9, mtime=0)
    lines = gzip.decompress(first_document).decode("utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [
        {"device_id": "device-1", "point": points[0]},
        {"device_id": "device-1", "point": points[1]},
    ]
    _, kwargs = first_session.calls[0]
    assert kwargs["files"]["document"][0].endswith(".jsonl.gz")
    assert kwargs["files"]["document"][2] == "application/gzip"
    assert "points: 2" in kwargs["data"]["caption"]
    assert second.delivered is True


def test_document_over_telegram_limit_is_permanent_without_network_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    monkeypatch.setattr(telegram_transport_module, "_TELEGRAM_DOCUMENT_MAX_BYTES", 256)
    point = {"message_id": "too-large", "metrics": {"blob": "x" * 512}}

    result = TelegramTransport(_telegram_config(), session=session).send("device-1", point)

    assert result.delivered is False
    assert result.permanent is True
    assert result.reason == "telemetry document exceeds Telegram's 50 MB limit"
    assert result.bytes_sent == 0
    assert session.calls == []


def test_429_parses_bot_retry_after_before_header_and_retains_point() -> None:
    response = FakeResponse(
        429,
        {
            "ok": False,
            "error_code": 429,
            "description": "Too Many Requests",
            "parameters": {"retry_after": 17},
        },
        {"Retry-After": "99"},
    )
    session = FakeSession(response)

    result = TelegramTransport(_telegram_config(), session=session).send(
        "device-1", {"message_id": "m1", "metrics": {}}
    )

    assert result.delivered is False
    assert result.retry_after_s == 17.0
    assert result.status_code == 429
    assert result.reason == "telegram API rejected delivery (error_code=429)"
    assert result.bytes_sent > 0


def test_5xx_parses_retry_after_header_and_retains_point() -> None:
    session = FakeSession(FakeResponse(503, ValueError("not json"), {"Retry-After": "4.5"}))

    result = TelegramTransport(_telegram_config(), session=session).send(
        "device-1", {"message_id": "m1", "metrics": {}}
    )

    assert result.delivered is False
    assert result.retry_after_s == 4.5
    assert result.status_code == 503
    assert result.reason == "telegram HTTP failure (status=503)"


def test_network_exception_never_exposes_token_url_or_exception_body() -> None:
    token = "123456:never-leak-this-token"
    leaked_url = f"https://api.telegram.org/bot{token}/sendDocument"
    session = FakeSession(requests.ConnectionError(f"failed posting {leaked_url} body={token}"))
    transport = TelegramTransport(_telegram_config(bot_token=token), session=session)

    result = transport.send("device-1", {"message_id": "m1", "metrics": {}})

    rendered = repr(result)
    assert result.delivered is False
    assert result.reason == "telegram network request failed"
    assert result.status_code is None
    assert result.bytes_sent > 0
    assert token not in rendered
    assert leaked_url not in rendered
