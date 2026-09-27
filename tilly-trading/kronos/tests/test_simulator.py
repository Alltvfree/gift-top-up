"""Trade simulator (Phases 6, 7, 9, 12, 13) against hand-constructed price
paths with known outcomes — same style as labels.py's own tests, but for
realistic execution instead of raw labeling.
"""
import numpy as np
import pandas as pd
import pytest

from backtest.account import Account
from backtest.config import (
    BacktestConfig, CommissionConfig, ExecutionConfig, RiskConfig, SignalConfig,
    SlippageConfig, SpreadConfig, StopLossConfig, TakeProfitConfig,
)
from backtest.simulator import run_simulation
from backtest.symbols import get_symbol_spec

spec = get_symbol_spec("XAUUSDm")  # contract_size=100, point=0.01


def _zero_cost_cfg(**overrides) -> BacktestConfig:
    cfg = BacktestConfig(
        stop_loss=StopLossConfig(type="price", value=2.0),
        take_profit=TakeProfitConfig(type="price", value=3.0),
        spread=SpreadConfig(mode="fixed", points=0.0),
        slippage=SlippageConfig(mode="fixed_points", points=0.0),
        commission=CommissionConfig(type="per_lot", value=0.0),
        risk=RiskConfig(mode="fixed_lot", fixed_lot=1.0),
        signal=SignalConfig(buy_threshold=0.6, sell_threshold=0.4, cooldown_bars=0),
        execution=ExecutionConfig(next_bar=True, same_bar_exit_policy="conservative", max_holding_bars=10),
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _bars(prices: dict, n: int, probability_at_0=np.nan) -> pd.DataFrame:
    times = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    prob = np.full(n, np.nan)
    prob[0] = probability_at_0
    return pd.DataFrame(
        {
            "time": times,
            "open": prices["open"], "high": prices["high"], "low": prices["low"], "close": prices["close"],
            "spread": np.zeros(n),
            "predicted_probability": prob,
        }
    )


def test_buy_hits_tp_on_the_entry_bar_itself():
    df = _bars(
        {"open": [100, 100, 103, 103, 103], "high": [100, 104, 103, 103, 103],
         "low": [100, 99.5, 103, 103, 103], "close": [100, 103, 103, 103, 103]},
        5, probability_at_0=0.9,
    )
    account = Account(10000.0)
    trades = run_simulation(df, _zero_cost_cfg(), spec, account, window_index=0)
    assert len(trades) == 1
    t = trades[0]
    assert t.direction == "BUY"
    assert t.entry_price == pytest.approx(100.0)
    assert t.exit_price == pytest.approx(103.0)
    assert t.exit_reason == "TP"
    assert t.gross_pnl == pytest.approx(300.0)
    assert account.balance == pytest.approx(10300.0)


def test_sell_hits_sl():
    df = _bars(
        {"open": [100, 100, 100, 100, 100], "high": [100, 103, 100, 100, 100],
         "low": [100, 99, 100, 100, 100], "close": [100, 101, 100, 100, 100]},
        5, probability_at_0=0.1,
    )
    account = Account(10000.0)
    trades = run_simulation(df, _zero_cost_cfg(), spec, account, window_index=0)
    assert len(trades) == 1
    t = trades[0]
    assert t.direction == "SELL"
    assert t.exit_reason == "SL"
    assert t.exit_price == pytest.approx(102.0)  # entry 100, SL distance 2 -> SELL SL at +2
    assert t.gross_pnl == pytest.approx(-200.0)
    assert account.balance == pytest.approx(9800.0)


def test_same_bar_tp_and_sl_conservative_default_assumes_sl():
    df = _bars(
        {"open": [100, 100, 103, 103, 103], "high": [100, 104, 103, 103, 103],
         "low": [100, 97, 103, 103, 103], "close": [100, 100, 103, 103, 103]},
        5, probability_at_0=0.9,
    )
    account = Account(10000.0)
    trades = run_simulation(df, _zero_cost_cfg(), spec, account, window_index=0)
    assert trades[0].exit_reason == "SL"
    assert trades[0].exit_price == pytest.approx(98.0)


def test_same_bar_tp_and_sl_optimistic_policy_assumes_tp():
    df = _bars(
        {"open": [100, 100, 103, 103, 103], "high": [100, 104, 103, 103, 103],
         "low": [100, 97, 103, 103, 103], "close": [100, 100, 103, 103, 103]},
        5, probability_at_0=0.9,
    )
    cfg = _zero_cost_cfg()
    cfg.execution.same_bar_exit_policy = "optimistic"
    account = Account(10000.0)
    trades = run_simulation(df, cfg, spec, account, window_index=0, )
    assert trades[0].exit_reason == "TP"
    assert trades[0].exit_price == pytest.approx(103.0)


def test_time_exit_when_neither_tp_nor_sl_hit_within_horizon():
    n = 8
    df = _bars(
        {"open": [100.0] * n, "high": [100.2] * n, "low": [99.8] * n, "close": [100.0] * n},
        n, probability_at_0=0.9,
    )
    cfg = _zero_cost_cfg()
    cfg.execution.max_holding_bars = 3
    account = Account(10000.0)
    trades = run_simulation(df, cfg, spec, account, window_index=0)
    assert len(trades) == 1
    assert trades[0].exit_reason == "TIME_EXIT"


def test_end_of_test_when_data_runs_out_before_horizon():
    n = 4  # shorter than max_holding_bars
    df = _bars(
        {"open": [100.0] * n, "high": [100.2] * n, "low": [99.8] * n, "close": [100.0] * n},
        n, probability_at_0=0.9,
    )
    cfg = _zero_cost_cfg()
    cfg.execution.max_holding_bars = 20
    account = Account(10000.0)
    trades = run_simulation(df, cfg, spec, account, window_index=0)
    assert len(trades) == 1
    assert trades[0].exit_reason == "END_OF_TEST"


def test_cooldown_blocks_immediate_reentry():
    n = 10
    prob = np.full(n, np.nan)
    prob[0] = 0.9  # BUY signal, entry at bar1, immediately hits TP at bar1
    prob[2] = 0.9  # another BUY signal right after the first trade closes at bar1
    df = pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC"),
            "open": [100] * n, "high": [104] * n, "low": [99.5] * n, "close": [103] * n,
            "spread": [0] * n, "predicted_probability": prob,
        }
    )
    cfg = _zero_cost_cfg()
    cfg.signal.cooldown_bars = 5
    account = Account(10000.0)
    trades = run_simulation(df, cfg, spec, account, window_index=0)
    assert len(trades) == 1, "the second signal fell inside the cooldown window and must be ignored"


