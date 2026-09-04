from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
import requests

from telegram_controller.heartbeat import (
    DeadManHeartbeat,
    HeartbeatConfig,
    HeartbeatConfigError,
    load_heartbeat_config,
)


class Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class Session:
    def __init__(self, responses: list[Response | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> Response:
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_optional_config_reads_only_strict_https_secret_file(tmp_path: Path) -> None:
    assert load_heartbeat_config({}) is None
    secret = tmp_path / "heartbeat-url"
    url = "https://hc-ping.com/secret-check-id"
    secret.write_text(f"{url}\n", encoding="utf-8")
    secret.chmod(0o600)

    config = load_heartbeat_config(
        {
            "EDGEWATCH_DEADMAN_HEARTBEAT_URL_FILE": str(secret),
            "EDGEWATCH_DEADMAN_INTERVAL_S": "3600",
            "EDGEWATCH_DEADMAN_REQUEST_TIMEOUT_S": "4",
            "EDGEWATCH_DEADMAN_MAX_ATTEMPTS": "3",
            "EDGEWATCH_DEADMAN_BACKOFF_BASE_S": "0.25",
        }
    )

    assert config is not None
    assert config.checkin_url == url
    assert config.interval_s == 3600
    assert config.request_timeout_s == 4
    assert config.max_attempts == 3
    assert config.backoff_base_s == 0.25
    assert url not in repr(config)


@pytest.mark.parametrize(
    "env",
    [
        {"EDGEWATCH_DEADMAN_HEARTBEAT_URL": "https://hc-ping.com/plaintext-secret"},
        {"EDGEWATCH_DEADMAN_INTERVAL_S": "3600"},
    ],
)
def test_partial_or_plaintext_configuration_fails_closed_without_disclosure(
    env: dict[str, str],
) -> None:
    with pytest.raises(HeartbeatConfigError) as caught:
        load_heartbeat_config(env)

    assert "plaintext-secret" not in str(caught.value)


@pytest.mark.parametrize(
    ("mode", "value"),
    [
        (0o644, "https://hc-ping.com/secret"),
        (0o600, "http://hc-ping.com/secret"),
        (0o600, "https://user:secret@hc-ping.com/check"),
    ],
)
def test_config_rejects_unsafe_secret_without_disclosure(tmp_path: Path, mode: int, value: str) -> None:
    secret = tmp_path / "do-not-print-secret-path"
    secret.write_text(value, encoding="utf-8")
    secret.chmod(mode)

    with pytest.raises(HeartbeatConfigError) as caught:
        load_heartbeat_config({"EDGEWATCH_DEADMAN_HEARTBEAT_URL_FILE": str(secret)})

    rendered = str(caught.value)
    assert value not in rendered
    assert str(secret) not in rendered


def test_config_rejects_symlink_to_mode_0600_secret(tmp_path: Path) -> None:
    target = tmp_path / "heartbeat-url-target"
    target.write_text("https://hc-ping.com/secret\n", encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "heartbeat-url-link"
    link.symlink_to(target)

    with pytest.raises(HeartbeatConfigError, match="regular file"):
        load_heartbeat_config({"EDGEWATCH_DEADMAN_HEARTBEAT_URL_FILE": str(link)})


def test_checkin_retries_with_backoff_and_never_exposes_url_in_result() -> None:
    url = "https://hc-ping.com/sensitive-check-id"
    session = Session(
        [
            requests.ConnectionError(f"failed to reach {url}"),
            Response(503),
            Response(200),
        ]
    )
    sleeps: list[float] = []
    heartbeat = DeadManHeartbeat(
        HeartbeatConfig(url, max_attempts=3, backoff_base_s=0.5),
        session=session,
        sleeper=sleeps.append,
    )

    result = heartbeat.check_in()

    assert result.success is True
    assert result.attempts == 3
    assert sleeps == [0.5, 1.0]
    assert url not in repr(result)
    assert all(call[1] == {"timeout": 10.0, "allow_redirects": False} for call in session.calls)


def test_poll_returns_immediately_and_coalesces_while_request_is_in_flight() -> None:
    started = threading.Event()
    release = threading.Event()

    class BlockingSession:
        def get(self, url: str, **kwargs: Any) -> Response:
            del url, kwargs
            started.set()
            assert release.wait(timeout=2)
            return Response(200)

    heartbeat = DeadManHeartbeat(
        HeartbeatConfig("https://hc-ping.com/sensitive", interval_s=3600),
        session=BlockingSession(),
    )

    assert heartbeat.poll(now=100) is True
    assert started.wait(timeout=1)
    assert heartbeat.in_flight is True
    assert heartbeat.poll(now=100) is False
    release.set()
    for _ in range(100):
        result = heartbeat.last_result
        if result is not None:
            break
        threading.Event().wait(0.005)
    assert result is not None and result.success is True
    assert heartbeat.in_flight is False
    assert heartbeat.poll(now=3699) is False
    assert heartbeat.poll(now=3700) is True
