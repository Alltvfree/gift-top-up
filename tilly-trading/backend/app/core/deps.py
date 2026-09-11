"""Shared FastAPI dependencies (DB session, current user).

The `get_current_user` dependency is a placeholder that decodes the JWT;
it is fleshed out into a real DB lookup in Task 2 (Database & Auth).
"""
from __future__ import annotations

from typing import Annotated, AsyncGenerator

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_token
from app.db.session import async_session_factory

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_v1_prefix}/auth/login")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


async def get_current_user_id(
    token: Annotated[str, Depends(oauth2_scheme)],
) -> str:
    """Validate the bearer token and return the user id (the `sub` claim)."""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
    except jwt.PyJWTError as exc:  # noqa: PERF203
        raise credentials_exc from exc

    user_id = payload.get("sub")
    if user_id is None or payload.get("type") != "access":
        raise credentials_exc
    return user_id


DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUserId = Annotated[str, Depends(get_current_user_id)]