def test_position_sizing_skip_opens_no_trade_and_does_not_hang():
    n = 5
    df = _bars(
        {"open": [100] * n, "high": [104] * n, "low": [99.5] * n, "close": [103] * n},
        n, probability_at_0=0.9,
    )
    cfg = _zero_cost_cfg(risk=RiskConfig(mode="fixed_money", fixed_money=0.0001))
    account = Account(10000.0)
    trades = run_simulation(df, cfg, spec, account, window_index=0)
    assert trades == []


def test_spread_slippage_and_commission_all_reduce_net_pnl():
    df = _bars(
        {"open": [100, 100, 103, 103, 103], "high": [100, 104, 103, 103, 103],
         "low": [100, 99.5, 103, 103, 103], "close": [100, 103, 103, 103, 103]},
        5, probability_at_0=0.9,
    )
    zero_cost = run_simulation(df, _zero_cost_cfg(), spec, Account(10000.0), window_index=0)[0]

    costly_cfg = _zero_cost_cfg(
        spread=SpreadConfig(mode="fixed", points=100.0),  # 100 points * 0.01 = $1 -> $0.50 half-spread
        slippage=SlippageConfig(mode="fixed_points", points=50.0),  # 50 * 0.01 = $0.50
        commission=CommissionConfig(type="per_lot", value=5.0),
    )
    costly = run_simulation(df, costly_cfg, spec, Account(10000.0), window_index=0)[0]

    assert costly.entry_price > zero_cost.entry_price, "spread+slippage must make a BUY entry more expensive"
    assert costly.commission == pytest.approx(5.0)
    assert costly.net_pnl < zero_cost.net_pnl


def test_signal_bar_own_future_ohlc_does_not_change_the_entry_price():
    """Execution-timing check (Phase 13): the entry price is fixed by bar1's
    open the instant a signal fires at bar0 — changing bar0's OWN high/low
    (which could only be known once bar0 closes, i.e. after the decision)
    must not retroactively change what price the trade got filled at."""
    n = 5
    df_a = _bars(
        {"open": [100, 105, 105, 105, 105], "high": [100, 106, 105, 105, 105],
         "low": [100, 104, 105, 105, 105], "close": [100, 105, 105, 105, 105]},
        n, probability_at_0=0.9,
    )
    df_b = df_a.copy()
    df_b.loc[0, ["high", "low"]] = [999.0, -999.0]  # bar0's own range changed; must not affect entry
    cfg = _zero_cost_cfg()
    trades_a = run_simulation(df_a, cfg, spec, Account(10000.0), window_index=0)
    trades_b = run_simulation(df_b, cfg, spec, Account(10000.0), window_index=0)
    assert trades_a[0].entry_price == trades_b[0].entry_price == pytest.approx(105.0)
