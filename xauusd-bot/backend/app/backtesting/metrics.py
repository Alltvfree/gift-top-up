"""Backtest performance metrics.

All metrics are computed directly from the realized trades and the sampled
equity curve — nothing is smoothed, hidden, or annualized away (spec §§21,37).
Sharpe/Sortino are reported on the per-trade return series and are explicitly
*not* annualized (documented, so they are reproducible and not overstated).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import List, Sequence, Tuple

from app.backtesting.models import BacktestResult, BacktestTrade


@dataclass
class Metrics:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    net_profit: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    average_trade: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    expectancy: float = 0.0
    expectancy_r: float = 0.0
    longest_winning_streak: int = 0
    longest_losing_streak: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def compute_metrics(result: BacktestResult) -> Metrics:
    trades = result.trades
    m = Metrics(total_trades=len(trades))
    if not trades:
        return m

    profits = [t.profit for t in trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]

    m.winning_trades = len(wins)
    m.losing_trades = len(losses)
    m.win_rate = round(len(wins) / len(trades) * 100, 2)
    m.gross_profit = round(sum(wins), 2)
    m.gross_loss = round(sum(losses), 2)
    m.net_profit = round(sum(profits), 2)
    m.profit_factor = round(
        (m.gross_profit / abs(m.gross_loss)) if m.gross_loss != 0 else math.inf, 3
    )
    m.average_win = round(sum(wins) / len(wins), 2) if wins else 0.0
    m.average_loss = round(sum(losses) / len(losses), 2) if losses else 0.0
    m.average_trade = round(sum(profits) / len(profits), 2)

    dd, dd_pct = _max_drawdown([e for _, e in result.equity_curve])
    m.max_drawdown = round(dd, 2)
    m.max_drawdown_pct = round(dd_pct, 2)

    returns = _per_trade_returns(trades, result.starting_balance)
    m.sharpe_ratio = round(_sharpe(returns), 3)
    m.sortino_ratio = round(_sortino(returns), 3)

    win_rate = len(wins) / len(trades)
    m.expectancy = round(
        win_rate * m.average_win + (1 - win_rate) * m.average_loss, 2
    )
    m.expectancy_r = round(sum(t.r_multiple for t in trades) / len(trades), 3)

    m.longest_winning_streak, m.longest_losing_streak = _streaks(trades)
    return m


def _max_drawdown(equity: Sequence[float]) -> Tuple[float, float]:
    peak = -math.inf
    max_dd = 0.0
    max_dd_pct = 0.0
    for value in equity:
        peak = max(peak, value)
        dd = peak - value
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = (dd / peak * 100) if peak > 0 else 0.0
    return max_dd, max_dd_pct


def _per_trade_returns(trades: List[BacktestTrade], starting_balance: float) -> List[float]:
    if starting_balance <= 0:
        return [0.0 for _ in trades]
    return [t.profit / starting_balance for t in trades]


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    mu = _mean(xs)
    var = sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(var)


def _sharpe(returns: Sequence[float]) -> float:
    sd = _std(returns)
    return (_mean(returns) / sd) if sd > 0 else 0.0


def _sortino(returns: Sequence[float]) -> float:
    downside = [r for r in returns if r < 0]
    if not downside:
        return 0.0
    dd = math.sqrt(sum(r ** 2 for r in downside) / len(downside))
    return (_mean(returns) / dd) if dd > 0 else 0.0


def _streaks(trades: Sequence[BacktestTrade]) -> Tuple[int, int]:
    longest_win = longest_loss = 0
    cur_win = cur_loss = 0
    for t in trades:
        if t.is_win:
            cur_win += 1
            cur_loss = 0
        else:
            cur_loss += 1
            cur_win = 0
        longest_win = max(longest_win, cur_win)
        longest_loss = max(longest_loss, cur_loss)
    return longest_win, longest_loss


__all__ = ["Metrics", "compute_metrics"]
