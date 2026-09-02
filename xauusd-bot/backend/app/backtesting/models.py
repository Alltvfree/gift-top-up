"""Backtest data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Tuple

from app.core.models import OrderSide


@dataclass
class BacktestTrade:
    """A completed round-trip trade in a backtest."""

    signal_id: str
    side: OrderSide
    entry_time: datetime
    exit_time: datetime
    entry: float
    exit: float
    volume: float
    initial_sl: float
    take_profit: float
    profit: float
    r_multiple: float
    close_reason: str          # "SL" | "TP" | "TRAIL/BE" | "EOD"
    bars_held: int

    @property
    def is_win(self) -> bool:
        return self.profit > 0


@dataclass
class BacktestResult:
    """Everything a backtest produces (before/besides metrics)."""

    symbol: str
    strategy: str
    strategy_version: str
    starting_balance: float
    ending_balance: float
    trades: List[BacktestTrade] = field(default_factory=list)
    # (timestamp, equity) sampled at each entry bar close.
    equity_curve: List[Tuple[datetime, float]] = field(default_factory=list)
    bars_processed: int = 0

    @property
    def net_profit(self) -> float:
        return self.ending_balance - self.starting_balance


__all__ = ["BacktestTrade", "BacktestResult"]
