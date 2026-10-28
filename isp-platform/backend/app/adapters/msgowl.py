"""MessageOwl (msgowl) SMS gateway, Maldives.

Matches the official SDK (github.com/messageowl/msgowl-php): POST https://rest.msgowl.com/messages
with `Authorization: AccessKey <key>` and JSON {recipients, sender_id, body}; reply {id, message}.
Errors: 401 bad key, 422 validation (may carry bulk_limit), 429 rate limit (50 POST/min, retry_after).
"""
import re

import httpx

BASE_URL = "https://rest.msgowl.com"


class SmsError(Exception):
    def __init__(self, message, status=None, retry_after=None, bulk_limit=None):
        super().__init__(message)
        self.status, self.retry_after, self.bulk_limit = status, retry_after, bulk_limit


def normalize_phone(raw: str | None) -> str | None:
    """Maldives numbers as MessageOwl expects them: 960 + 7 digits, no '+'."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 7:
        digits = "960" + digits
    if len(digits) == 10 and digits.startswith("960"):
        return digits
    if 8 <= len(digits) <= 15 and not digits.startswith("960"):
        return digits  # foreign number in international form
    return None


class MessageOwl:
    def __init__(self, access_key: str, sender_id: str, timeout: float = 15.0, transport=None):
        self.sender_id = sender_id
        self.client = httpx.Client(base_url=BASE_URL, timeout=timeout, transport=transport,
                                   headers={"Authorization": f"AccessKey {access_key}", "Accept": "application/json"})

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _call(self, method, path, body=None) -> dict:
        try:
            r = self.client.request(method, path, json=body)
        except httpx.HTTPError as exc:
            raise SmsError(f"{type(exc).__name__}: {exc}") from exc
        try:
            data = r.json() if r.content else {}
        except ValueError:
            data = {"message": r.text[:200]}
        if r.status_code >= 400:
            raise SmsError(data.get("message") or f"HTTP {r.status_code}", r.status_code,
                           retry_after=data.get("retry_after") or r.headers.get("Retry-After"),
                           bulk_limit=data.get("bulk_limit"))
        return data

    def send(self, recipients: list[str], body: str) -> str:
        """One message to one or many recipients (same text). Returns MessageOwl's message id."""
        # As in the SDK README: a plain string for one number, a list for several.
        to = recipients[0] if len(recipients) == 1 else list(recipients)
        data = self._call("POST", "/messages", {"recipients": to, "sender_id": self.sender_id, "body": body})
        return str(data.get("id", ""))

    def balance(self) -> dict:
        return self._call("GET", "/balance")
