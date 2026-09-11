"""Auth endpoints — register, login, refresh, me (DB-backed, JWT)."""
from __future__ import annotations

import uuid
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.models.user import User
from app.schemas.auth import (
    RefreshRequest,
    TokenPair,
    UserOut,
    UserRegister,
)

router = APIRouter()


def _tokens_for(user: User) -> TokenPair:
    subject = str(user.id)
    return TokenPair(
        access_token=create_access_token(subject),
        refresh_token=create_refresh_token(subject),
    )


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegister, db: DbSession) -> TokenPair:
    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _tokens_for(user)


@router.post("/login", response_model=TokenPair)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
) -> TokenPair:
    """OAuth2 password flow. `username` is the user's email."""
    user = await db.scalar(select(User).where(User.email == form_data.username))
    if user is None or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _tokens_for(user)


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, db: DbSession) -> TokenPair:
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token.",
    )
    try:
        claims = decode_token(payload.refresh_token)
    except jwt.PyJWTError as exc:
        raise invalid from exc
    if claims.get("type") != "refresh":
        raise invalid

    try:
        user_id = uuid.UUID(str(claims.get("sub")))
    except ValueError as exc:
        raise invalid from exc

    user = await db.get(User, user_id)
    if user is None:
        raise invalid
    return _tokens_for(user)


@router.get("/me", response_model=UserOut)
async def me(current_user: CurrentUser) -> UserOut:
    return current_user
