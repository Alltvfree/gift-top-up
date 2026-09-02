"""Tests for backtest metrics and reporting."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.core.models import OrderSide
from app.backtesting.metrics import compute_metrics
from app.backtesting.models import BacktestResult, BacktestTrade
from app.backtesting import report

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def trade(profit, r, day=1, month=1):
    t = T0.replace(month=month, day=day)
    return BacktestTrade(
        signal_id="s", side=OrderSide.BUY, entry_time=t, exit_time=t,
        entry=2000, exit=2000 + profit, volume=0.1, initial_sl=1990,
        take_profit=2020, profit=profit, r_multiple=r, close_reason="TP",
        bars_held=3,
    )


def make_result(profits_and_r, equity):
    trades = [trade(p, r, day=i + 1) for i, (p, r) in enumerate(profits_and_r)]
    return BacktestResult(
        symbol="XAUUSD", strategy="t", strategy_version="1",
        starting_balance=10_000, ending_balance=10_000 + sum(p for p, _ in profits_and_r),
        trades=trades,
        equity_curve=[(T0 + timedelta(days=i), e) for i, e in enumerate(equity)],
    )


def test_basic_metrics():
    result = make_result(
        [(100, 2.0), (100, 2.0), (-50, -1.0), (100, 2.0), (-50, -1.0)],
        equity=[10_000, 10_100, 10_200, 10_150, 10_250, 10_200],
    )
    m = compute_metrics(result)
    assert m.total_trades == 5
    assert m.winning_trades == 3
    assert m.losing_trades == 2
    assert m.win_rate == 60.0
    assert m.gross_profit == 300.0
    assert m.gross_loss == -100.0
    assert m.profit_factor == 3.0
    assert m.average_win == 100.0
    assert m.average_loss == -50.0
    assert m.net_profit == 200.0


def test_streaks():
    result = make_result(
        [(10, 1), (10, 1), (10, 1), (-5, -1), (-5, -1), (10, 1)],
        equity=[10_000, 10_010, 10_020, 10_030, 10_025, 10_020, 10_030],
    )
    m = compute_metrics(result)
    assert m.longest_winning_streak == 3
    assert m.longest_losing_streak == 2


def test_max_drawdown():
    # Peak 10_200, trough 10_150 -> dd 50 (~0.49%).
    result = make_result(
        [(100, 2.0)],
        equity=[10_000, 10_200, 10_150],
    )
    m = compute_metrics(result)
    assert m.max_drawdown == 50.0
    assert 0.4 < m.max_drawdown_pct < 0.5


def test_empty_result_is_safe():
    result = BacktestResult("XAUUSD", "t", "1", 10_000, 10_000)
    m = compute_metrics(result)
    assert m.total_trades == 0
    assert m.win_rate == 0.0


def test_report_breakdowns_and_export(tmp_path):
    result = make_result(
        [(100, 2.0), (-50, -1.0), (100, 2.0)],
        equity=[10_000, 10_100, 10_050, 10_150],
    )
    rep = report.build_report(result)
    assert "metrics" in rep and "equity_curve" in rep
    assert rep["monthly_performance"]  # grouped
    assert rep["trade_distribution"]

    json_path = tmp_path / "report.json"
    report.export_json(result, json_path)
    loaded = json.loads(json_path.read_text())
    assert loaded["metrics"]["total_trades"] == 3

    csv_path = tmp_path / "trades.csv"
    report.export_trades_csv(result, csv_path)
    lines = csv_path.read_text().splitlines()
    assert len(lines) == 4  # header + 3 trades
