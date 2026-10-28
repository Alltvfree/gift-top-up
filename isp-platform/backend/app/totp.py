"""TOTP (RFC 6238: HMAC-SHA1, 30 s, 6 digits) and recovery codes. Works with any authenticator app."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30
DIGITS = 6
WINDOW = 1  # accept the previous/next step too (phone clock drift)


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode()


def code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def verify(secret: str, code: str, last_step: int = 0, now: float | None = None) -> int | None:
    """Return the matched time step (store it as last_step), or None. Steps <= last_step are replays."""
    code = (code or "").strip().replace(" ", "")
    if not (code.isdigit() and len(code) == DIGITS):
        return None
    current = int((now if now is not None else time.time()) // STEP)
    for step in range(current - WINDOW, current + WINDOW + 1):
        if step > last_step and hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, username: str, issuer: str) -> str:
    label = quote(f"{issuer}:{username}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"


# Recovery codes: 16 chars from a 31-symbol alphabet (~79 bits), so a fast hash is safe.
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def new_recovery_codes(n: int = 10) -> list[str]:
    codes = []
    for _ in range(n):
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(16))
        codes.append("-".join(raw[i:i + 4] for i in range(0, 16, 4)))
    return codes


def normalize_recovery(code: str) -> str:
    return "".join(c for c in (code or "").lower() if c.isalnum())


def hash_recovery(code: str) -> str:
    return hashlib.sha256(normalize_recovery(code).encode()).hexdigest()
