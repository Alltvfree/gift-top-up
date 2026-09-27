"""Account/equity simulation (Phase 11).

Balance changes only on a realized close (TP/SL/time/end-of-test); equity
also reflects the current open position's unrealized P&L, marked at every
bar so the drawdown curve is meaningful intrabar, not just at trade exits.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class EquityPoint:
    time: pd.Timestamp
    balance: float
    equity: float
    drawdown: float
    drawdown_percent: float
    open_positions: int


class Account:
    def __init__(self, initial_balance: float, currency: str = "USD"):
        if initial_balance <= 0:
            raise ValueError("initial_balance must be positive.")
        self.initial_balance = initial_balance
        self.currency = currency
        self.balance = initial_balance
        self._peak_equity = initial_balance
        self.curve: list[EquityPoint] = []

    def realize(self, net_pnl: float) -> None:
        self.balance += net_pnl

    def mark(self, time: pd.Timestamp, unrealized_pnl: float, open_positions: int) -> EquityPoint:
        equity = self.balance + unrealized_pnl
        self._peak_equity = max(self._peak_equity, equity)
        drawdown = self._peak_equity - equity
        drawdown_percent = (drawdown / self._peak_equity * 100.0) if self._peak_equity > 0 else 0.0
        point = EquityPoint(time, self.balance, equity, drawdown, drawdown_percent, open_positions)
        self.curve.append(point)
        return point

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([vars(p) for p in self.curve])

    @property
    def max_drawdown(self) -> float:
        return max((p.drawdown for p in self.curve), default=0.0)

    @property
    def max_drawdown_percent(self) -> float:
        return max((p.drawdown_percent for p in self.curve), default=0.0)
