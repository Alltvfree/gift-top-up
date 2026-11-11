"""setups/library.py: crafted markets where the answer is known, no-lookahead,
mirror symmetry, and the compare runner end to end on synthetic data."""
import numpy as np
import pandas as pd
import pytest

from backtest.compare_setups import compare, shifted_null
from backtest.config import load_config
from backtest.symbols import get_symbol_spec
from conftest import make_synthetic_ohlc
from setups.library import STRATEGIES, confluence, dtc_ribbon, mayfair_rsi, smc_sweep

POINT = 0.01


def frame(n=400, seed=1, freq="15min"):
    return make_synthetic_ohlc(n, freq=freq, start_time="2024-01-01 00:00", seed=seed)


def test_mayfair_buys_oversold_bull_candle_after_bear_candle():
    df = frame(120)
    # steady selloff, then a bullish candle
    close = 3000 - np.arange(120) * 3.0
    df["open"], df["close"] = close + 1.5, close
    df["high"], df["low"] = close + 2.0, close - 2.0
    df.loc[119, ["open", "close", "high", "low"]] = [close[118] - 1, close[118] + 4, close[118] + 5, close[118] - 2]
    out = mayfair_rsi(df, POINT)
    assert out["setup_buy"].iloc[-1] and not out["setup_sell"].iloc[-1]
    assert out["signal_sl_distance"].iloc[-1] == 6.0 and out["signal_tp_distance"].iloc[-1] == 18.0


def test_dtc_fires_once_when_ribbon_first_stacks():
    df = frame(300)
    close = np.concatenate([np.full(150, 2000.0), 2000 + np.arange(150) * 2.0])
    df["close"] = close
    df["open"], df["high"], df["low"] = close - 0.5, close + 1.0, close - 1.0
    out = dtc_ribbon(df, POINT)
    assert out["setup_buy"].sum() == 1 and out["setup_sell"].sum() == 0
    i = out.index[out["setup_buy"]][0]
    assert out["signal_sl_distance"][i] == pytest.approx(close[i] * 0.0025)


def test_smc_sells_after_sweeping_a_swing_high_and_closing_back_under():
    t = pd.date_range("2024-01-03 08:00", periods=40, freq="15min", tz="UTC")  # in session
    n = len(t)
    close = np.full(n, 2000.0)
    high, low = close + 4.0, close - 4.0      # realistic ~8 ATR
    high[10] = 2010.0                         # a swing high, confirmed by lower neighbours
    close[30] = 2006.0                        # upper half of the range (premium)
    high[30] = 2013.0                         # pierces 2010 ...
    df = pd.DataFrame({"time": t, "open": close, "high": high, "low": low, "close": close, "spread": 20.0})
    p = __import__("setups.library", fromlist=["SmcSweepParams"]).SmcSweepParams(range_bars=20, use_asia=False, use_prev_day=False)
    out = smc_sweep(df, POINT, p)
    assert out["setup_sell"].iloc[30] and not out["setup_buy"].iloc[30]   # ... and closed back under 2010
    assert out["setup_sell"].sum() == 1
    assert out["signal_sl_distance"].iloc[30] > 0


def test_smc_does_not_sell_when_price_closes_beyond_the_level():
    t = pd.date_range("2024-01-03 08:00", periods=40, freq="15min", tz="UTC")
    close = np.full(40, 2000.0)
    high, low = close + 4.0, close - 4.0
    high[10] = 2010.0
    close[30], high[30] = 2012.0, 2013.0       # a real breakout: closes above the level
    df = pd.DataFrame({"time": t, "open": close, "high": high, "low": low, "close": close, "spread": 20.0})
    from setups.library import SmcSweepParams
    out = smc_sweep(df, POINT, SmcSweepParams(range_bars=20, use_asia=False, use_prev_day=False))
    assert not out["setup_sell"].iloc[30]


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_no_lookahead_signals_unchanged_by_future_bars(name):
    df = frame(700, seed=7)
    fn = STRATEGIES[name]
    full = fn(df, POINT)
    cut = fn(df.iloc[:500].reset_index(drop=True), POINT)
    for c in ["setup_buy", "setup_sell"]:
        assert (full[c].iloc[:500].to_numpy() == cut[c].to_numpy()).all(), f"{name}.{c} changed when future bars were removed"


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_output_contract(name):
    out = STRATEGIES[name](frame(500, seed=3), POINT)
    for c in ["setup_buy", "setup_sell", "signal_sl_distance", "signal_tp_distance", "predicted_probability_buy", "predicted_probability_sell"]:
        assert c in out.columns
    assert not (out["setup_buy"] & out["setup_sell"]).any()
    fired = out["setup_buy"] | out["setup_sell"]
    assert (out.loc[fired, "signal_sl_distance"] > 0).all()
    assert out.loc[~fired, "signal_sl_distance"].isna().all()


def test_confluence_needs_agreement_and_blocks_conflict():
    idx = pd.RangeIndex(10)
    def mk(buy_at=(), sell_at=()):
        f = pd.DataFrame({"time": pd.date_range("2024-01-03", periods=10, freq="15min", tz="UTC"),
                          "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}, index=idx)
        f["setup_buy"], f["setup_sell"] = False, False
        for i in buy_at: f.loc[i, "setup_buy"] = True
        for i in sell_at: f.loc[i, "setup_sell"] = True
        f["signal_sl_distance"] = np.where(f["setup_buy"] | f["setup_sell"], 5.0, np.nan)
        f["signal_tp_distance"], f["predicted_probability_buy"], f["predicted_probability_sell"] = np.nan, 0.0, 0.0
        return f
    agree = confluence({"a": mk(buy_at=[3]), "b": mk(buy_at=[4])}, min_agree=2, window_bars=3)
    assert agree["setup_buy"].tolist() == [False] * 4 + [True] + [False] * 5   # fires on the bar completing agreement
    assert agree["signal_sl_distance"].iloc[4] == 5.0
    far = confluence({"a": mk(buy_at=[1]), "b": mk(buy_at=[8])}, min_agree=2, window_bars=3)
    assert not far["setup_buy"].any()
    conflict = confluence({"a": mk(buy_at=[3]), "b": mk(buy_at=[4]), "c": mk(sell_at=[4])}, min_agree=2, window_bars=3)
    assert not conflict["setup_buy"].any()


def test_shifted_null_preserves_count():
    f = mayfair_rsi(frame(600, seed=5), POINT)
    s = shifted_null(f, 123)
    assert s["setup_buy"].sum() == f["setup_buy"].sum() and s["setup_sell"].sum() == f["setup_sell"].sum()


def test_compare_runs_end_to_end_and_refuses_verdict_on_small_samples():
    cfg = load_config("config/setup_xauusd.toml")
    spec = get_symbol_spec("XAUUSDm")
    df = make_synthetic_ohlc(6000, freq="15min", start_time="2024-01-01", seed=11)
    table = compare(df, None, cfg, spec, min_trades=500, n_null=1)
    assert {"mayfair_rsi", "dtc_ribbon", "smc_sweep", "agree2(all)"} <= set(table["setup"])
    # a 6000-bar random walk can't clear 500 trades through the risk limits: no verdict may be issued
    assert not table["verdict"].isin(["POSITIVE EXPECTANCY SUPPORTED"]).any()
