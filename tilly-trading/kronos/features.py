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

from collections import deque

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


# How many bars must pass on both sides of a high/low before it counts as
# a confirmed swing point. A swing at position i needs bars [i-k, i+k] to
# know it was the local extreme — the most recent k bars can never be
# confirmed yet, which is correct, not a bug: you genuinely can't know a
# bar was a swing high until enough time has passed without a higher one.
SWING_LAG = 5

# Only the most recent N confirmed swing highs/lows are tracked as
# potential support/resistance — old levels lose relevance, and bounding
# this keeps the per-bar scan cheap (O(N) instead of O(bars)) even over
# 50,000+ bars of training history.
MAX_TRACKED_LEVELS = 20


def _market_structure(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.DataFrame:
    """Distance to the nearest confirmed swing-high (resistance, above
    price) and swing-low (support, below price), whether price has broken
    beyond every recently confirmed level in either direction, and a set of
    "smart money concepts" style event features built on the SAME confirmed
    swings: break of structure (BOS), change of character (CHoCH), and
    liquidity sweeps.

    Lookahead-safe by construction: at bar t, only swings at position
    i <= t - SWING_LAG are used, since a swing at i needs bars up to i+k to
    be confirmed at all. This is the one thing in this file most tempting
    to get wrong — a naive centered rolling-window swing detector (used
    without this confirmation-lag bookkeeping) would silently leak future
    bars into a "live" feature. Reused for every feature below rather than
    re-detecting swings a second way, so they can't silently drift apart —
    an earlier reference implementation of BOS/CHoCH (a ChatGPT-authored
    prototype reviewed alongside this one) computed its own separate pivot
    detector via `.shift(left).rolling(left+right+1).max()`, which doesn't
    actually implement a two-sided confirmed pivot at all (it compares each
    bar's high to a max computed from an *earlier*, already-passed window)
    — no lookahead, but not a correct swing detector either. This function
    avoids that by building strictly on the swing detector above, already
    tested against hand-constructed price paths.

    BOS/liquidity-sweep definitions:
      - bos_bull/bos_bear ("break of structure"): an EVENT flag — fires only
        on the bar whose close first crosses beyond the most recently
        confirmed swing high/low (broke_resistance/broke_support are the
        persistent-state version of the same idea, staying 1 every bar
        price remains beyond the level).
      - liquidity_sweep_high/low: this bar's wick alone pokes beyond the
        most recently confirmed swing level but closes back on the other
        side of it (a "stop hunt") — non-lookahead by construction, since it
        only compares the CURRENT bar's own high/low/close against an
        already-confirmed prior level.
      - structure_bias: +1 while the two most recently confirmed swings are
        a higher high AND a higher low (bullish), -1 for a lower high and
        lower low (bearish), 0 while ambiguous or not enough confirmed
        swings exist yet.
      - choch ("change of character"): fires the bar structure_bias flips
        from bullish to bearish or back.
    """
    n = len(close)
    h = high.to_numpy()
    l = low.to_numpy()
    c = close.to_numpy()

    is_swing_high = np.zeros(n, dtype=bool)
    is_swing_low = np.zeros(n, dtype=bool)
    for i in range(SWING_LAG, n - SWING_LAG):
        # Strict dominance over every OTHER bar in the window, not just
        # tying the window max: a flat/tied stretch (real markets do have
        # these — thin liquidity, or repeated prints) would otherwise let
        # every bar in it claim to be a "swing high" against itself.
        others_h = np.delete(h[i - SWING_LAG : i + SWING_LAG + 1], SWING_LAG)
        others_l = np.delete(l[i - SWING_LAG : i + SWING_LAG + 1], SWING_LAG)
        if h[i] > others_h.max():
            is_swing_high[i] = True
        if l[i] < others_l.min():
            is_swing_low[i] = True

    dist_to_resistance_pct = np.full(n, np.nan)
    dist_to_support_pct = np.full(n, np.nan)
    broke_resistance = np.zeros(n, dtype=int)
    broke_support = np.zeros(n, dtype=int)
    bos_bull = np.zeros(n, dtype=int)
    bos_bear = np.zeros(n, dtype=int)
    liquidity_sweep_high = np.zeros(n, dtype=int)
    liquidity_sweep_low = np.zeros(n, dtype=int)
    structure_bias = np.zeros(n, dtype=int)
    choch = np.zeros(n, dtype=int)

    confirmed_highs: deque[float] = deque(maxlen=MAX_TRACKED_LEVELS)
    confirmed_lows: deque[float] = deque(maxlen=MAX_TRACKED_LEVELS)
    confirmed_up_to = -1  # last position whose swing status is knowable as of the current bar

    last_swing_high = prev_swing_high = np.nan
    last_swing_low = prev_swing_low = np.nan
    bias = 0

    for t in range(n):
        newly_confirmable = t - SWING_LAG
        while confirmed_up_to < newly_confirmable and confirmed_up_to + 1 < n:
            confirmed_up_to += 1
            i = confirmed_up_to
            if is_swing_high[i]:
                confirmed_highs.append(h[i])
                prev_swing_high, last_swing_high = last_swing_high, h[i]
            if is_swing_low[i]:
                confirmed_lows.append(l[i])
                prev_swing_low, last_swing_low = last_swing_low, l[i]

        above = [p for p in confirmed_highs if p > c[t]]
        below = [p for p in confirmed_lows if p < c[t]]
        if above:
            dist_to_resistance_pct[t] = (min(above) - c[t]) / c[t]
        elif confirmed_highs:
            # Broke through every tracked level — 0.0 is a real, meaningful
            # value here ("at or beyond the ceiling"), not "unknown". Left
            # as NaN this would silently drop every breakout row wherever
            # callers do dropna(subset=FEATURE_COLUMNS) for the warmup
            # period — exactly the rows a breakout feature exists to catch.
            dist_to_resistance_pct[t] = 0.0
            broke_resistance[t] = 1
        if below:
            dist_to_support_pct[t] = (c[t] - max(below)) / c[t]
        elif confirmed_lows:
            dist_to_support_pct[t] = 0.0
            broke_support[t] = 1

        prev_close = c[t - 1] if t > 0 else np.nan
        if np.isfinite(last_swing_high) and c[t] > last_swing_high and not (np.isfinite(prev_close) and prev_close > last_swing_high):
            bos_bull[t] = 1
        if np.isfinite(last_swing_low) and c[t] < last_swing_low and not (np.isfinite(prev_close) and prev_close < last_swing_low):
            bos_bear[t] = 1

        if np.isfinite(last_swing_high) and h[t] > last_swing_high and c[t] < last_swing_high:
            liquidity_sweep_high[t] = 1
        if np.isfinite(last_swing_low) and l[t] < last_swing_low and c[t] > last_swing_low:
            liquidity_sweep_low[t] = 1

        if (
            np.isfinite(last_swing_high) and np.isfinite(prev_swing_high)
            and np.isfinite(last_swing_low) and np.isfinite(prev_swing_low)
        ):
            if last_swing_high > prev_swing_high and last_swing_low > prev_swing_low:
                bias = 1
            elif last_swing_high < prev_swing_high and last_swing_low < prev_swing_low:
                bias = -1
        structure_bias[t] = bias
        if t > 0 and bias != 0 and structure_bias[t - 1] != bias and structure_bias[t - 1] != 0:
            choch[t] = 1

    return pd.DataFrame(
        {
            "dist_to_resistance_pct": dist_to_resistance_pct,
            "dist_to_support_pct": dist_to_support_pct,
            "broke_resistance": broke_resistance,
            "broke_support": broke_support,
            "bos_bull": bos_bull,
            "bos_bear": bos_bear,
            "liquidity_sweep_high": liquidity_sweep_high,
            "liquidity_sweep_low": liquidity_sweep_low,
            "structure_bias": structure_bias,
            "choch": choch,
        },
        index=close.index,
    )


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

    # Market structure — simple bar-to-bar higher-high / lower-low flags,
    # real support/resistance levels, and BOS/CHoCH/liquidity-sweep event
    # features, all from confirmed swing points (_market_structure handles
    # its own no-lookahead bookkeeping).
    out["higher_high"] = (high > high.shift(1)).astype(int)
    out["lower_low"] = (low < low.shift(1)).astype(int)
    ms = _market_structure(high, low, close)
    for col in ms.columns:
        out[col] = ms[col]

    # Fair value gap (FVG) proxy — a 3-candle imbalance: this bar's low sits
    # above the high from 2 bars ago (bullish gap) or vice versa. Pure
    # .shift() comparison, no swing-confirmation dependency, non-lookahead.
    out["fvg_bull"] = (low > high.shift(2)).astype(int)
    out["fvg_bear"] = (high < low.shift(2)).astype(int)

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
    the base timeframe by time.

    Critical subtlety: MT5 (mt5_data.download_history) labels every candle
    by its OPEN time, not its close time. A naive backward-asof merge on
    raw open timestamps would attach a higher-timeframe bar that has
    *started* but not yet *closed* as of a given base row — e.g. at 10:05,
    the H1 bar labeled "10:00" spans 10:00-11:00 and hasn't finished
    forming yet, but in historical data its recorded close/high/low
    already reflect everything through 11:00. Matching it to a 10:05 base
    row would leak the rest of that hour backward in time. Fixed by
    shifting the higher timeframe's match key forward by its own bar
    duration (auto-detected from the median gap between its own rows)
    before merging — a bar only becomes eligible once it has actually
    closed. The output's own `time` column is unaffected (it's the base
    row's real timestamp throughout); only the *matching* key is shifted.
    """
    if len(higher) < 2:
        raise ValueError("Need at least 2 higher-timeframe rows to detect its bar duration.")
    bar_duration = higher["time"].diff().median()

    h = higher.add_prefix(f"{prefix}_")
    h = h.rename(columns={f"{prefix}_time": "time"})
    h["time"] = h["time"] + bar_duration  # now represents each bar's CLOSE time, for matching only

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
    "dist_to_resistance_pct", "dist_to_support_pct", "broke_resistance", "broke_support",
    "bos_bull", "bos_bear", "liquidity_sweep_high", "liquidity_sweep_low",
    "structure_bias", "choch", "fvg_bull", "fvg_bear",
    "body_pct_of_range", "upper_wick_pct", "lower_wick_pct", "bullish_candle",
    "hour", "day_of_week", "session_asian", "session_london", "session_new_york",
]
