"""Shared FastAPI dependencies (DB session, current user)."""
from __future__ import annotations

import uuid
from typing import Annotated, AsyncGenerator

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_token
from app.db.models.user import User
from app.db.session import async_session_factory

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_v1_prefix}/auth/login")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DbSession,
) -> User:
    """Validate the bearer token and return the authenticated user."""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
    except jwt.PyJWTError as exc:
        raise credentials_exc from exc

    user_id = payload.get("sub")
    if user_id is None or payload.get("type") != "access":
        raise credentials_exc

    try:
        user_uuid = uuid.UUID(str(user_id))
    except ValueError as exc:
        raise credentials_exc from exc

    user = await db.get(User, user_uuid)
    if user is None:
        raise credentials_exc
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
