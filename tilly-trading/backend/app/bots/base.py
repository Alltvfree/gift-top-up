"""Base bot class — the lifecycle contract every strategy implements."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.broker.base import BrokerClient


class BaseBot(ABC):
    def __init__(self, bot_id: str, broker: BrokerClient, params: dict[str, Any]) -> None:
        self.bot_id = bot_id
        self.broker = broker
        self.params = params
        self.is_running = False

    @abstractmethod
    async def initialize(self) -> None:
        """Set up initial state and place first orders."""

    @abstractmethod
    async def on_tick(self, symbol: str, bid: float, ask: float) -> None:
        """Called on every price update."""

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
