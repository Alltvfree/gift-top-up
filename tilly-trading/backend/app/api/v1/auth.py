"""Auth endpoints.

Structure is in place; full persistence + credential verification is wired
in Task 2 (Database & Auth). The token-issuing primitives already live in
`app.core.security`.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.schemas.auth import (
    RefreshRequest,
    TokenPair,
    UserLogin,
    UserOut,
    UserRegister,
)

router = APIRouter()

_NOT_YET = HTTPException(
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    detail="Auth persistence is implemented in Task 2 (Database & Auth).",
)


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegister) -> TokenPair:
    raise _NOT_YET


@router.post("/login", response_model=TokenPair)
async def login(payload: UserLogin) -> TokenPair:
    raise _NOT_YET


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest) -> TokenPair:
    raise _NOT_YET


@router.get("/me", response_model=UserOut)
async def me() -> UserOut:
    raise _NOT_YET
