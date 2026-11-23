"""Hummingbot-derived strategies (setups/hummingbot.py): the three signal rules, the Supertrend, no lookahead."""
import numpy as np
import pandas as pd
import pytest

from backtest.compare_setups import compare
from backtest.config import load_config
from backtest.symbols import get_symbol_spec
from conftest import make_synthetic_ohlc
from setups.hummingbot import (HbParams, bbp, hb_bollinger, hb_macd_bb, hb_supertrend, macd_bb_conditions, macd_parts,
                               supertrend)

POINT = 0.01


def frame(close, rng=0.5):
    c = np.asarray(close, float)
    t = pd.date_range("2024-01-01", periods=len(c), freq="1h", tz="UTC")
    return pd.DataFrame({"time": t, "open": c, "high": c + rng, "low": c - rng, "close": c, "spread": 20.0})


def test_percent_b_is_zero_at_the_lower_band_and_one_at_the_upper_band():
    c = pd.Series(np.r_[np.full(99, 100.0), 100.0])
    assert bbp(c, 100, 2.0).isna().iloc[:99].all()
    wiggle = pd.Series(100 + np.sin(np.arange(200)))
    mid, sd = wiggle.rolling(100).mean(), wiggle.rolling(100).std(ddof=0)
    assert bbp(wiggle, 100, 2.0).iloc[-1] == pytest.approx((wiggle.iloc[-1] - (mid - 2 * sd).iloc[-1]) / (4 * sd.iloc[-1]))


def test_bollinger_buys_a_plunge_below_the_lower_band_and_sells_a_spike_above_the_upper():
    calm = 100 + np.sin(np.arange(200) / 3.0)
    down, up = frame(np.r_[calm, 70.0]), frame(np.r_[calm, 130.0])
    assert hb_bollinger(down, POINT)["setup_buy"].iloc[-1] and not hb_bollinger(down, POINT)["setup_sell"].iloc[-1]
    assert hb_bollinger(up, POINT)["setup_sell"].iloc[-1] and not hb_bollinger(up, POINT)["setup_buy"].iloc[-1]
    assert not hb_bollinger(frame(calm), POINT)["setup_buy"].iloc[-1]


def test_macd_bb_needs_all_three_conditions_for_each_side():
    p = HbParams()
    b = pd.Series([-0.1, -0.1, 0.5, 1.2, 1.2])
    macd = pd.Series([-1.0, -1.0, -1.0, 1.0, 1.0])
    hist = pd.Series([0.5, -0.5, 0.5, -0.5, 0.5])
    buy, sell = macd_bb_conditions(b, macd, hist, p)
    assert buy.tolist() == [True, False, False, False, False]      # stretch down + hist turning up + MACD still negative
    assert sell.tolist() == [False, False, False, True, False]     # stretch up + hist turning down + MACD still positive


def test_macd_parts_are_the_standard_definition():
    c = pd.Series(100 + np.cumsum(np.sin(np.arange(120) / 5.0)))
    macd, hist = macd_parts(c, 21, 42, 9)
    fast, slow = c.ewm(span=21, adjust=False).mean(), c.ewm(span=42, adjust=False).mean()
    assert np.allclose(macd, fast - slow) and np.allclose(hist, macd - macd.ewm(span=9, adjust=False).mean())


def test_supertrend_follows_an_uptrend_then_flips_down_after_a_collapse():
    c = np.r_[np.linspace(100, 200, 120), np.linspace(200, 100, 120)]
    line, direction = supertrend(frame(c, rng=0.3), 20, 4.0)
    assert direction[100] == 1 and line[100] < c[100]                # up-trend: the line sits below price
    assert direction[-1] == -1 and line[-1] > c[-1]                  # after the collapse: above price
    assert (np.diff(line[~np.isnan(line)][5:60]) >= -1e-9).all()     # an up-trend line never moves down


def test_supertrend_signals_only_near_the_line_and_in_the_trend_direction():
    c = np.r_[np.linspace(100, 110, 120), np.linspace(110, 100, 120)]          # gentle: the line stays within 1% of price
    df = frame(c, rng=0.02)
    out = hb_supertrend(df, POINT)
    _, direction = supertrend(df, 20, 4.0)
    assert out["setup_buy"].sum() > 20 and out["setup_sell"].sum() > 20
    assert (direction[out["setup_buy"].to_numpy()] == 1).all() and (direction[out["setup_sell"].to_numpy()] == -1).all()
    loose = hb_supertrend(df, POINT, HbParams(st_threshold=1e-9))
    assert (loose["setup_buy"] | loose["setup_sell"]).sum() < (out["setup_buy"] | out["setup_sell"]).sum()
    steep = hb_supertrend(frame(np.r_[np.linspace(100, 200, 120)], rng=0.3), POINT)    # line ~4 ATRs (>1%) away: stays quiet
    assert steep["setup_buy"].sum() < 10


@pytest.mark.parametrize("fn", [hb_bollinger, hb_macd_bb, hb_supertrend])
def test_exits_are_atr_based_in_every_one_and_there_is_no_lookahead(fn):
    df = make_synthetic_ohlc(3000, freq="1h", start_time="2023-01-01", seed=13)
    full, cut = fn(df, POINT), fn(df.iloc[:2000].reset_index(drop=True), POINT)
    for col in ("setup_buy", "setup_sell"):
        assert (full[col].iloc[:2000].to_numpy() == cut[col].to_numpy()).all(), col
    fired = full["setup_buy"] | full["setup_sell"]
    assert (full.loc[fired, "signal_sl_distance"] > 0).all() and np.allclose(full.loc[fired, "signal_tp_distance"], 2 * full.loc[fired, "signal_sl_distance"])
    assert not (full["setup_buy"] & full["setup_sell"]).any()


def test_compare_runs_them_on_a_btc_config():
    cfg, spec = load_config("config/setup_btcusd_h1.toml"), get_symbol_spec("BTCUSDm")
    assert cfg.symbol == "BTCUSDm" and cfg.timeframe == "H1"
    df = make_synthetic_ohlc(6000, freq="1h", start_time="2023-01-01", start_price=65000.0, seed=3, spread_points=600.0)
    table = compare(df, None, cfg, spec, min_trades=500, n_null=0, only=["hb_bollinger", "hb_macd_bb", "hb_supertrend"])
    assert list(table["setup"]) == ["hb_bollinger", "hb_macd_bb", "hb_supertrend"]
