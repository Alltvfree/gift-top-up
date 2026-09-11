"""Verify Supabase Auth access tokens (for the deployed broker API).

The web app (Cloudflare Pages) sends its Supabase access token as a bearer
token. Supabase signs these JWTs (HS256) with the project's JWT secret
(Project Settings → API → JWT Secret). We verify that signature and return the
user id (the `sub` claim) — no separate login system needed.
"""
from __future__ import annotations

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

bearer_scheme = HTTPBearer(auto_error=True)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_supabase_user_id(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> uuid.UUID:
    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SUPABASE_JWT_SECRET is not configured on the server.",
        )
    try:
        payload = jwt.decode(
            creds.credentials,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as exc:
        raise _unauthorized("Invalid or expired token.") from exc

    sub = payload.get("sub")
    if not sub:
        raise _unauthorized("Token missing subject.")
    try:
        return uuid.UUID(str(sub))
    except ValueError as exc:
        raise _unauthorized("Invalid subject.") from exc


SupabaseUserId = Annotated[uuid.UUID, Depends(get_supabase_user_id)]
