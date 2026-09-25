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

    async def get_candles(self, symbol: str, timeframe: str, limit: int) -> list[dict]:
        """Historical OHLC bars, for adapters with a real history API (e.g.
        the MT5 bridge via MetaTrader5.copy_rates_from_pos). Not abstract —
        most adapters (paper, and MetaAPI's RPC connection) have no candle
        history to offer; callers should catch NotImplementedError and fall
        back to another price source rather than treat it as a hard error."""
        raise NotImplementedError(f"{type(self).__name__} does not support get_candles().")

    async def get_symbols(self) -> list[str]:
        """Every symbol this account's connection knows about, by its exact
        broker-side name. Not abstract, same reasoning as get_candles() —
        only adapters backed by a real broker connection (the MT5 bridge)
        can answer this; callers fall back to a fixed symbol list on
        NotImplementedError."""
        raise NotImplementedError(f"{type(self).__name__} does not support get_symbols().")
