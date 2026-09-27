"""Base bot class — the lifecycle contract every strategy implements."""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.base import BrokerClient


class BaseBot(ABC):
    def __init__(self, bot_id: str, broker: BrokerClient, params: dict[str, Any]) -> None:
        self.bot_id = bot_id
        self.broker = broker
        self.params = params
        self.is_running = False

    @property
    def magic(self) -> int:
        """Stable MT5 "magic number" for this bot, derived from its id.

        A real broker account has no concept of "which Tilly bot" opened a
        position — without tagging orders ourselves, two bots trading the
        same symbol on the same account can't tell their own positions
        apart from each other's (they double-count each other's P&L, and a
        GRID bot's take-profit logic can close a position a different bot
        opened). Derived deterministically so it's stable across restarts
        without needing a DB column. Kept within int32 range since that's
        the narrowest range any broker/server is guaranteed to accept.
        """
        digest = hashlib.sha256(self.bot_id.encode()).hexdigest()
        return int(digest[:8], 16) % 2_000_000_000

    @abstractmethod
    async def initialize(self) -> None:
        """Set up initial state and place first orders."""

    @abstractmethod
    async def on_tick(self, symbol: str, bid: float, ask: float, session: AsyncSession) -> None:
        """Called on every price update. `session` is the engine's current
        dispatch-cycle DB session — only needed by strategies that opt into
        `require_signal` (see app/services/signal_gate.py); most bots can
        ignore it."""

    @abstractmethod
    async def on_order_filled(self, order_id: str, fill_price: float, volume: float) -> None:
        """Called when an order is executed."""

    async def run(self) -> None:
        """Start the bot: initialize, then run until stopped.

        The full event loop (price-feed subscription + order updates) is
        driven by the bot runner service (Task 4).
        """
        self.is_running = True
        await self.initialize()

    async def stop(self) -> None:
        self.is_running = False
