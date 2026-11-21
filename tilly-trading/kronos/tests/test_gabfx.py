"""GABFX ebook setup (setups/gabfx.py): zone rule, storyline, entry, mirror, no lookahead."""
import numpy as np
import pandas as pd
import pytest

from backtest.compare_setups import compare
from backtest.config import load_config
from backtest.symbols import get_symbol_spec
from conftest import make_synthetic_ohlc
from setups.gabfx import (GabfxParams, gabfx_snr2, gabfx_snr3, signals_from_context, storyline_and_zones,
                          two_candle_zones)


def arr(*rows):
    a = np.array(rows, float)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]   # o, h, l, c


def test_support_zone_is_bear_then_bull_and_resistance_is_bull_then_bear():
    o, h, l, c = arr((10, 10.5, 8, 8.5),     # bear
                     (8.5, 11, 8.2, 10.5),   # bull  -> support
                     (10.5, 12, 10.4, 11.8), # bull
                     (11.8, 12.5, 10, 10.5)) # bear -> resistance
    s_lo, s_hi, r_lo, r_hi = two_candle_zones(o, h, l, c)
    assert s_lo[1] == 8 and s_hi[1] == 8.5
    assert np.isnan(s_lo[2]) and np.isnan(r_lo[1])
    assert r_lo[3] == 11.8 and r_hi[3] == 12.5


def test_storyline_turns_bullish_only_on_a_close_above_resistance():
    # resistance zone forms at bar 2 (bull, bear); bar 3 wicks above but closes inside; bar 4 closes above
    o, h, l, c = arr((10, 11, 9.8, 10.9), (10.9, 12, 10.8, 11.9), (11.9, 12.5, 11, 11.2),
                     (11.2, 13, 11.1, 12.0), (12.0, 13.5, 11.9, 13.2))
    state, _, res = storyline_and_zones(o, h, l, c, max_age=30)
    assert state[3] == 0 and state[4] == 1


def _frame(n=60):
    t = pd.date_range("2024-01-03 00:00", periods=n, freq="1h", tz="UTC")
    c = np.full(n, 110.0)
    return pd.DataFrame({"time": t, "open": c, "high": c + 2.0, "low": c - 2.0, "close": c, "spread": 20.0})


def _ctx(n, d_state=1.0, w_state=0.0, support=(100.0, 102.0), resistance=(np.nan, np.nan)):
    full = lambda v: np.full(n, v)
    return {"d_state": full(d_state), "w_state": full(w_state), "ds_lo": full(support[0]), "ds_hi": full(support[1]),
            "dr_lo": full(resistance[0]), "dr_hi": full(resistance[1])}


def _buy_setup():
    df = _frame()
    df.loc[48, ["open", "high", "low", "close"]] = [103.0, 103.2, 100.5, 101.0]   # bear, wick into the daily zone
    df.loc[49, ["open", "high", "low", "close"]] = [101.0, 104.2, 100.8, 104.0]   # bull: new support forms there
    return df


def test_buy_when_storyline_up_and_new_support_forms_in_a_daily_zone():
    df = _buy_setup()
    out = signals_from_context(df, _ctx(len(df)), GabfxParams())
    assert out["setup_buy"].iloc[49] and out["setup_buy"].sum() == 1 and not out["setup_sell"].any()
    assert out["signal_sl_distance"].iloc[49] > 0
    assert out["signal_tp_distance"].iloc[49] == pytest.approx(2.0 * out["signal_sl_distance"].iloc[49])


@pytest.mark.parametrize("d_state,w_state", [(0.0, 0.0), (-1.0, 0.0), (1.0, -1.0)])
def test_no_trade_without_storyline_or_when_weekly_conflicts(d_state, w_state):
    df = _buy_setup()
    out = signals_from_context(df, _ctx(len(df), d_state=d_state, w_state=w_state), GabfxParams())
    assert not out["setup_buy"].any()


def test_weekly_gate_can_be_turned_off():
    df = _buy_setup()
    out = signals_from_context(df, _ctx(len(df), w_state=-1.0), GabfxParams(use_weekly_gate=False))
    assert out["setup_buy"].iloc[49]


def test_new_support_outside_the_daily_zone_does_not_trigger():
    df = _buy_setup()
    out = signals_from_context(df, _ctx(len(df), support=(80.0, 82.0)), GabfxParams())
    assert not out["setup_buy"].any()


def test_mirror_sell():
    df = _frame()
    df.loc[48, ["open", "high", "low", "close"]] = [117.0, 119.5, 116.8, 119.0]   # bull, wick into the daily resistance
    df.loc[49, ["open", "high", "low", "close"]] = [119.0, 119.2, 115.8, 116.0]   # bear: new resistance
    ctx = _ctx(len(df), d_state=-1.0, support=(np.nan, np.nan), resistance=(118.0, 120.0))
    out = signals_from_context(df, ctx, GabfxParams())
    assert out["setup_sell"].iloc[49] and not out["setup_buy"].any()


def test_three_confirmations_wait_for_breakout_and_a_holding_pullback():
    df = _buy_setup()
    level = df["high"].iloc[43:50].max()                      # the swing level the breakout must clear
    df.loc[50, ["open", "high", "low", "close"]] = [104.0, level + 3, 103.5, level + 2]       # closes above: breakout
    df.loc[51, ["open", "high", "low", "close"]] = [level + 2, level + 2.5, level - 0.1, level + 1]  # pulls back, holds the level
    out = signals_from_context(df, _ctx(len(df)), GabfxParams(confirmations=3))
    assert not out["setup_buy"].iloc[49] and out["setup_buy"].iloc[51]


def test_three_confirmations_without_a_breakout_never_fire():
    out = signals_from_context(_buy_setup(), _ctx(60), GabfxParams(confirmations=3))
    assert not out["setup_buy"].any()


@pytest.mark.parametrize("fn", [gabfx_snr2, gabfx_snr3])
def test_no_lookahead_on_real_pipeline(fn):
    df = make_synthetic_ohlc(2500, freq="1h", start_time="2023-01-01", seed=9)
    full = fn(df, 0.01)
    cut = fn(df.iloc[:1800].reset_index(drop=True), 0.01)
    for col in ("setup_buy", "setup_sell"):
        assert (full[col].iloc[:1800].to_numpy() == cut[col].to_numpy()).all(), col


@pytest.mark.parametrize("fn", [gabfx_snr2, gabfx_snr3])
def test_output_contract_and_naive_timestamps(fn):
    df = make_synthetic_ohlc(1500, freq="1h", seed=4)
    df["time"] = df["time"].dt.tz_localize(None)       # a feed without timezone info must work too
    out = fn(df, 0.01)
    fired = out["setup_buy"] | out["setup_sell"]
    assert not (out["setup_buy"] & out["setup_sell"]).any()
    assert (out.loc[fired, "signal_sl_distance"] > 0).all() and out.loc[~fired, "signal_sl_distance"].isna().all()


def test_compare_only_runs_just_the_named_setups():
    cfg, spec = load_config("config/setup_xauusd.toml"), get_symbol_spec("XAUUSDm")
    df = make_synthetic_ohlc(3000, freq="1h", seed=2)
    table = compare(df, None, cfg, spec, min_trades=500, n_null=1, only=["gabfx_snr2", "gabfx_snr3"])
    assert list(table["setup"]) == ["gabfx_snr2", "gabfx_snr3"]
