"""Password hashing and JWT helpers.

Full auth wiring (register/login/refresh) lands in Task 2 — this module
provides the primitives those endpoints will use.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings


def _encode(password: str) -> bytes:
    # bcrypt only uses the first 72 bytes; truncate to stay within that limit.
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(_encode(plain_password), hashed_password.encode("utf-8"))
    except ValueError:
        return False


def _create_token(subject: str, expires_delta: timedelta, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str) -> str:
    return _create_token(
        subject,
        timedelta(minutes=settings.access_token_expire_minutes),
        "access",
    )


def create_refresh_token(subject: str) -> str:
    return _create_token(
        subject,
        timedelta(days=settings.refresh_token_expire_days),
        "refresh",
    )


def decode_token(token: str) -> dict[str, Any]:
    """Decode & validate a JWT, raising jwt exceptions on failure."""
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
