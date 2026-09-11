"""Bot management endpoints.

Route surface matches the spec. CRUD persistence and the start/stop
lifecycle are implemented in Task 4 (Bot Engine Core); the strategy
registry they build on already exists in `app.services.bot_runner`.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.schemas.bot import BotCreate, BotOut, BotUpdate, OrderOut, PositionOut

router = APIRouter()

_NOT_YET = HTTPException(
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    detail="Bot persistence & lifecycle are implemented in Task 4 (Bot Engine Core).",
)


@router.get("", response_model=list[BotOut])
async def list_bots() -> list[BotOut]:
    raise _NOT_YET


@router.post("", response_model=BotOut, status_code=status.HTTP_201_CREATED)
async def create_bot(payload: BotCreate) -> BotOut:
    raise _NOT_YET


@router.get("/{bot_id}", response_model=BotOut)
async def get_bot(bot_id: uuid.UUID) -> BotOut:
    raise _NOT_YET


@router.patch("/{bot_id}", response_model=BotOut)
async def update_bot(bot_id: uuid.UUID, payload: BotUpdate) -> BotOut:
    raise _NOT_YET


@router.post("/{bot_id}/start", response_model=BotOut)
async def start_bot(bot_id: uuid.UUID) -> BotOut:
    raise _NOT_YET


@router.post("/{bot_id}/stop", response_model=BotOut)
async def stop_bot(bot_id: uuid.UUID) -> BotOut:
    raise _NOT_YET


@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bot(bot_id: uuid.UUID) -> None:
    raise _NOT_YET


@router.get("/{bot_id}/orders", response_model=list[OrderOut])
async def bot_orders(bot_id: uuid.UUID) -> list[OrderOut]:
    raise _NOT_YET


@router.get("/{bot_id}/positions", response_model=list[PositionOut])
async def bot_positions(bot_id: uuid.UUID) -> list[PositionOut]:
    raise _NOT_YET
