"""Trend-pullback setup rules (setups/trend_pullback.py): a hand-built market
where the answer is known, each do-not-trade filter, mirror symmetry, and the
no-lookahead guarantee on the real feature pipeline."""
import numpy as np
import pandas as pd
import pytest

from backtest.config import load_config
from conftest import make_synthetic_ohlc
from features import compute_features, merge_higher_timeframe
from setups.trend_pullback import TrendPullbackParams, generate_signals, load_setup_params

POINT = 0.01
ATR = 7.0
LAST_BAR_UTC = pd.Timestamp("2024-01-03 14:45", tz="UTC")  # Wednesday, inside the session


def crafted(atr=ATR, last_bar=LAST_BAR_UTC, spread=25.0, htf_bias=1, htf_dist=0.01):
    """120-bar steady uptrend, a 3-bar pullback that tags the EMA 20, then one
    strong bullish bar closing above the prior high — a textbook long."""
    closes = [1000.0 + i for i in range(120)]
    opens = [c - 0.8 for c in closes]
    highs = [c + 0.2 for c in closes]
    lows = [o - 0.2 for o in opens]
    last = closes[-1]
    for k in range(1, 4):
        c = last - 4.0 * k
        o = c + 2.5
        opens.append(o), closes.append(c), highs.append(o + 0.2), lows.append(c - 0.3)
    o, c = closes[-1] + 0.5, closes[-1] + 14.0
    opens.append(o), closes.append(c), highs.append(c + 0.3), lows.append(o - 0.3)

    n = len(closes)
    df = pd.DataFrame(
        {
            "time": pd.date_range(end=last_bar, periods=n, freq="15min"),
            "open": opens, "high": highs, "low": lows, "close": closes,
        }
    )
    df["atr_pct"] = atr / df["close"]
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    df["body_pct_of_range"] = ((df["close"] - df["open"]).abs() / rng).fillna(0.0)
    df["h1_structure_bias"] = htf_bias
    df["h1_dist_from_ema_50_pct"] = htf_dist
    df["spread"] = spread
    return df


def mirrored(df: pd.DataFrame, atr=ATR) -> pd.DataFrame:
    """The same market flipped upside-down: every rule must flip with it."""
    m = 2400.0
    out = df.copy()
    out["open"], out["close"] = m - df["open"], m - df["close"]
    out["high"], out["low"] = m - df["low"], m - df["high"]
    out["atr_pct"] = atr / out["close"]
    out["h1_structure_bias"] = -df["h1_structure_bias"]
    out["h1_dist_from_ema_50_pct"] = -df["h1_dist_from_ema_50_pct"]
    return out


def fired(sig: pd.DataFrame) -> pd.DataFrame:
    return sig[sig["setup_buy"] | sig["setup_sell"]]


def test_textbook_long_fires_once_with_structural_stop_and_2r_target():
    sig = generate_signals(crafted(), TrendPullbackParams(), POINT)
    hits = fired(sig)
    assert list(hits.index) == [len(sig) - 1] and bool(hits.iloc[0]["setup_buy"])
    pullback_low = crafted()["low"].iloc[-8:].min()
    expected_sl = hits.iloc[0]["close"] - (pullback_low - 0.25 * ATR)
    assert hits.iloc[0]["signal_sl_distance"] == pytest.approx(expected_sl)
    assert hits.iloc[0]["signal_tp_distance"] == pytest.approx(2.0 * expected_sl)
    assert hits.iloc[0]["predicted_probability_buy"] == 1.0 and hits.iloc[0]["predicted_probability_sell"] == 0.0
    assert sig["predicted_probability_buy"].notna().all() and sig["predicted_probability_sell"].notna().all()


def test_mirrored_market_gives_the_mirrored_short():
    sig = generate_signals(mirrored(crafted()), TrendPullbackParams(), POINT)
    hits = fired(sig)
    assert list(hits.index) == [len(sig) - 1] and bool(hits.iloc[0]["setup_sell"])
    long_sig = fired(generate_signals(crafted(), TrendPullbackParams(), POINT)).iloc[0]
    assert hits.iloc[0]["signal_sl_distance"] == pytest.approx(long_sig["signal_sl_distance"])
    assert hits.iloc[0]["signal_tp_distance"] == pytest.approx(long_sig["signal_tp_distance"])


@pytest.mark.parametrize(
    "label, build",
    [
        ("htf structure bearish", lambda: crafted(htf_bias=-1)),
        ("htf structure neutral", lambda: crafted(htf_bias=0)),
        ("htf price below its EMA 50", lambda: crafted(htf_dist=-0.01)),
        ("outside the session (03:00 UTC)", lambda: crafted(last_bar=pd.Timestamp("2024-01-03 03:00", tz="UTC"))),
        ("after the session (20:00 UTC)", lambda: crafted(last_bar=pd.Timestamp("2024-01-03 20:00", tz="UTC"))),
        ("Friday late (19:15 UTC)", lambda: crafted(last_bar=pd.Timestamp("2024-01-05 19:15", tz="UTC"))),
        ("spread too wide", lambda: crafted(spread=400.0)),
        ("stop wider than max_sl_atr", lambda: crafted(atr=5.0)),
        ("stop tighter than min_sl_atr", lambda: crafted(atr=40.0)),
    ],
)
def test_each_do_not_trade_condition_blocks_the_setup(label, build):
    assert fired(generate_signals(build(), TrendPullbackParams(), POINT)).empty, label


