"""Shared test fixtures/helpers for deterministic market data."""

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
from app.mt5.base import MT5Adapter
from app.mt5.market_data import MarketDataService

XAUUSD = SymbolInfo(
    name="XAUUSD", digits=2, point=0.01, tick_size=0.01, tick_value=1.0,
    volume_min=0.01, volume_max=100.0, volume_step=0.01,
)

BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_candles(closes, tf: Timeframe, pad: float = 0.5) -> List[Candle]:
    out: List[Candle] = []
    delta = timedelta(minutes=tf.minutes)
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append(
            Candle(
                time=BASE_TIME + delta * i,
                open=round(o, 2), high=round(max(o, c) + pad, 2),
                low=round(min(o, c) - pad, 2), close=round(c, 2),
                tick_volume=100,
            )
        )
        prev = c
    return out


def rising(n, start, stop):
    return list(np.linspace(start, stop, n))


class FakeAdapter(MT5Adapter):
    """Adapter returning caller-supplied candles and a settable tick."""

    def __init__(
        self,
        symbol_info: SymbolInfo,
        frames: Dict[Timeframe, List[Candle]],
        tick: Tick,
        balance: float = 10_000.0,
    ) -> None:
        self._info = symbol_info
        self._frames = frames
        self.tick = tick
        self._balance = balance
        self._connected = False

    def connect(self) -> ConnectionStatus:
        self._connected = True
        return ConnectionStatus(True, "fake connected")

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def get_account_info(self) -> AccountInfo:
        return AccountInfo(1, "Fake", "USD", self._balance, self._balance,
                           0.0, self._balance, 100, "Fake")

    def list_symbols(self) -> List[str]:
        return [self._info.name]

    def get_symbol_info(self, symbol: str) -> Optional[SymbolInfo]:
        return self._info if symbol == self._info.name else None

    def get_tick(self, symbol: str) -> Optional[Tick]:
        return self.tick

    def get_candles(self, symbol, timeframe, count) -> List[Candle]:
        return self._frames[timeframe][-count:]

    def get_positions(self, symbol=None) -> List[Position]:
        return []

    # test helper: append a new candle to shift the "last completed" bar.
    def append_candle(self, tf: Timeframe, close: float) -> None:
        series = self._frames[tf]
        last = series[-1]
        series.append(
            Candle(
                time=last.time + timedelta(minutes=tf.minutes),
                open=last.close, high=round(max(last.close, close) + 0.5, 2),
                low=round(min(last.close, close) - 0.5, 2), close=round(close, 2),
                tick_volume=100,
            )
        )


def build_uptrend_dataset(n_entry: int = 1500, start: float = 1900.0,
                          stop: float = 2100.0):
    """Time-aligned M5/M15/H1 candle lists rising start->stop for backtests."""
    n_setup = n_entry * Timeframe.M5.minutes // Timeframe.M15.minutes + 5
    n_trend = n_entry * Timeframe.M5.minutes // Timeframe.H1.minutes + 5
    return {
        Timeframe.H1: make_candles(rising(n_trend, start, stop), Timeframe.H1),
        Timeframe.M15: make_candles(rising(n_setup, start, stop), Timeframe.M15),
        Timeframe.M5: make_candles(rising(n_entry, start, stop), Timeframe.M5),
    }


def build_uptrend_market(balance: float = 10_000.0) -> tuple[MarketDataService, FakeAdapter]:
    """A clean rising market across all three timeframes -> BUY-able."""
    frames = {
        Timeframe.H1: make_candles(rising(300, 1900, 2000), Timeframe.H1),
        Timeframe.M15: make_candles(rising(260, 1950, 2000), Timeframe.M15),
        Timeframe.M5: make_candles(rising(260, 1980, 2000), Timeframe.M5),
    }
    tick = Tick("XAUUSD", BASE_TIME, bid=1999.90, ask=2000.10)
    adapter = FakeAdapter(XAUUSD, frames, tick, balance=balance)
    adapter.connect()
    market = MarketDataService(adapter)
    market.resolve_symbol(["XAUUSD"])
    return market, adapter
