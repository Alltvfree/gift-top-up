"""Bot management endpoints — DB-backed CRUD + start/stop lifecycle.

The live trading loop (broker execution via Celery) is layered on in Task 4;
here start/stop transition persisted state so the full API and UI flow works
end to end against real data.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.db.models.bot import Bot
from app.db.models.order import Order
from app.db.models.position import Position
from app.schemas.bot import BotCreate, BotOut, BotUpdate, OrderOut, PositionOut

router = APIRouter()


async def _get_owned_bot(bot_id: uuid.UUID, user_id: uuid.UUID, db: DbSession) -> Bot:
    bot = await db.get(Bot, bot_id)
    if bot is None or bot.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found.")
    return bot


@router.get("", response_model=list[BotOut])
async def list_bots(current_user: CurrentUser, db: DbSession) -> list[Bot]:
    result = await db.scalars(
        select(Bot).where(Bot.user_id == current_user.id).order_by(Bot.created_at.desc())
    )
    return list(result.all())


@router.post("", response_model=BotOut, status_code=status.HTTP_201_CREATED)
async def create_bot(payload: BotCreate, current_user: CurrentUser, db: DbSession) -> Bot:
    bot = Bot(
        user_id=current_user.id,
        broker_account_id=payload.broker_account_id,
        name=payload.name,
        strategy=payload.strategy.value,
        symbol=payload.symbol,
        parameters=payload.parameters,
        ai_preset_used=payload.ai_preset_used,
    )
    db.add(bot)
    await db.commit()
    await db.refresh(bot)
    return bot


@router.get("/{bot_id}", response_model=BotOut)
async def get_bot(bot_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> Bot:
    return await _get_owned_bot(bot_id, current_user.id, db)


@router.patch("/{bot_id}", response_model=BotOut)
async def update_bot(
    bot_id: uuid.UUID, payload: BotUpdate, current_user: CurrentUser, db: DbSession
) -> Bot:
    bot = await _get_owned_bot(bot_id, current_user.id, db)
    if payload.name is not None:
        bot.name = payload.name
    if payload.parameters is not None:
        bot.parameters = payload.parameters
    await db.commit()
    await db.refresh(bot)
    return bot


@router.post("/{bot_id}/start", response_model=BotOut)
async def start_bot(bot_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> Bot:
    bot = await _get_owned_bot(bot_id, current_user.id, db)
    if bot.status == "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Bot is already running.")
    bot.status = "running"
    bot.started_at = datetime.now(timezone.utc)
    bot.stopped_at = None
    await db.commit()
    await db.refresh(bot)
    return bot


@router.post("/{bot_id}/stop", response_model=BotOut)
async def stop_bot(bot_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> Bot:
    bot = await _get_owned_bot(bot_id, current_user.id, db)
    bot.status = "stopped"
    bot.stopped_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(bot)
    return bot


@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bot(bot_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> None:
    bot = await _get_owned_bot(bot_id, current_user.id, db)
    await db.delete(bot)
    await db.commit()


@router.get("/{bot_id}/orders", response_model=list[OrderOut])
async def bot_orders(bot_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> list[Order]:
    await _get_owned_bot(bot_id, current_user.id, db)
    result = await db.scalars(
        select(Order).where(Order.bot_id == bot_id).order_by(Order.created_at.desc())
    )
    return list(result.all())


@router.get("/{bot_id}/positions", response_model=list[PositionOut])
async def bot_positions(
    bot_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> list[Position]:
    await _get_owned_bot(bot_id, current_user.id, db)
    result = await db.scalars(
        select(Position).where(Position.bot_id == bot_id).order_by(Position.opened_at.desc())
    )
    return list(result.all())
