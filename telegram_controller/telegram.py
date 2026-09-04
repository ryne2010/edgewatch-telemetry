from __future__ import annotations

from typing import Any

import requests


class TelegramError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, token: str, *, timeout_s: int = 40, session: requests.Session | None = None):
        if not token:
            raise ValueError("control bot token is required")
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._timeout_s = timeout_s
        self._session = session or requests.Session()

    def get_me(self) -> dict[str, Any]:
        result = self._request("getMe", {}, timeout=self._timeout_s)
        if not isinstance(result, dict):
            raise TelegramError("Telegram returned an invalid bot identity response")
        return result

    def get_updates(self, *, offset: int | None, poll_timeout_s: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": poll_timeout_s, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        result = self._request("getUpdates", payload, timeout=max(self._timeout_s, poll_timeout_s + 5))
        if not isinstance(result, list):
            raise TelegramError("Telegram returned an invalid update response")
        return [item for item in result if isinstance(item, dict)]

    def send_message(self, chat_id: str, text: str, topic_id: str | None = None) -> str:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if topic_id is not None:
            payload["message_thread_id"] = topic_id
        result = self._request("sendMessage", payload, timeout=self._timeout_s)
        if not isinstance(result, dict) or "message_id" not in result:
            raise TelegramError("Telegram returned an invalid send response")
        return str(result["message_id"])

    def _request(self, method: str, payload: dict[str, Any], *, timeout: int) -> Any:
        try:
            response = self._session.post(f"{self._base_url}/{method}", json=payload, timeout=timeout)
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TelegramError(f"Telegram {method} request failed") from exc
        if not isinstance(body, dict) or body.get("ok") is not True:
            raise TelegramError(f"Telegram {method} request was rejected")
        return body.get("result")
