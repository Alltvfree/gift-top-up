"""Telegram Bot API client (https://core.telegram.org/bots/api), the few methods the bot needs.

The bot token is part of every request URL, so it is kept out of logs and error messages.
"""
import json

import httpx

API = "https://api.telegram.org"


class TelegramError(Exception):
    def __init__(self, message, code=None, retry_after=None):
        super().__init__(message)
        self.code, self.retry_after = code, retry_after


class Telegram:
    def __init__(self, token: str, timeout: float = 40.0, transport=None):
        self._token = token
        self.client = httpx.Client(base_url=f"{API}/bot{token}/", timeout=timeout, transport=transport)

    def close(self):
        self.client.close()

    def call(self, method: str, **params):
        try:
            r = self.client.post(method, json={k: v for k, v in params.items() if v is not None})
        except httpx.HTTPError as exc:
            raise TelegramError(f"{type(exc).__name__}: {str(exc).replace(self._token, '***')}") from None
        try:
            data = r.json()
        except ValueError:
            raise TelegramError(f"HTTP {r.status_code}", r.status_code) from None
        if not data.get("ok"):
            raise TelegramError(data.get("description") or f"HTTP {r.status_code}", data.get("error_code"),
                                (data.get("parameters") or {}).get("retry_after"))
        return data["result"]

    def get_me(self) -> dict:
        return self.call("getMe")

    def delete_webhook(self):
        return self.call("deleteWebhook")

    def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict]:
        return self.call("getUpdates", offset=offset, timeout=timeout,
                         allowed_updates=["message", "callback_query"])

    def send_message(self, chat_id: int, text: str, keyboard: list | None = None, force_reply: bool = False) -> dict:
        markup = {"inline_keyboard": keyboard} if keyboard else ({"force_reply": True} if force_reply else None)
        return self.call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
                         disable_web_page_preview=True, reply_markup=json.dumps(markup) if markup else None)

    def edit_message(self, chat_id: int, message_id: int, text: str, keyboard: list | None = None) -> dict:
        return self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML",
                         disable_web_page_preview=True, reply_markup=json.dumps({"inline_keyboard": keyboard or []}))

    def answer_callback(self, callback_id: str, text: str = "") -> dict:
        return self.call("answerCallbackQuery", callback_query_id=callback_id, text=text[:200])

    def delete_message(self, chat_id: int, message_id: int):
        return self.call("deleteMessage", chat_id=chat_id, message_id=message_id)
