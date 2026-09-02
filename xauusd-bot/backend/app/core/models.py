"""Core domain models shared across the trading bot.

These are lightweight, framework-agnostic value objects that describe the data
we exchange with MetaTrader 5. Keeping them here (rather than leaking MT5's own
named-tuples throughout the codebase) is what lets the MT5 adapter be mocked
and swapped freely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class TradingMode(str, Enum):
    """Where orders go. Only DEMO/LIVE touch a real broker."""

    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    DEMO = "DEMO"
    LIVE = "LIVE"


class Timeframe(str, Enum):
    """Supported chart timeframes."""

    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"

    @property
    def minutes(self) -> int:
        return {
            Timeframe.M1: 1,
            Timeframe.M5: 5,
            Timeframe.M15: 15,
            Timeframe.M30: 30,
            Timeframe.H1: 60,
            Timeframe.H4: 240,
            Timeframe.D1: 1440,
        }[self]


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class SymbolInfo:
    """Static/dynamic properties of a tradable symbol.

    Never assume XAUUSD has 2 digits — always read ``digits`` from here.
    """

    name: str
    digits: int
    point: float            # smallest price increment (e.g. 0.01)
    tick_size: float        # minimum price change per tick
    tick_value: float       # account-currency value of one tick per 1.0 lot
    volume_min: float       # broker minimum lot
    volume_max: float       # broker maximum lot
    volume_step: float      # lot step
    contract_size: float = 100.0
    currency_profit: str = "USD"

    @property
    def points_per_price(self) -> float:
        """How many broker 'points' make up one unit of price."""
        return 1.0 / self.point if self.point else 0.0


@dataclass(frozen=True)
class Tick:
    """A single price tick."""

    symbol: str
    time: datetime
    bid: float
    ask: float

    @property
    def spread(self) -> float:
        """Raw spread in price terms (ask - bid)."""
        return self.ask - self.bid

    def spread_points(self, symbol_info: SymbolInfo) -> float:
        """Spread expressed in broker points."""
        if not symbol_info.point:
            return 0.0
        return self.spread / symbol_info.point


@dataclass(frozen=True)
class Candle:
    """A single OHLC bar. ``time`` is the bar's OPEN time (UTC)."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int = 0
    spread: int = 0
    real_volume: int = 0


@dataclass(frozen=True)
class AccountInfo:
    """Snapshot of the trading account."""

    login: int
    server: str
    currency: str
    balance: float
    equity: float
    margin: float
    margin_free: float
    leverage: int = 0
    name: str = ""

    @property
    def margin_level(self) -> Optional[float]:
        if self.margin <= 0:
            return None
        return (self.equity / self.margin) * 100.0


@dataclass(frozen=True)
class Position:
    """An open position as reported by the terminal."""

    ticket: int
    symbol: str
    side: OrderSide
    volume: float
    price_open: float
    sl: float
    tp: float
    price_current: float
    profit: float
    time: datetime
    comment: str = ""
    magic: int = 0


@dataclass
class ConnectionStatus:
    """Result of a connection attempt / health check."""

    connected: bool
    message: str = ""
    account: Optional[AccountInfo] = field(default=None)
