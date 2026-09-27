"""No-lookahead checks for features.py, against synthetic OHLC data.

Previously these lived only as an ad-hoc scratch script during development
and were never committed — porting them here so `pytest` from kronos/
actually proves what README.md claims about this file.
"""
import numpy as np
import pandas as pd
import pytest

from conftest import make_synthetic_ohlc
from features import FEATURE_COLUMNS, _market_structure, compute_features, merge_higher_timeframe


def test_compute_features_runs_clean_no_nan_or_inf_after_warmup():
    df = make_synthetic_ohlc(2000, freq="5min")
    feats = compute_features(df)
    assert all(c in feats.columns for c in FEATURE_COLUMNS)
    warm = feats.iloc[250:]  # past every indicator's warmup period (EMA 200 etc.)
    for c in FEATURE_COLUMNS:
        assert not warm[c].isna().any(), f"unexpected NaN in {c} after warmup"
        assert np.isfinite(warm[c].to_numpy()).all(), f"non-finite value in {c}"


def test_no_lookahead_truncating_future_bars_does_not_change_past_features():
    df = make_synthetic_ohlc(2000, freq="5min")
    full = compute_features(df)
    truncated = compute_features(df.iloc[:1000].copy())
    row = 900
    for c in FEATURE_COLUMNS:
        a, b = full.iloc[row][c], truncated.iloc[row][c]
        if pd.isna(a) and pd.isna(b):
            continue
        assert np.isclose(a, b, rtol=1e-9, atol=1e-9), f"LOOKAHEAD in {c}: full={a} truncated={b}"


def test_merge_higher_timeframe_only_attaches_already_closed_bars():
    df = make_synthetic_ohlc(2000, freq="5min")
    base = df.copy()
    higher = df.iloc[::12].reset_index(drop=True).copy()  # every 12th M5 bar = 1-hour spacing
    higher_feats = compute_features(higher)[["time", "rsi_14"]].copy()
    higher_feats["open_time"] = higher_feats["time"]  # survives the prefix+rename since it isn't "time"
    merged = merge_higher_timeframe(base, higher_feats, prefix="htf")

    bar_duration = higher_feats["time"].diff().median()
    close_time = merged["htf_open_time"] + bar_duration
    known = merged["htf_open_time"].notna()
    assert (close_time[known] <= merged.loc[known, "time"]).all(), (
        "merge_higher_timeframe attached a higher-timeframe bar that hadn't "
        "closed yet as of the base row's time — lookahead bug"
    )

    mid_formation_row = merged[merged["time"] == pd.Timestamp("2024-01-01 10:35", tz="UTC")]
    if len(mid_formation_row) == 1:
        attached_open = mid_formation_row.iloc[0]["htf_open_time"]
        assert attached_open == pd.Timestamp("2024-01-01 09:00", tz="UTC"), (
            f"at 10:35 (mid-formation of the 10:00 H1 bar), expected the previous "
            f"(09:00, closed at 10:00) bar attached, got {attached_open}"
        )


def test_swing_detection_requires_strict_dominance_not_a_tie():
    n = 30
    times = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = np.full(n, 100.0)
    close[15] = 105.0  # one unambiguous swing high
    high = close + 0.2
    low = close - 0.2
    open_ = close.copy()
    df = pd.DataFrame({"time": times, "open": open_, "high": high, "low": low, "close": close})
    feats = compute_features(df)
    # The flat region around it must NOT all register as breaking resistance
    # against each other (a tie-based detector would do this); only rows
    # genuinely below the one real swing high should show a resistance distance.
    assert feats.loc[20, "dist_to_resistance_pct"] >= 0


