"""No-lookahead checks for features.py, against synthetic OHLC data.

Previously these lived only as an ad-hoc scratch script during development
and were never committed — porting them here so `pytest` from kronos/
actually proves what README.md claims about this file.
"""
import numpy as np
import pandas as pd

from conftest import make_synthetic_ohlc
from features import FEATURE_COLUMNS, compute_features, merge_higher_timeframe


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
