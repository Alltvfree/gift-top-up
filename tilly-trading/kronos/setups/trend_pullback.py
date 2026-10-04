"""Trend + pullback + confirmation, with a structural stop and a fixed
risk:reward target. One simple setup, rules fixed up front — deliberately
NOT tuned against any backtest result (see README, "Rule-based setup").

LONG (SHORT is the exact mirror):
  1. Higher-timeframe trend is up: the H1 confirmed swings are a higher high
     AND higher low (structure_bias == +1), and H1 price is above its EMA 50.
  2. Base-timeframe trend is intact: close above EMA 50 and EMA 20 above
     EMA 50.
  3. Pullback: within the last `pullback_bars` bars, price tagged the base
     EMA 20 (a bar's low reached that bar's own EMA 20).
  4. Confirmation, on the signal bar itself: a bullish candle with a real
     body that closes back above EMA 20 AND above the previous bar's high —
     the pullback is over, buyers took control.
  5. Stop: just beyond the pullback's extreme (lowest low in the window,
     minus a `sl_buffer_atr` ATR buffer). If that stop is tighter than
     `min_sl_atr` ATR (noise would stop it out) or wider than `max_sl_atr`
     ATR (poor risk:reward, and a pullback that deep isn't a pullback), the
     setup is invalid and skipped. Target: `rr` times the stop distance.
  6. Do-not-trade conditions: outside the session window; Friday late
     (weekend-gap risk); ATR below `atr_ratio_min` or above `atr_ratio_max`
     times its own recent average (dead market / news spike); spread wider
     than `max_spread_atr_fraction` of ATR (cost would eat the trade).

Every input is a feature already computed lookahead-safe by
features.compute_features / merge_higher_timeframe, plus rolling windows
that only look backward — a signal on bar t uses data through bar t only.
The caller acts on it at bar t+1's open (backtest/simulator.py's default).
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class TrendPullbackParams:
    higher_prefix: str = "h1"
    require_htf_structure: bool = True
    ema_fast: int = 20
    ema_slow: int = 50
    pullback_bars: int = 8
    min_body_pct: float = 0.5
    sl_buffer_atr: float = 0.25
    min_sl_atr: float = 0.8
    max_sl_atr: float = 2.5
    rr: float = 2.0
    session_start_utc: int = 7
    session_end_utc: int = 20
    friday_cutoff_utc: int = 19
    atr_ratio_min: float = 0.6
    atr_ratio_max: float = 2.5
    atr_ratio_window: int = 100
    max_spread_atr_fraction: float = 0.15

    def __post_init__(self) -> None:
        if self.rr <= 0:
            raise ValueError("rr must be positive.")
        if not 0 < self.min_sl_atr < self.max_sl_atr:
            raise ValueError("Need 0 < min_sl_atr < max_sl_atr.")
        if self.pullback_bars < 1 or self.ema_fast >= self.ema_slow:
            raise ValueError("Need pullback_bars >= 1 and ema_fast < ema_slow.")
        if not 0 <= self.session_start_utc < self.session_end_utc <= 24:
            raise ValueError("Need 0 <= session_start_utc < session_end_utc <= 24.")


def load_setup_params(path: str | Path | None) -> TrendPullbackParams:
    """Reads the [setup] table of a TOML config (the same file the backtest
    config sections live in). Missing file/table -> the defaults above."""
    if path is None:
        return TrendPullbackParams()
    with open(path, "rb") as f:
        raw = (tomllib.load(f) or {}).get("setup", {})
    names = {f.name for f in fields(TrendPullbackParams)}
    unknown = set(raw) - names
    if unknown:
        raise ValueError(f"Unknown [setup] key(s) in {path}: {sorted(unknown)}")
    return TrendPullbackParams(**raw)


def generate_signals(df: pd.DataFrame, params: TrendPullbackParams, point: float) -> pd.DataFrame:
    """df: features.compute_features output merged with the higher
    timeframe's features (columns prefixed `params.higher_prefix`_) and,
    optionally, MT5's `spread` column (points). Returns a copy with:
      setup_buy / setup_sell       bool, a valid setup closed on this bar
      signal_sl_distance           price units from the signal close (NaN if none)
      signal_tp_distance           rr * signal_sl_distance (NaN if none)
      predicted_probability_buy/sell   1.0 / 0.0 — the same shape the
        dual-model simulator input uses, so run_simulation consumes it as is.
    """
    p = params
    bias_col = f"{p.higher_prefix}_structure_bias"
    dist_col = f"{p.higher_prefix}_dist_from_ema_50_pct"
    needed = {"time", "open", "high", "low", "close", "atr_pct", "body_pct_of_range", bias_col, dist_col}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(
            f"generate_signals needs compute_features output merged with the higher timeframe "
            f"(prefix {p.higher_prefix!r}); missing columns: {sorted(missing)}"
        )

    out = df.copy()
    close, high, low, open_ = out["close"], out["high"], out["low"], out["open"]
    ema_fast = close.ewm(span=p.ema_fast, adjust=False).mean()
    ema_slow = close.ewm(span=p.ema_slow, adjust=False).mean()
    atr = out["atr_pct"] * close

    htf_up = out[dist_col] > 0
    htf_down = out[dist_col] < 0
    if p.require_htf_structure:
        htf_up &= out[bias_col] == 1
        htf_down &= out[bias_col] == -1

    base_up = (close > ema_slow) & (ema_fast > ema_slow)
    base_down = (close < ema_slow) & (ema_fast < ema_slow)

    n = p.pullback_bars
    tagged_ema_from_above = (low <= ema_fast).astype(float).rolling(n).max() >= 1
    tagged_ema_from_below = (high >= ema_fast).astype(float).rolling(n).max() >= 1
    pullback_low = low.rolling(n).min()
    pullback_high = high.rolling(n).max()

    body_ok = out["body_pct_of_range"] >= p.min_body_pct
    confirm_long = (close > open_) & (close > ema_fast) & (close > high.shift(1)) & body_ok
    confirm_short = (close < open_) & (close < ema_fast) & (close < low.shift(1)) & body_ok

    sl_long = close - (pullback_low - p.sl_buffer_atr * atr)
    sl_short = (pullback_high + p.sl_buffer_atr * atr) - close
    valid_long = (sl_long >= p.min_sl_atr * atr) & (sl_long <= p.max_sl_atr * atr)
    valid_short = (sl_short >= p.min_sl_atr * atr) & (sl_short <= p.max_sl_atr * atr)

    hours, weekday = out["time"].dt.hour, out["time"].dt.dayofweek
    in_session = (hours >= p.session_start_utc) & (hours < p.session_end_utc)
    friday_late = (weekday == 4) & (hours >= p.friday_cutoff_utc)
    atr_ratio = atr / atr.rolling(p.atr_ratio_window).mean()
    atr_ok = (atr_ratio >= p.atr_ratio_min) & (atr_ratio <= p.atr_ratio_max)
    tradeable = in_session & ~friday_late & atr_ok
    if "spread" in out.columns:
        tradeable &= (out["spread"] * point).fillna(np.inf) <= p.max_spread_atr_fraction * atr

    buy = htf_up & base_up & tagged_ema_from_above & confirm_long & valid_long & tradeable
    sell = htf_down & base_down & tagged_ema_from_below & confirm_short & valid_short & tradeable

    sl_distance = pd.Series(np.nan, index=out.index)
    sl_distance[buy] = sl_long[buy]
    sl_distance[sell] = sl_short[sell]

    out["setup_buy"] = buy.fillna(False).astype(bool)
    out["setup_sell"] = sell.fillna(False).astype(bool)
    out["signal_sl_distance"] = sl_distance
    out["signal_tp_distance"] = sl_distance * p.rr
    out["predicted_probability_buy"] = out["setup_buy"].astype(float)
    out["predicted_probability_sell"] = out["setup_sell"].astype(float)
    return out