def test_no_confirmation_candle_means_no_entry():
    df = crafted()
    last = len(df) - 1
    df.loc[last, ["open", "close", "high", "low"]] = [1090.0, 1089.0, 1090.2, 1088.8]  # small bearish bar
    df["body_pct_of_range"] = ((df["close"] - df["open"]).abs() / (df["high"] - df["low"])).fillna(0.0)
    assert fired(generate_signals(df, TrendPullbackParams(), POINT)).empty


def test_a_breakout_without_a_pullback_to_the_ema_is_not_a_setup():
    """Same strong confirmation bar, but price drifted sideways well above
    the EMA 20 instead of pulling back to it. ATR is widened so the stop
    would be valid either way — the ONLY difference between the two frames
    is whether a bar in the window tagged the EMA 20."""
    df = crafted(atr=9.0)
    for i, (o, c) in zip(range(120, 123), [(1119.0, 1119.5), (1119.5, 1120.0), (1120.0, 1120.5)]):
        df.loc[i, ["open", "close", "high", "low"]] = [o, c, c + 0.5, o - 1.5]
    df.loc[123, ["open", "close", "high", "low"]] = [1120.8, 1128.0, 1128.3, 1120.5]
    df["body_pct_of_range"] = ((df["close"] - df["open"]).abs() / (df["high"] - df["low"])).fillna(0.0)
    df["atr_pct"] = 9.0 / df["close"]

    assert fired(generate_signals(df, TrendPullbackParams(), POINT)).empty

    ema20 = df["close"].ewm(span=20, adjust=False).mean()
    tagged = df.copy()
    tagged.loc[121, "low"] = ema20.iloc[121] - 0.5   # one wick that reaches the EMA 20
    hits = fired(generate_signals(tagged, TrendPullbackParams(), POINT))
    assert list(hits.index) == [123] and bool(hits.iloc[0]["setup_buy"])


def test_missing_higher_timeframe_columns_fail_loudly():
    with pytest.raises(ValueError, match="higher timeframe"):
        generate_signals(crafted().drop(columns=["h1_structure_bias"]), TrendPullbackParams(), POINT)


def test_param_validation():
    for bad in ({"rr": 0}, {"min_sl_atr": 3.0, "max_sl_atr": 2.0}, {"ema_fast": 50, "ema_slow": 20},
                {"pullback_bars": 0}, {"session_start_utc": 20, "session_end_utc": 7}):
        with pytest.raises(ValueError):
            TrendPullbackParams(**bad)


def test_signals_use_only_data_up_to_each_bar():
    """The no-lookahead guarantee on the REAL pipeline (features + higher-
    timeframe merge): signals for the first k bars must be identical whether
    or not the bars after k exist."""
    base = make_synthetic_ohlc(5000, freq="15min", start_price=4000.0, seed=11, spread_points=25.0)
    higher = (
        base.set_index("time")
        .resample("1h")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "tick_volume": "sum", "spread": "max"})
        .dropna()
        .reset_index()
    )

    def run(b, h):
        merged = merge_higher_timeframe(compute_features(b), compute_features(h), prefix="h1")
        return generate_signals(merged.reset_index(drop=True), TrendPullbackParams(), POINT)

    full = run(base, higher)
    k = 3500
    cut_time = base["time"].iloc[k]
    truncated = run(base.iloc[:k].reset_index(drop=True), higher[higher["time"] < cut_time].reset_index(drop=True))

    cols = ["setup_buy", "setup_sell", "signal_sl_distance", "signal_tp_distance"]
    assert int(full.iloc[:k]["setup_buy"].sum() + full.iloc[:k]["setup_sell"].sum()) > 5, "test needs real signals to compare"
    pd.testing.assert_frame_equal(full.iloc[:k][cols].reset_index(drop=True), truncated[cols].reset_index(drop=True))


def test_load_setup_params_from_toml(tmp_path):
    good = tmp_path / "s.toml"
    good.write_text("[setup]\nrr = 3.0\npullback_bars = 5\n")
    p = load_setup_params(good)
    assert (p.rr, p.pullback_bars, p.ema_slow) == (3.0, 5, 50)
    assert load_setup_params(None) == TrendPullbackParams()

    bad = tmp_path / "bad.toml"
    bad.write_text("[setup]\nrr = 2.0\nmystery = 1\n")
    with pytest.raises(ValueError, match="mystery"):
        load_setup_params(bad)


def test_shipped_xauusd_config_loads_in_both_loaders():
    path = "config/setup_xauusd.toml"
    cfg = load_config(path)
    assert (cfg.symbol, cfg.timeframe, cfg.higher_timeframe) == ("XAUUSDm", "M15", "H1")
    assert cfg.risk.max_trades_per_day == 3 and cfg.risk.max_daily_loss_percent == 3.0
    assert load_setup_params(path).rr == 2.0
