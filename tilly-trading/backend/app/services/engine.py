"""Trading engine — drives running bots against their broker (Task 4).

Runs inside the Celery worker. Because the MetaAPI SDK (aiohttp) binds
connections to the event loop that created them, the engine owns a single
long-lived asyncio loop on a background thread; every tick is scheduled onto
that loop so bot state and broker connections persist between ticks.

Lifecycle each tick (`dispatch`):
  1. Load bots with status='running' from the DB.
  2. Start any that aren't running yet (connect broker + strategy.initialize).
  3. Stop any live bots whose DB status is no longer 'running'.
  4. Tick each live bot (strategy.on_tick) and sync positions/PnL to the DB.

Run the worker single-process for correct shared state:
    celery -A app.tasks.celery_app.celery_app worker --pool=solo
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select

from app.bots.base import BaseBot
from app.broker.base import BrokerClient
from app.broker.registry import build_broker_for_account
from app.db.models.bot import Bot
from app.db.models.broker_account import BrokerAccount
from app.db.models.position import Position
from app.db.session import async_session_factory
from app.services.bot_runner import build_bot

logger = logging.getLogger("tilly.engine")


@dataclass
class RunningBot:
    bot_id: str
    symbol: str
    broker: BrokerClient
    strategy: BaseBot


class _EngineLoop:
    """Owns a dedicated asyncio loop on a background thread."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ensure(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(
                    target=self._loop.run_forever, name="tilly-engine", daemon=True
                )
                self._thread.start()
            return self._loop

    def run(self, coro, timeout: float = 120.0):
        loop = self._ensure()
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=timeout)


class TradingEngine:
    def __init__(self) -> None:
        self.running: dict[str, RunningBot] = {}
        self._loop = _EngineLoop()

    # ---- sync entrypoint for Celery ----
    def tick(self) -> dict:
        # Simulated bots need no MetaAPI token; metaapi bots are guarded per-bot
        # in build_broker_for_account, so always dispatch.
        return self._loop.run(self._dispatch())

    # ---- async logic (runs on the engine loop) ----
    async def _dispatch(self) -> dict:
        async with async_session_factory() as session:
            rows = (await session.scalars(select(Bot).where(Bot.status == "running"))).all()
            wanted = {str(b.id): b for b in rows}

            started, stopped, ticked, errored = 0, 0, 0, 0

            # Stop bots no longer marked running.
            for bot_id in list(self.running.keys()):
                if bot_id not in wanted:
                    await self._stop(bot_id)
                    stopped += 1

            # Start newly-running bots.
            for bot_id, bot in wanted.items():
                if bot_id not in self.running:
                    try:
                        await self._start(bot, session)
                        bot.last_error = None
                        await session.commit()
                        started += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("Failed to start bot %s", bot_id)
                        bot.status = "error"
                        bot.last_error = f"{type(exc).__name__}: {exc}"[:500]
                        await session.commit()
                        errored += 1

            # Tick live bots.
            for bot_id, running in list(self.running.items()):
                bot = wanted.get(bot_id)
                if bot is None:
                    continue
                try:
                    await self._tick(running, bot, session)
                    ticked += 1
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Tick failed for bot %s", bot_id)

            return {
                "status": "ok",
                "running": len(self.running),
                "started": started,
                "stopped": stopped,
                "ticked": ticked,
                "errored": errored,
            }

    async def _start(self, bot: Bot, session) -> None:
        if bot.broker_account_id is None:
            raise RuntimeError("Bot has no broker account linked.")
        account = await session.get(BrokerAccount, bot.broker_account_id)
        if account is None:
            raise RuntimeError("Linked broker account not found.")

        broker = build_broker_for_account(account)
        await broker.connect()

        params = {**(bot.parameters or {}), "symbol": bot.symbol}
        strategy = build_bot(bot.strategy, str(bot.id), broker, params)
        await strategy.initialize()

        self.running[str(bot.id)] = RunningBot(
            bot_id=str(bot.id), symbol=bot.symbol, broker=broker, strategy=strategy
        )
        logger.info("Started bot %s (%s %s)", bot.id, bot.strategy, bot.symbol)
        await self._sync_positions(self.running[str(bot.id)], bot, session)

    async def _stop(self, bot_id: str) -> None:
        running = self.running.pop(bot_id, None)
        if running is None:
            return
        try:
            await running.broker.close()
        except Exception:  # noqa: BLE001
            pass
        logger.info("Stopped bot %s", bot_id)

    async def _tick(self, running: RunningBot, bot: Bot, session) -> None:
        quote = await running.broker.get_quote(running.symbol)
        await running.strategy.on_tick(running.symbol, quote.bid, quote.ask)
        await self._sync_positions(running, bot, session)

    async def _sync_positions(self, running: RunningBot, bot: Bot, session) -> None:
        """Reflect broker positions for this bot's symbol into the DB + PnL.

        Diffs the broker's snapshot against this bot's open DB rows instead of
        replacing them wholesale: a row still reported stays open and gets its
        live price/PnL updated in place (stable id across ticks); a row that
        dropped out of the snapshot has closed, and is marked `closed_at` with
        its last-known unrealized PnL as `realized_pnl` — rather than deleted —
        so it becomes trade history for the journal (Trades page). The broker
        interface doesn't hand back an exact close fill price, so that
        realized figure is a same-tick approximation, not a booked exit price.
        """
        try:
            broker_positions = await running.broker.get_positions()
        except Exception:  # noqa: BLE001
            return
        mine = [p for p in broker_positions if p.get("symbol") == running.symbol]
        live_ids = {str(p.get("id", "")) for p in mine}

        existing = (
            await session.scalars(
                select(Position).where(Position.bot_id == bot.id, Position.closed_at.is_(None))
            )
        ).all()
        existing_by_broker_id = {p.broker_position_id: p for p in existing if p.broker_position_id}

        now = datetime.now(timezone.utc)
        for row in existing:
            if row.broker_position_id not in live_ids:
                row.closed_at = now
                row.realized_pnl = row.unrealized_pnl

        total_unrealized = 0.0
        for p in mine:
            broker_id = str(p.get("id", ""))
            upnl = float(p.get("unrealizedProfit", p.get("profit", 0)) or 0)
            total_unrealized += upnl
            current_price = float(p.get("currentPrice", 0) or 0) or None
            row = existing_by_broker_id.get(broker_id)
            if row is not None:
                row.current_price = current_price
                row.unrealized_pnl = upnl
            else:
                session.add(
                    Position(
                        bot_id=bot.id,
                        broker_position_id=broker_id,
                        symbol=running.symbol,
                        side=str(p.get("type", "")).replace("POSITION_TYPE_", ""),
                        volume=float(p.get("volume", 0) or 0),
                        open_price=float(p.get("openPrice", 0) or 0),
                        current_price=current_price,
                        unrealized_pnl=upnl,
                    )
                )

        bot.total_pnl = total_unrealized
        bot.stopped_at = None if bot.status == "running" else now
        await session.commit()


# Module-level singleton used by the Celery task.
engine = TradingEngine()
