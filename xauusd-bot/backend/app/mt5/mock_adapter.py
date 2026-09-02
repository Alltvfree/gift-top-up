"""Mock MT5 adapter — SYNTHETIC data for development and testing.

⚠️  The data produced here is deterministic pseudo-random noise, NOT a real
market feed. It exists so the strategy, risk and backtesting code can be
exercised on machines without a MetaTrader 5 terminal (e.g. CI on Linux).
Never present its output as real trading data.

Determinism: given the same seed, candle and tick history are reproducible,
which keeps unit tests stable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import numpy as np

from app.core.models import (
    AccountInfo,
    Candle,
    ConnectionStatus,
    Position,
    SymbolInfo,
    Tick,
    Timeframe,
)
from app.mt5.base import MT5Adapter, MT5AdapterError

# A realistic XAUUSD symbol profile (gold ~ $2,000, 2 digits, $1/tick per lot).
_DEFAULT_SYMBOLS: Dict[str, SymbolInfo] = {
    "XAUUSD": SymbolInfo(
        name="XAUUSD",
        digits=2,
        point=0.01,
        tick_size=0.01,
        tick_value=1.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        contract_size=100.0,
        currency_profit="USD",
    ),
}


class MockMT5Adapter(MT5Adapter):
    """In-memory MT5 replacement backed by a seeded random walk."""

    def __init__(
        self,
        symbols: Optional[Dict[str, SymbolInfo]] = None,
        *,
        seed: int = 42,
        start_price: float = 2000.0,
        balance: float = 10_000.0,
        spread_points: float = 20.0,
        now: Optional[datetime] = None,
    ) -> None:
        self._symbols = dict(symbols or _DEFAULT_SYMBOLS)
        self._seed = seed
        self._start_price = start_price
        self._balance = balance
        self._spread_points = spread_points
        self._now = now or datetime(2026, 1, 1, tzinfo=timezone.utc)
        self._connected = False
        self._positions: List[Position] = []
        # Cache generated candle series per (symbol, timeframe) for consistency.
        self._candle_cache: Dict[tuple[str, str], List[Candle]] = {}

    # --- Connection ----------------------------------------------------------
    def connect(self) -> ConnectionStatus:
        self._connected = True
        return ConnectionStatus(
            connected=True,
            message="mock terminal connected (SYNTHETIC data)",
            account=self.get_account_info(),
        )

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def _require_connection(self) -> None:
        if not self._connected:
            raise MT5AdapterError("mock adapter is not connected")

    # --- Account -------------------------------------------------------------
    def get_account_info(self) -> AccountInfo:
        return AccountInfo(
            login=1000001,
            server="MockServer-Demo",
            currency="USD",
            balance=self._balance,
            equity=self._balance,
            margin=0.0,
            margin_free=self._balance,
            leverage=100,
            name="Mock Account",
        )

    # --- Symbols -------------------------------------------------------------
    def list_symbols(self) -> List[str]:
        return list(self._symbols.keys())

    def get_symbol_info(self, symbol: str) -> Optional[SymbolInfo]:
        return self._symbols.get(symbol)

    def add_symbol(self, info: SymbolInfo) -> None:
        """Register an extra symbol (used by tests for odd broker profiles)."""
        self._symbols[info.name] = info

    # --- Market data ---------------------------------------------------------
    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int,
    ) -> List[Candle]:
        self._require_connection()
        if count <= 0:
            return []
        if symbol not in self._symbols:
            raise MT5AdapterError(f"unknown symbol: {symbol}")

        cache_key = (symbol, timeframe.value)
        series = self._candle_cache.get(cache_key)
        # Regenerate if we don't have enough cached bars.
        if series is None or len(series) < count:
            series = self._generate_candles(symbol, timeframe, max(count, 500))
            self._candle_cache[cache_key] = series
        return series[-count:]

    def get_tick(self, symbol: str) -> Optional[Tick]:
        self._require_connection()
        info = self._symbols.get(symbol)
        if info is None:
            return None
        candles = self.get_candles(symbol, Timeframe.M1, 1)
        last_close = candles[-1].close if candles else self._start_price
        half_spread = (self._spread_points * info.point) / 2.0
        bid = round(last_close - half_spread, info.digits)
        ask = round(last_close + half_spread, info.digits)
        return Tick(symbol=symbol, time=self._now, bid=bid, ask=ask)

    # --- Positions -----------------------------------------------------------
    def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        self._require_connection()
        if symbol is None:
            return list(self._positions)
        return [p for p in self._positions if p.symbol == symbol]

    def set_positions(self, positions: List[Position]) -> None:
        """Test helper to inject open positions."""
        self._positions = list(positions)

    # --- Synthetic generation ------------------------------------------------
    def _generate_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int,
    ) -> List[Candle]:
        """Seeded geometric-random-walk OHLC series, oldest first."""
        info = self._symbols[symbol]
        # Symbol- and timeframe-specific seed so different series differ but stay
        # reproducible run-to-run.
        rng = np.random.default_rng(
            self._seed + hash((symbol, timeframe.value)) % 10_000
        )
        # ~0.05% per-bar volatility of the random walk.
        returns = rng.normal(loc=0.0, scale=0.0005, size=count)
        prices = self._start_price * np.exp(np.cumsum(returns))

        candles: List[Candle] = []
        delta = timedelta(minutes=timeframe.minutes)
        # End the series at `_now`, walking backwards for the open times.
        start_time = self._now - delta * count
        for i in range(count):
            open_price = float(prices[i - 1]) if i > 0 else self._start_price
            close_price = float(prices[i])
            wick = abs(close_price - open_price) + info.point * rng.integers(1, 30)
            high = max(open_price, close_price) + wick * 0.5
            low = min(open_price, close_price) - wick * 0.5
            candles.append(
                Candle(
                    time=start_time + delta * i,
                    open=round(open_price, info.digits),
                    high=round(high, info.digits),
                    low=round(low, info.digits),
                    close=round(close_price, info.digits),
                    tick_volume=int(rng.integers(50, 500)),
                )
            )
        return candles


__all__ = ["MockMT5Adapter"]
