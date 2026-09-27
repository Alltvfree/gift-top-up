"""Feature engineering for Kronos — pure pandas/numpy, no MT5 dependency,
so (unlike mt5_data.py) this is fully unit-testable without a live terminal.

Input: a DataFrame with columns [time, open, high, low, close, tick_volume],
one row per closed bar, sorted ascending by time. Output: the same frame
with feature columns appended.

No-lookahead guarantee: every feature at row i is computed only from rows
<= i (rolling/ewm windows, `.diff()`, `.shift()`) — never from row i+1 or
later. That guarantee is what makes it safe to run this identical function
in both offline training and live inference; labels.py is the one place
that's allowed to look forward, because a label needs to know the outcome.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)  # neutral before enough history exists to compute a ratio


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = _ema(close, fast) - _ema(close, slow)
    signal_line = _ema(macd_line, signal)
    return macd_line, signal_line, macd_line - signal_line


def _stochastic(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    lowest_low = low.rolling(period, min_periods=period).min()
    highest_high = high.rolling(period, min_periods=period).max()
    denom = (highest_high - lowest_low).replace(0, np.nan)
    return (100 * (close - lowest_low) / denom).fillna(50.0)


def _bollinger_width(close: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.Series:
    mid = close.rolling(period, min_periods=period).mean()
    std = close.rolling(period, min_periods=period).std()
    width = (2 * num_std * std) / mid.replace(0, np.nan)
    return width.fillna(0.0)


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index
    )
    atr = _atr(high, low, close, period).replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)).fillna(0.0)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


SESSION_HOURS_UTC = {
    "asian": (0, 8),
    "london": (7, 16),
    "new_york": (12, 21),
}


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    close, high, low, open_ = out["close"], out["high"], out["low"], out["open"]

    # Trend: EMAs, their slopes, and price's *relative* distance from each
    # (a percentage, not a raw price difference) — so the model isn't tied
    # to XAUUSD's absolute level, which drifts enormously over years of
    # training data.
    for span in (9, 20, 50, 100, 200):
        ema = _ema(close, span)
        out[f"ema_{span}_slope"] = ema.diff()
        out[f"dist_from_ema_{span}_pct"] = (close - ema) / ema.replace(0, np.nan)

    # Momentum
    out["rsi_14"] = _rsi(close, 14)
    macd_line, signal_line, hist = _macd(close)
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_hist"] = hist
    out["stoch_14"] = _stochastic(high, low, close, 14)
    out["roc_10"] = close.pct_change(10)

    # Volatility
    atr = _atr(high, low, close, 14)
    out["atr_pct"] = atr / close.replace(0, np.nan)
    out["bb_width_20"] = _bollinger_width(close, 20)
    out["candle_range_pct"] = (high - low) / close.replace(0, np.nan)
    out["rolling_std_20"] = close.pct_change().rolling(20, min_periods=20).std()
    out["adx_14"] = _adx(high, low, close, 14)

    # Market structure — simple higher-high / lower-low flags, one bar at a
    # time (not the centered rolling-window swing detector some libraries
    # use, since a centered window peeks at future bars).
    out["higher_high"] = (high > high.shift(1)).astype(int)
    out["lower_low"] = (low < low.shift(1)).astype(int)

    # Candle structure
    body = (close - open_).abs()
    full_range = (high - low).replace(0, np.nan)
    upper_body = np.maximum(close, open_)
    lower_body = np.minimum(close, open_)
    out["body_pct_of_range"] = (body / full_range).fillna(0.0)
    out["upper_wick_pct"] = ((high - upper_body) / full_range).fillna(0.0)
    out["lower_wick_pct"] = ((lower_body - low) / full_range).fillna(0.0)
    out["bullish_candle"] = (close > open_).astype(int)

    # Time / session — `time` must be tz-aware UTC (mt5_data.py returns it
    # that way).
    hours = out["time"].dt.hour
    out["hour"] = hours
    out["day_of_week"] = out["time"].dt.dayofweek
    for name, (start, end) in SESSION_HOURS_UTC.items():
        out[f"session_{name}"] = ((hours >= start) & (hours < end)).astype(int)

    return out


def merge_higher_timeframe(base: pd.DataFrame, higher: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Attach a higher timeframe's already-computed feature columns onto
    the base timeframe by time. `direction="backward"` is what prevents
    lookahead here: each base-timeframe row only ever sees the most
    recently *closed* higher-timeframe bar as of that moment, never one
    that closes later.
    """
    h = higher.add_prefix(f"{prefix}_")
    h = h.rename(columns={f"{prefix}_time": "time"})
    return pd.merge_asof(
        base.sort_values("time"), h.sort_values("time"), on="time", direction="backward"
    )


FEATURE_COLUMNS = [
    "ema_9_slope", "ema_20_slope", "ema_50_slope", "ema_100_slope", "ema_200_slope",
    "dist_from_ema_9_pct", "dist_from_ema_20_pct", "dist_from_ema_50_pct",
    "dist_from_ema_100_pct", "dist_from_ema_200_pct",
    "rsi_14", "macd", "macd_signal", "macd_hist", "stoch_14", "roc_10",
    "atr_pct", "bb_width_20", "candle_range_pct", "rolling_std_20", "adx_14",
    "higher_high", "lower_low",
    "body_pct_of_range", "upper_wick_pct", "lower_wick_pct", "bullish_candle",
    "hour", "day_of_week", "session_asian", "session_london", "session_new_york",
]
