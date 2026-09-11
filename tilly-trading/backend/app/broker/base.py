"""Abstract broker client interface.

All broker integrations (MetaAPI/Exness, and future direct integrations)
implement this contract so the bot engine stays broker-agnostic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class OrderResult:
    """Normalized result returned from an order placement."""

    id: str
    symbol: str
    side: str
    volume: float
    filled_price: float | None = None
    status: str = "pending"


@dataclass
class Quote:
    symbol: str
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


class BrokerClient(ABC):
    """Contract every broker adapter must satisfy."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish and synchronize the broker connection."""

    @abstractmethod
    async def get_balance(self) -> float:
        """Return the account balance."""

    @abstractmethod
    async def get_price(self, symbol: str) -> float:
        """Return the mid price for a symbol."""

    @abstractmethod
    async def get_quote(self, symbol: str) -> Quote:
        """Return the full bid/ask quote for a symbol."""

    @abstractmethod
    async def place_market_order(self, symbol: str, side: str, volume: float) -> OrderResult:
        """Place a market order."""

    @abstractmethod
    async def place_limit_order(
        self, symbol: str, side: str, price: float, volume: float
    ) -> OrderResult:
        """Place a limit order."""

    @abstractmethod
    async def close_position(self, position_id: str) -> None:
        """Close an open position by id."""
