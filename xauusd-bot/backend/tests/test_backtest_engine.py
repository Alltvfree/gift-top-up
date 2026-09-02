"""Integration tests for the Backtester (deterministic data, no look-ahead)."""

from __future__ import annotations

import pytest

from app.core.config import BotConfig
from app.backtesting.engine import Backtester
from app.backtesting.metrics import compute_metrics
from app.strategies.factory import create_strategy

from tests.helpers import XAUUSD, build_uptrend_dataset


def bt_config():
    return BotConfig(
        strategy={
            "min_score": 70, "pullback_atr_mult": 50.0,
            "rsi_overbought": 100.0, "rsi_oversold": 0.0,
            # Short EMAs so the trend timeframe reaches a full window within the
            # test dataset (EMA200 would need 200+ H1 candles).
            "ema_fast": 20, "ema_slow": 50, "ema_short": 10,
        },
        risk={"cooldown_minutes": 0, "max_daily_trades": 1000, "max_positions": 1},
        break_even={"enabled": False},
        trailing_stop={"enabled": False},
        trading_sessions={"enabled": False},
    )


def run_bt():
    config = bt_config()
    candles = build_uptrend_dataset(n_entry=1000, start=1900, stop=2100)
    bt = Backtester(config, create_strategy(config), XAUUSD, candles,
                    starting_balance=10_000)
    return bt.run()


@pytest.fixture(scope="module")
def result():
    return run_bt()


def test_backtest_runs_and_trades(result):
    assert result.bars_processed > 0
    assert len(result.trades) > 0
    assert len(result.equity_curve) == result.bars_processed


def test_uptrend_is_net_positive(result):
    # A clean uptrend with 1:2 RR should net positive (mechanics check, NOT a
    # profitability claim — the data is synthetic).
    assert result.net_profit > 0
    metrics = compute_metrics(result)
    assert metrics.win_rate > 50.0


def test_no_lookahead_equity_monotonic_timestamps(result):
    times = [t for t, _ in result.equity_curve]
    assert times == sorted(times)


def test_reproducible(result):
    # A fresh run reproduces the shared result exactly.
    b = run_bt()
    assert result.ending_balance == b.ending_balance
    assert len(result.trades) == len(b.trades)
