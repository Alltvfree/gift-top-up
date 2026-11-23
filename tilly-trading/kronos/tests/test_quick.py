"""Quick-ticket backtest strategies (setups/quick.py): the side follows the hourly trend, stop geometry, sessions, no lookahead."""
import numpy as np
import pandas as pd
import pytest

from backtest.compare_setups import compare
from backtest.config import load_config
from backtest.symbols import get_symbol_spec
from conftest import make_synthetic_ohlc
from setups.quick import quick_counter, quick_random, quick_signals, quick_trend, QuickParams

POINT = 0.01


def trending(n=4000, step=0.02, spread=24.0):
    """A steady climb (or fall, with a negative step) in one-minute bars, starting at midnight UTC."""
    t = pd.date_range("2024-01-02 00:00", periods=n, freq="1min", tz="UTC")
    c = 2000.0 + np.arange(n) * step
    return pd.DataFrame({"time": t, "open": c - step / 2, "high": c + 0.4, "low": c - 0.4, "close": c, "tick_volume": 100, "spread": spread})


def test_trend_mode_buys_in_an_uptrend_and_counter_sells_and_only_inside_the_session():
    up = trending()
    tr, ct = quick_trend(up, POINT), quick_counter(up, POINT)
    assert tr["setup_buy"].sum() > 100 and not tr["setup_sell"].any()
    assert ct["setup_sell"].sum() == tr["setup_buy"].sum() and not ct["setup_buy"].any()
    hours = pd.DatetimeIndex(up["time"]).hour
    fired = tr["setup_buy"] | tr["setup_sell"]
    assert ((hours[fired.to_numpy()] >= 7) & (hours[fired.to_numpy()] < 20)).all()
    assert quick_trend(trending(step=-0.02), POINT)["setup_sell"].sum() > 100


def test_stop_is_at_least_six_spreads_and_target_is_twice_the_stop():
    out = quick_trend(trending(), POINT)
    fired = out["setup_buy"]
    assert (out.loc[fired, "signal_sl_distance"] >= 6 * 24 * POINT - 1e-9).all()
    assert np.allclose(out.loc[fired, "signal_tp_distance"], 2 * out.loc[fired, "signal_sl_distance"])


def test_random_mode_uses_both_sides_and_is_repeatable():
    df = trending()
    a, b = quick_random(df, POINT), quick_random(df, POINT)
    assert a["setup_buy"].sum() > 100 and a["setup_sell"].sum() > 100
    assert (a["setup_buy"] == b["setup_buy"]).all()
    assert (quick_signals(df, POINT, QuickParams(mode="random", seed=1))["setup_buy"] != a["setup_buy"]).any()


def test_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        quick_signals(trending(500), POINT, QuickParams(mode="best"))


@pytest.mark.parametrize("fn", [quick_trend, quick_counter, quick_random])
def test_no_lookahead(fn):
    df = make_synthetic_ohlc(5000, freq="1min", start_time="2024-01-02 00:00", seed=5)
    full, cut = fn(df, POINT), fn(df.iloc[:3500].reset_index(drop=True), POINT)
    for col in ("setup_buy", "setup_sell"):
        assert (full[col].iloc[:3500].to_numpy() == cut[col].to_numpy()).all(), col


def test_compare_runs_the_three_quick_setups_on_one_minute_data():
    cfg, spec = load_config("config/setup_xauusd_m1.toml"), get_symbol_spec("XAUUSDm")
    assert cfg.timeframe == "M1" and cfg.risk.max_trades_per_day == 0
    df = make_synthetic_ohlc(9000, freq="1min", start_time="2024-01-02 00:00", seed=8)
    table = compare(df, None, cfg, spec, min_trades=500, n_null=0, only=["quick_trend", "quick_counter", "quick_random"])
    assert list(table["setup"]) == ["quick_trend", "quick_counter", "quick_random"] and (table["trades"] > 10).all()


def test_fifteen_spread_variants_have_wider_stops_and_the_slow_config_holds_five_bars():
    from setups.quick import quick15_trend
    df = trending()
    wide, narrow = quick15_trend(df, POINT), quick_trend(df, POINT)
    fired = wide["setup_buy"]
    assert (wide.loc[fired, "signal_sl_distance"] >= 15 * 24 * POINT - 1e-9).all()
    assert wide.loc[fired, "signal_sl_distance"].mean() > narrow.loc[narrow["setup_buy"], "signal_sl_distance"].mean()
    cfg = load_config("config/setup_xauusd_m1_slow.toml")
    assert cfg.execution.max_holding_bars == 5 and cfg.signal.cooldown_bars == 10
