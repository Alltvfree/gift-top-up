"""Verify Supabase Auth access tokens (for the deployed broker API).

Supabase projects now sign access tokens with **asymmetric JWT signing keys**
(ES256/RS256). We verify them against the project's public JWKS endpoint
(`/auth/v1/.well-known/jwks.json`). Older projects still on the symmetric
**Legacy JWT Secret** (HS256) are supported as a fallback when
SUPABASE_JWT_SECRET is set.

Either way we return the user id (the `sub` claim).
"""
from __future__ import annotations

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.core.config import settings

bearer_scheme = HTTPBearer(auto_error=True)

_jwks_client: PyJWKClient | None = None


def _jwks() -> PyJWKClient | None:
    global _jwks_client
    if _jwks_client is None and settings.supabase_url:
        url = settings.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
        _jwks_client = PyJWKClient(url)
    return _jwks_client


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _decode(token: str) -> dict:
    try:
        alg = jwt.get_unverified_header(token).get("alg")
    except jwt.PyJWTError as exc:
        raise _unauthorized("Malformed token.") from exc

    opts = {"audience": "authenticated"}

    if alg in ("ES256", "RS256", "EdDSA"):
        client = _jwks()
        if client is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SUPABASE_URL is not configured (needed to fetch JWKS).",
            )
        try:
            key = client.get_signing_key_from_jwt(token).key
            return jwt.decode(token, key, algorithms=["ES256", "RS256", "EdDSA"], **opts)
        except jwt.PyJWTError as exc:
            raise _unauthorized("Invalid or expired token.") from exc

    if alg == "HS256":
        if not settings.supabase_jwt_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SUPABASE_JWT_SECRET is not configured for HS256 tokens.",
            )
        try:
            return jwt.decode(
                token, settings.supabase_jwt_secret, algorithms=["HS256"], **opts
            )
        except jwt.PyJWTError as exc:
            raise _unauthorized("Invalid or expired token.") from exc

    raise _unauthorized(f"Unsupported token algorithm: {alg}")


async def get_supabase_user_id(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> uuid.UUID:
    payload = _decode(creds.credentials)
    sub = payload.get("sub")
    if not sub:
        raise _unauthorized("Token missing subject.")
    try:
        return uuid.UUID(str(sub))
    except ValueError as exc:
        raise _unauthorized("Invalid subject.") from exc


SupabaseUserId = Annotated[uuid.UUID, Depends(get_supabase_user_id)]