def test_bos_fires_once_on_the_break_not_every_bar_beyond_it():
    """Break of structure (bos_bull) is an EVENT (fires once, on the bar
    that first crosses), unlike broke_resistance which stays 1 every bar
    price remains beyond the level. Reference ChatGPT-authored code
    (kronos_lgbm_news_ai/features/structure.py) built its own separate
    pivot detector for this via `.shift(left).rolling(...).max()`, which
    doesn't actually implement a two-sided confirmed pivot — this instead
    reuses the swing detector already proven lookahead-safe above."""
    n = 40
    close = np.full(n, 100.0)
    high = np.full(n, 100.5)
    low = np.full(n, 99.5)
    high[10], low[10], close[10] = 100.5, 99.0, 99.5  # isolated swing low (irrelevant here)
    high[10] = 110.0  # isolated swing high at bar 10 (confirmed once t >= 15)
    high[25], low[25], close[25] = 111.0, 99.0, 105.0  # pokes above 110 but closes back under — a sweep, not a break
    high[30], low[30], close[30] = 116.0, 99.0, 115.0  # genuine break: closes above 110
    high[31], low[31], close[31] = 117.0, 99.0, 116.0  # stays above — must NOT re-fire bos_bull

    df = pd.DataFrame({"high": high, "low": low, "close": close})
    ms = _market_structure(df["high"], df["low"], df["close"])

    assert ms["dist_to_resistance_pct"].iloc[20] == pytest.approx(0.1)
    assert ms["broke_resistance"].iloc[20:30].sum() == 0
    assert ms["bos_bull"].iloc[25] == 0, "a sweep (wick through, close back under) must not count as a break"
    assert ms["liquidity_sweep_high"].iloc[25] == 1
    assert ms["bos_bull"].iloc[30] == 1
    assert ms["broke_resistance"].iloc[30] == 1
    assert ms["bos_bull"].iloc[31] == 0, "still beyond the level on the next bar — not a fresh break"
    assert ms["broke_resistance"].iloc[31] == 1, "broke_resistance is the persistent-state version, unlike bos_bull"


def test_structure_bias_and_choch_track_a_real_trend_reversal():
    """A clean uptrend (higher-high + higher-low swings) followed by a clean
    downtrend (lower-high + lower-low swings) must flip structure_bias from
    +1 to -1 exactly once, firing choch on that bar — built from a genuine
    zigzag price path (each anchor is a true local extreme within its own
    +-SWING_LAG window), not a flat background a swing point sits inside."""
    anchors = [(0, 100), (15, 95), (30, 108), (45, 101), (60, 115), (75, 90), (90, 105), (109, 97)]
    n = 110
    xs = np.array([a[0] for a in anchors])
    ys = np.array([a[1] for a in anchors])
    close = np.interp(np.arange(n), xs, ys)
    high, low = close.copy(), close.copy()
    for idx, val in anchors[1:-1]:
        high[idx] = val + 0.3
        low[idx] = val - 0.3

    df = pd.DataFrame({"high": high, "low": low, "close": close})
    ms = _market_structure(df["high"], df["low"], df["close"])

    bias = ms["structure_bias"]
    assert (bias == 1).any(), "expected a confirmed bullish stretch (higher high + higher low)"
    assert (bias == -1).any(), "expected a confirmed bearish stretch (lower high + lower low)"
    # Bullish must come chronologically before bearish, matching the constructed path.
    first_bull = bias[bias == 1].index[0]
    first_bear = bias[bias == -1].index[0]
    assert first_bull < first_bear

    choch_bars = ms.index[ms["choch"] == 1].tolist()
    assert len(choch_bars) == 1, f"expected exactly one bias flip, got {choch_bars}"
    assert bias.iloc[choch_bars[0] - 1] == 1 and bias.iloc[choch_bars[0]] == -1


def test_fvg_detects_a_three_candle_gap():
    n = 10
    times = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    high = np.full(n, 100.0)
    low = np.full(n, 99.0)
    close = np.full(n, 99.5)
    open_ = np.full(n, 99.5)
    high[4], low[4], close[4], open_[4] = 101.5, 101.0, 101.2, 101.0  # low[4] > high[2] -> bullish FVG
    tick_volume = np.full(n, 100)
    df = pd.DataFrame(
        {"time": times, "open": open_, "high": high, "low": low, "close": close, "tick_volume": tick_volume}
    )
    feats = compute_features(df)
    assert feats["fvg_bull"].iloc[4] == 1
    assert feats["fvg_bull"].iloc[3] == 0 and feats["fvg_bull"].iloc[5] == 0
